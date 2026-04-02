# Playlist Bug Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix iCloud sync race condition that causes old tracks to persist when rebuilding the Music Discovery playlist (fixes #1)

**Architecture:** Simplify `setup_playlist()` to always delete and recreate any non-empty playlist, removing the unreliable `delete tracks` code path. The delete-and-recreate approach is already proven reliable in the oversized-playlist path.

**Tech Stack:** AppleScript, osascript

---

## Chunk 1: Fix setup_playlist and Tests

### Task 1: Simplify setup_playlist() to always delete-and-recreate

**Files:**
- Modify: `music_discovery.py:750-832`

**Context:** `setup_playlist()` currently has three branches after counting tracks:
1. `track_count == -1` — playlist missing, create it (correct)
2. `track_count > MAX_PLAYLIST_TRACKS` — delete playlist, recreate (correct, reliable)
3. `track_count > 0` — `delete tracks of user playlist` (BUGGY — iCloud sync restores tracks)

The fix collapses branches 2 and 3 into a single `track_count > 0` branch that always deletes the playlist and recreates it. The `MAX_PLAYLIST_TRACKS` threshold check and the `delete tracks` code path are both removed. The post-clear verification step is also removed since a freshly created playlist is guaranteed empty.

- [ ] **Step 1: Replace setup_playlist() body**

Replace lines 750-832 of `music_discovery.py` (the entire `setup_playlist` function) with:

```python
def setup_playlist():
    """Create or reset the 'Music Discovery' playlist.
    If the playlist exists and contains tracks, deletes the whole playlist
    and creates a fresh one.  This avoids an iCloud Music Library sync race
    where 'delete tracks' can leave stale track references behind.
    Returns True on success, False on failure."""

    # Step 1: Check if playlist exists and how big it is
    count_script = '''
tell application "Music"
    if (exists user playlist "Music Discovery") then
        return count of tracks of user playlist "Music Discovery"
    else
        return -1
    end if
end tell
'''
    out, code = _run_applescript(count_script)
    if code != 0:
        log.error("Could not check for existing playlist.")
        return False

    try:
        track_count = int(out)
    except ValueError:
        log.error(f"Unexpected response checking playlist: {out}")
        return False

    # Step 2: Handle based on state
    if track_count == -1:
        # Playlist doesn't exist — create it
        _, code = _run_applescript('''
tell application "Music"
    make new user playlist with properties {name:"Music Discovery"}
end tell
''')
        return code == 0

    if track_count > 0:
        # Playlist has tracks — delete and recreate to avoid iCloud sync issues
        log.info(f"Existing playlist has {track_count} tracks — deleting and recreating.")
        _, code = _run_applescript('''
tell application "Music"
    delete user playlist "Music Discovery"
end tell
''')
        if code != 0:
            log.error("Could not delete existing playlist.")
            return False
        time.sleep(1)
        _, code = _run_applescript('''
tell application "Music"
    make new user playlist with properties {name:"Music Discovery"}
end tell
''')
        return code == 0

    # track_count == 0 — playlist exists and is already empty
    return True
```

- [ ] **Step 2: Run the existing test suite to check baseline**

Run: `python3 -m pytest tests/test_music_discovery.py -k "setup_playlist" -v`
Expected: `test_setup_playlist_returns_true_on_success` and `test_setup_playlist_returns_false_on_failure` PASS. `test_setup_playlist_script_references_playlist_name` PASS.

---

### Task 2: Update and add tests for the new setup_playlist behavior

**Files:**
- Modify: `tests/test_music_discovery.py:682-703`

**Context:** The existing tests cover playlist-missing and error paths. We need to add tests for:
- Non-empty playlist triggers delete-and-recreate (the fixed path)
- Already-empty playlist returns True without delete
- Delete failure returns False

- [ ] **Step 1: Replace the setup_playlist test block**

Replace lines 682-703 of `tests/test_music_discovery.py` (from the section comment through the last existing test) with:

```python
# ── setup_playlist ────────────────────────────────────────

def test_setup_playlist_creates_if_missing(monkeypatch):
    """Returns True and creates playlist when it doesn't exist."""
    responses = iter([("-1", 0), ("", 0)])
    monkeypatch.setattr(md, "_run_applescript", lambda script: next(responses))
    assert md.setup_playlist() is True

def test_setup_playlist_returns_false_on_failure(monkeypatch):
    """Returns False when osascript fails."""
    monkeypatch.setattr(md, "_run_applescript", lambda script: ("error", 1))
    assert md.setup_playlist() is False

def test_setup_playlist_deletes_and_recreates_nonempty(monkeypatch):
    """Non-empty playlist is deleted and recreated (not just cleared)."""
    scripts_called = []
    responses = iter([
        ("25", 0),   # count query — 25 tracks exist
        ("", 0),     # delete playlist
        ("", 0),     # create new playlist
    ])
    def fake_run(script):
        scripts_called.append(script)
        return next(responses)
    monkeypatch.setattr(md, "_run_applescript", fake_run)
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert md.setup_playlist() is True
    # The second call should be a delete of the whole playlist, not delete tracks
    assert "delete user playlist" in scripts_called[1]
    assert "delete tracks" not in scripts_called[1]

def test_setup_playlist_empty_playlist_is_noop(monkeypatch):
    """Already-empty playlist returns True without any delete or create."""
    call_count = [0]
    def fake_run(script):
        call_count[0] += 1
        return ("0", 0)  # count query — 0 tracks
    monkeypatch.setattr(md, "_run_applescript", fake_run)
    assert md.setup_playlist() is True
    assert call_count[0] == 1  # only the count query was called

def test_setup_playlist_delete_failure_returns_false(monkeypatch):
    """Returns False when deleting existing playlist fails."""
    responses = iter([
        ("10", 0),    # count query — 10 tracks exist
        ("error", 1), # delete fails
    ])
    monkeypatch.setattr(md, "_run_applescript", lambda script: next(responses))
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert md.setup_playlist() is False

def test_setup_playlist_script_references_playlist_name(monkeypatch):
    """The AppleScript contains the playlist name."""
    captured = []
    def fake_run(script):
        captured.append(script)
        return ("", 0)
    monkeypatch.setattr(md, "_run_applescript", fake_run)
    md.setup_playlist()
    assert "Music Discovery" in captured[0]
```

- [ ] **Step 2: Run all setup_playlist tests**

Run: `python3 -m pytest tests/test_music_discovery.py -k "setup_playlist" -v`
Expected: All 6 tests PASS.

- [ ] **Step 3: Run full test suite to check for regressions**

Run: `python3 -m pytest tests/test_music_discovery.py -v`
Expected: All tests PASS.

- [ ] **Step 4: Commit with issue reference**

```bash
git add music_discovery.py tests/test_music_discovery.py
git commit -m "fix: always delete-and-recreate playlist to avoid iCloud sync stale tracks

Removes the unreliable 'delete tracks' code path from setup_playlist().
Any non-empty playlist is now deleted and recreated, matching the approach
already used for oversized playlists.

Fixes #1"
```
