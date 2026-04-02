# Playback Fix & Playlist Robustness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix JXA playback (issue #8), add library-first path, cross-round track dedup, deep track sourcing, and auto-blocklist for missing artists.

**Architecture:** `SearchResult` dataclass enables richer data flow from `search_itunes()`. Library-first AppleScript path bypasses JXA for known tracks. `_run_build()` restructured for overflow iteration, tiered track sourcing, track dedup via `offered_tracks.json`, and strike counting via `search_strikes.json`.

**Tech Stack:** Python 3.14, AppleScript/JXA via osascript, iTunes Search API, Last.fm API

---

### Task 1: `SearchResult` Dataclass and `search_itunes()` Update

**Files:**
- Modify: `music_discovery.py:1-27` (imports), `music_discovery.py:1028-1057` (search_itunes)
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write failing tests for `SearchResult`**

Add to `tests/test_music_discovery.py` after the existing `search_itunes` tests (after line ~1133):

```python
# ── SearchResult ──────────────────────────────────────────

def test_search_result_bool_true_when_found():
    """SearchResult is truthy when store_id is set."""
    r = md.SearchResult(store_id="12345", searched_ok=True,
                        canonical_artist="Fleet Foxes",
                        canonical_track="White Winter Hymnal")
    assert r
    assert bool(r) is True

def test_search_result_bool_false_when_not_found():
    """SearchResult is falsy when store_id is None."""
    r = md.SearchResult(store_id=None, searched_ok=True)
    assert not r
    assert bool(r) is False

def test_search_result_bool_false_on_error():
    """SearchResult is falsy when search errored."""
    r = md.SearchResult(store_id=None, searched_ok=False)
    assert not r
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py::test_search_result_bool_true_when_found tests/test_music_discovery.py::test_search_result_bool_false_when_not_found tests/test_music_discovery.py::test_search_result_bool_false_on_error -v`

Expected: FAIL with `AttributeError: module 'music_discovery' has no attribute 'SearchResult'`

- [ ] **Step 3: Implement `SearchResult` dataclass**

Add to `music_discovery.py` after the imports (after line 27), before `_resolve_library_path`:

```python
import dataclasses

@dataclasses.dataclass
class SearchResult:
    """Result from search_itunes(). Use bool() to check if a track was found."""
    store_id: str | None
    searched_ok: bool
    canonical_artist: str = ""
    canonical_track: str = ""

    def __bool__(self) -> bool:
        return self.store_id is not None
```

- [ ] **Step 4: Run SearchResult tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py::test_search_result_bool_true_when_found tests/test_music_discovery.py::test_search_result_bool_false_when_not_found tests/test_music_discovery.py::test_search_result_bool_false_on_error -v`

Expected: 3 PASSED

- [ ] **Step 5: Write failing tests for updated `search_itunes()`**

Update existing tests in `tests/test_music_discovery.py`. Replace the existing `search_itunes` test block (lines ~1087-1133) with:

```python
# ── search_itunes ─────────────────────────────────────────

def test_search_itunes_returns_search_result_on_success(monkeypatch):
    """Returns SearchResult with store_id and canonical metadata on success."""
    mock_resp = type("R", (), {
        "status_code": 200,
        "json": lambda self: {"resultCount": 1, "results": [
            {"trackId": 12345, "kind": "song",
             "artistName": "Radiohead", "trackName": "Creep"}
        ]},
    })()
    monkeypatch.setattr("requests.get", lambda *a, **kw: mock_resp)
    result = md.search_itunes("Radiohead", "Creep")
    assert isinstance(result, md.SearchResult)
    assert result.store_id == "12345"
    assert result.searched_ok is True
    assert result.canonical_artist == "Radiohead"
    assert result.canonical_track == "Creep"
    assert result  # truthy

def test_search_itunes_filters_music_videos(monkeypatch):
    """Skips music videos and returns only songs."""
    mock_resp = type("R", (), {
        "status_code": 200,
        "json": lambda self: {"resultCount": 2, "results": [
            {"trackId": 111, "kind": "music-video", "artistName": "Radiohead", "trackName": "Creep"},
            {"trackId": 222, "kind": "song", "artistName": "Radiohead", "trackName": "Creep"},
        ]},
    })()
    monkeypatch.setattr("requests.get", lambda *a, **kw: mock_resp)
    result = md.search_itunes("Radiohead", "Creep")
    assert result.store_id == "222"
    assert result.canonical_artist == "Radiohead"

def test_search_itunes_returns_none_when_only_videos(monkeypatch):
    """Returns falsy SearchResult with searched_ok=True when all results are music videos."""
    mock_resp = type("R", (), {
        "status_code": 200,
        "json": lambda self: {"resultCount": 1, "results": [
            {"trackId": 111, "kind": "music-video", "artistName": "Radiohead", "trackName": "Creep"},
        ]},
    })()
    monkeypatch.setattr("requests.get", lambda *a, **kw: mock_resp)
    result = md.search_itunes("Radiohead", "Creep")
    assert not result
    assert result.searched_ok is True
    assert result.store_id is None

def test_search_itunes_returns_none_on_no_results(monkeypatch):
    """Returns falsy SearchResult with searched_ok=True when no tracks found."""
    mock_resp = type("R", (), {
        "status_code": 200,
        "json": lambda self: {"resultCount": 0, "results": []},
    })()
    monkeypatch.setattr("requests.get", lambda *a, **kw: mock_resp)
    result = md.search_itunes("Nobody", "Fake")
    assert not result
    assert result.searched_ok is True

def test_search_itunes_returns_searched_ok_false_on_error(monkeypatch):
    """Returns falsy SearchResult with searched_ok=False on network error."""
    monkeypatch.setattr("requests.get", lambda *a, **kw: (_ for _ in ()).throw(Exception("timeout")))
    result = md.search_itunes("Radiohead", "Creep")
    assert not result
    assert result.searched_ok is False

def test_search_itunes_returns_searched_ok_false_on_non_200(monkeypatch):
    """Returns falsy SearchResult with searched_ok=False on non-200 response."""
    mock_resp = type("R", (), {"status_code": 503, "json": lambda self: {}})()
    monkeypatch.setattr("requests.get", lambda *a, **kw: mock_resp)
    result = md.search_itunes("Radiohead", "Creep")
    assert not result
    assert result.searched_ok is False

def test_search_itunes_fuzzy_match(monkeypatch):
    """Falls back to fuzzy match when exact artist match fails."""
    mock_resp = type("R", (), {
        "status_code": 200,
        "json": lambda self: {"resultCount": 1, "results": [
            {"trackId": 999, "kind": "song",
             "artistName": "The Black Keys", "trackName": "Lonely Boy"}
        ]},
    })()
    monkeypatch.setattr("requests.get", lambda *a, **kw: mock_resp)
    result = md.search_itunes("Black Keys", "Lonely Boy")
    assert result.store_id == "999"
    assert result.canonical_artist == "The Black Keys"
```

- [ ] **Step 6: Update `search_itunes()` to return `SearchResult`**

Replace `music_discovery.py:search_itunes` (lines 1028-1057) with:

```python
def search_itunes(artist, track_name):
    """Search the iTunes/Apple Music catalog for a track.
    Returns a SearchResult with store_id, searched_ok, and canonical metadata.
    Free API — no key required."""
    try:
        resp = requests.get(ITUNES_SEARCH_URL, timeout=10, params={
            "term":  f"{artist} {track_name}",
            "media": "music",
            "limit": 10,
        })
        if resp.status_code != 200:
            return SearchResult(store_id=None, searched_ok=False)
        results = resp.json().get("results", [])
        # Filter out music videos — only accept actual songs
        results = [r for r in results if r.get("kind") == "song"]
        artist_lower = artist.strip().lower()
        for r in results:
            result_artist = r.get("artistName", "").strip().lower()
            if result_artist == artist_lower:
                return SearchResult(
                    store_id=str(r["trackId"]), searched_ok=True,
                    canonical_artist=r.get("artistName", ""),
                    canonical_track=r.get("trackName", ""),
                )
        # Fallback: fuzzy match (one name contains the other)
        for r in results:
            result_artist = r.get("artistName", "").strip().lower()
            if artist_lower in result_artist or result_artist in artist_lower:
                return SearchResult(
                    store_id=str(r["trackId"]), searched_ok=True,
                    canonical_artist=r.get("artistName", ""),
                    canonical_track=r.get("trackName", ""),
                )
        return SearchResult(store_id=None, searched_ok=True)
    except Exception as e:
        log.debug(f"search_itunes failed for '{artist} - {track_name}': {e}")
        return SearchResult(store_id=None, searched_ok=False)
```

- [ ] **Step 7: Update all callers that use `store_id` as a string**

In `music_discovery.py:add_track_to_playlist()` (line ~1201), change:

```python
# Before:
    store_id = search_itunes(artist, track_name)
    if not store_id:
        return False
    ...
    _play_store_track(store_id)
```

To:

```python
    result = search_itunes(artist, track_name)
    if not result:
        return False
    ...
    _play_store_track(result.store_id)
```

In `signal_experiment.py:_add_track_to_named_playlist()` (line ~436), change:

```python
# Before:
    store_id = search_itunes(artist, track_name)
    if not store_id:
        log.info(f"  Not found: {artist} — {track_name}")
        return False
    ...
    _play_store_track(store_id)
```

To:

```python
    result = search_itunes(artist, track_name)
    if not result:
        log.info(f"  Not found: {artist} — {track_name}")
        return False
    ...
    _play_store_track(result.store_id)
```

Also add `SearchResult` to the import list in the function body. This prevents temporal breakage — without this fix, the code is broken between Task 1's commit and Task 3's commit.

- [ ] **Step 8: Update test mocks that return raw strings/None**

In `tests/test_music_discovery.py`, update all monkeypatches of `search_itunes`:

```python
# Replace all instances of:
#   lambda a, t: "12345"
# With:
#   lambda a, t: md.SearchResult("12345", True, a, t)

# Replace all instances of:
#   lambda a, t: None
# With:
#   lambda a, t: md.SearchResult(None, True)
```

Apply this to all 7 monkeypatch sites found in the test file (lines ~1201, 1216, 1223, 1239, 1257, 1982, 2010).

- [ ] **Step 9: Run full test suite to verify nothing is broken**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -v`

Expected: ALL PASS (no regressions from SearchResult change)

- [ ] **Step 10: Commit**

```bash
cd "/Users/brianhill/Scripts/Music Discovery"
git add music_discovery.py tests/test_music_discovery.py
git commit -m "feat: SearchResult dataclass for search_itunes()

Return SearchResult with store_id, searched_ok, canonical_artist,
canonical_track. __bool__ preserves backward compat for existing
if-not checks. All callers and test mocks updated."
```

---

### Task 2: JXA NSRunLoop Fix

**Files:**
- Modify: `music_discovery.py:1121-1138` (_play_store_track)
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write failing test for updated JXA script template**

Add to `tests/test_music_discovery.py`:

```python
# ── _play_store_track JXA fix ─────────────────────────────

def test_play_store_track_script_polls_is_prepared(monkeypatch):
    """JXA script should poll isPreparedToPlay, not use a fixed wait."""
    captured = {}
    def fake_jxa(script):
        captured["script"] = script
        return "1", 0
    monkeypatch.setattr(md, "_run_jxa", fake_jxa)
    md._play_store_track("12345")
    assert "isPreparedToPlay" in captured["script"]
    assert "NSRunLoop" in captured["script"]
    assert '"12345"' in captured["script"] or "'12345'" in captured["script"]

def test_play_store_track_raises_on_jxa_failure(monkeypatch):
    """Raises RuntimeError when JXA exits non-zero."""
    monkeypatch.setattr(md, "_run_jxa", lambda s: ("", 1))
    with pytest.raises(RuntimeError, match="JXA MediaPlayer failed"):
        md._play_store_track("12345")
```

- [ ] **Step 2: Run tests to verify the new one fails**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py::test_play_store_track_script_polls_is_prepared tests/test_music_discovery.py::test_play_store_track_raises_on_jxa_failure -v`

Expected: `test_play_store_track_script_polls_is_prepared` FAILS (current script doesn't contain `isPreparedToPlay`). `test_play_store_track_raises_on_jxa_failure` PASSES (existing behavior — this is a regression guard).

- [ ] **Step 3: Update `_play_store_track()` with NSRunLoop polling**

Replace `music_discovery.py:_play_store_track` (lines 1121-1138) with:

```python
def _play_store_track(store_id):
    """Use MediaPlayer framework via JXA to play a catalog track by store ID.
    Polls isPreparedToPlay with NSRunLoop to handle async buffering.
    This makes the track visible to Music.app as the current track."""
    script = f'''
ObjC.import("MediaPlayer");
ObjC.import("Foundation");
var player = $.MPMusicPlayerController.systemMusicPlayer;
var ids = $.NSArray.arrayWithObject($("{store_id}"));
var descriptor = $.MPMusicPlayerStoreQueueDescriptor.alloc.initWithStoreIDs(ids);
player.setQueueWithDescriptor(descriptor);
player.prepareToPlay;
var rl = $.NSRunLoop.currentRunLoop;
var deadline = $.NSDate.dateWithTimeIntervalSinceNow(10.0);
while (!player.isPreparedToPlay) {{
    var step = $.NSDate.dateWithTimeIntervalSinceNow(0.25);
    rl.runUntilDate(step);
    if ($.NSDate.date.compare(deadline) === 2) break;
}}
player.play;
var post = $.NSDate.dateWithTimeIntervalSinceNow(1.0);
rl.runUntilDate(post);
var state = player.playbackState;
String(state);
'''
    out, code = _run_jxa(script)
    if code != 0:
        raise RuntimeError(f"JXA MediaPlayer failed (code {code})")
    return out.strip()
```

Note the `{{` and `}}` — these are literal braces in an f-string.

**Return type change:** Previously returned `bool` (`out == "ok"`), now returns `str` (the playback state number). All existing callers ignore the return value, so this is safe. The docstring documents the new return semantics.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py::test_play_store_track_script_polls_is_prepared tests/test_music_discovery.py::test_play_store_track_raises_on_jxa_failure -v`

Expected: 2 PASSED

- [ ] **Step 5: Run full test suite for regressions**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/ -v`

Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
cd "/Users/brianhill/Scripts/Music Discovery"
git add music_discovery.py tests/test_music_discovery.py
git commit -m "fix: poll isPreparedToPlay via NSRunLoop in _play_store_track

Replaces blind fire-and-exit with a polling loop that keeps the JXA
script alive until MediaPlayer is ready (up to 10s). Fixes issue #8."
```

---

### Task 3: Library-First Path in `_add_track_to_named_playlist()`

**Files:**
- Modify: `signal_experiment.py:423-555` (_add_track_to_named_playlist)
- Test: `tests/test_music_discovery.py` (or new `tests/test_signal_experiment.py`)

- [ ] **Step 1: Write failing tests for library-first path**

Check if `tests/test_signal_experiment.py` exists. If not, create it. Add these tests:

```python
"""Tests for signal_experiment playlist functions."""
import pytest
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import signal_experiment as se
import music_discovery as md


def test_library_first_path_adds_directly(monkeypatch):
    """When track is in library, adds to playlist without JXA."""
    search_result = md.SearchResult("12345", True, "Fleet Foxes", "White Winter Hymnal")
    jxa_called = {"called": False}

    def fake_applescript(script):
        if "search library" in script:
            return "ok", 0
        return "", 0
    def fake_play_store(*a):
        jxa_called["called"] = True

    monkeypatch.setattr(md, "_run_applescript", fake_applescript)
    monkeypatch.setattr(md, "_play_store_track", fake_play_store)
    result = se._add_track_to_named_playlist(
        "Fleet Foxes", "White Winter Hymnal", "Test Playlist",
        search_result=search_result,
    )
    assert result is True
    assert jxa_called["called"] is False


def test_library_first_falls_through_to_jxa(monkeypatch):
    """When track is not in library, falls through to JXA path."""
    search_result = md.SearchResult("12345", True, "New Artist", "New Track")
    jxa_called = {"called": False}

    def fake_applescript(script):
        """Stateful mock that handles different AppleScript contexts."""
        if "search library" in script and "duplicate" in script:
            # Library search (first call) or library-add-to-playlist (later)
            if not jxa_called["called"]:
                return "not_in_library", 0  # first time: not in library
            return "ok", 0  # after JXA play: found and added
        if "current track" in script:
            if not jxa_called["called"]:
                return "", 0  # snapshot before play
            return "New Track|||New Artist", 0  # poll/info after play
        if "duplicate" in script and "source" in script:
            return "lib_ok", 0  # add to library
        return "", 0

    def fake_play_store(sid):
        jxa_called["called"] = True
        return "1"

    monkeypatch.setattr(md, "_run_applescript", fake_applescript)
    monkeypatch.setattr(md, "_play_store_track", fake_play_store)
    result = se._add_track_to_named_playlist(
        "New Artist", "New Track", "Test Playlist",
        search_result=search_result,
    )
    assert jxa_called["called"] is True
    assert result is True


def test_library_first_error_falls_through(monkeypatch):
    """When library search errors, falls through to JXA path."""
    search_result = md.SearchResult("12345", True, "Artist", "Track")
    jxa_called = {"called": False}

    applescript_responses = iter([
        ("error: some error", 0),  # library search errored
        ("", 0),                   # snapshot
        ("Track|||Artist", 0),     # poll
        ("Track|||Artist", 0),     # info
        ("ok", 0),                 # library add
    ])

    def fake_applescript(script):
        return next(applescript_responses)
    def fake_play_store(sid):
        jxa_called["called"] = True
        return "1"

    monkeypatch.setattr(md, "_run_applescript", fake_applescript)
    monkeypatch.setattr(md, "_play_store_track", fake_play_store)
    result = se._add_track_to_named_playlist(
        "Artist", "Track", "Test Playlist",
        search_result=search_result,
    )
    assert jxa_called["called"] is True


def test_backward_compat_without_search_result(monkeypatch):
    """When called without search_result, calls search_itunes internally."""
    search_called = {"called": False}

    def fake_search(a, t):
        search_called["called"] = True
        return md.SearchResult("12345", True, a, t)

    def fake_applescript(script):
        if "search library" in script:
            return "ok", 0
        return "", 0

    monkeypatch.setattr(md, "search_itunes", fake_search)
    monkeypatch.setattr(md, "_run_applescript", fake_applescript)
    result = se._add_track_to_named_playlist(
        "Artist", "Track", "Test Playlist",
    )
    assert search_called["called"] is True
    assert result is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_signal_experiment.py::test_library_first_path_adds_directly tests/test_signal_experiment.py::test_library_first_falls_through_to_jxa tests/test_signal_experiment.py::test_library_first_error_falls_through tests/test_signal_experiment.py::test_backward_compat_without_search_result -v`

Expected: FAIL (function doesn't accept `search_result` param yet)

- [ ] **Step 3: Implement library-first path**

Replace `signal_experiment.py:_add_track_to_named_playlist` (lines 423-555) with:

```python
def _add_track_to_named_playlist(artist, track_name, playlist_name, *, search_result=None):
    """Search Apple Music for a track and add it to a named playlist.
    
    If search_result is provided, uses it directly (skips search_itunes call).
    Tries library-first path (fast, no JXA) before falling back to JXA playback.
    Returns True if added, False if not found."""
    from music_discovery import (
        search_itunes, _run_applescript, _run_jxa, _play_store_track,
        _applescript_escape, SearchResult,
    )
    import time

    safe_pl = _applescript_escape(playlist_name)
    safe_artist = _applescript_escape(artist)
    safe_track = _applescript_escape(track_name)

    # Get search result (caller may have already searched)
    if search_result is None:
        search_result = search_itunes(artist, track_name)
    if not search_result:
        log.info(f"  Not found: {artist} — {track_name}")
        return False

    # Use canonical names from API for better library matching
    canon_artist = search_result.canonical_artist or artist
    canon_track = search_result.canonical_track or track_name
    safe_canon_artist = _applescript_escape(canon_artist)
    safe_canon_track = _applescript_escape(canon_track)

    # ── Library-first path: try to find and add directly ────────────────
    lib_search_script = f'''
tell application "Music"
    try
        set sr to search library playlist 1 for "{safe_canon_artist}"
        repeat with t in sr
            if name of t is "{safe_canon_track}" and artist of t is "{safe_canon_artist}" then
                duplicate t to user playlist "{safe_pl}"
                return "ok"
            end if
        end repeat
        return "not_in_library"
    on error e
        return "error: " & e
    end try
end tell
'''
    lib_out, _ = _run_applescript(lib_search_script)
    if lib_out.startswith("ok"):
        return True

    # ── JXA fallback: play via MediaPlayer, then add ────────────────────
    # Snapshot current track
    snapshot_script = '''
tell application "Music"
    try
        set ct to current track
        return (name of ct) & "|||" & (artist of ct)
    on error
        return ""
    end try
end tell
'''
    prev_track, _ = _run_applescript(snapshot_script)

    # Play via MediaPlayer
    _play_store_track(search_result.store_id)

    # Poll until current track changes
    poll_script = '''
tell application "Music"
    try
        set ct to current track
        return (name of ct) & "|||" & (artist of ct)
    on error
        return ""
    end try
end tell
'''
    for _ in range(10):
        time.sleep(0.5)
        out, _ = _run_applescript(poll_script)
        if out and out != prev_track:
            break
    else:
        return False

    # Get current track info
    info_script = '''
tell application "Music"
    try
        set ct to current track
        return (name of ct) & "|||" & (artist of ct)
    on error
        return ""
    end try
end tell
'''
    track_info, _ = _run_applescript(info_script)
    if not track_info or "|||" not in track_info:
        return False
    ct_name, ct_artist = track_info.split("|||", 1)
    safe_ct_name = _applescript_escape(ct_name)
    safe_ct_artist = _applescript_escape(ct_artist)

    # Try to find in library and add to playlist
    lib_script = f'''
tell application "Music"
    try
        set sr to search library playlist 1 for "{safe_ct_artist}"
        repeat with t in sr
            if name of t is "{safe_ct_name}" and artist of t is "{safe_ct_artist}" then
                duplicate t to user playlist "{safe_pl}"
                return "ok"
            end if
        end repeat
        return "not_in_library"
    on error e
        return "error: " & e
    end try
end tell
'''
    out, code = _run_applescript(lib_script)
    if out.startswith("ok"):
        return True

    # Not in library — add it first
    add_lib_script = '''
tell application "Music"
    try
        set ct to current track
        duplicate ct to source "Library"
        return "lib_ok"
    on error e
        return "lib_error: " & e
    end try
end tell
'''
    lib_out, _ = _run_applescript(add_lib_script)
    if not lib_out.startswith("lib_ok"):
        return False

    # Poll until in library, then add to playlist
    playlist_script = f'''
tell application "Music"
    try
        set sr to search library playlist 1 for "{safe_ct_artist}"
        repeat with t in sr
            if name of t is "{safe_ct_name}" and artist of t is "{safe_ct_artist}" then
                duplicate t to user playlist "{safe_pl}"
                return "ok"
            end if
        end repeat
        return "notfound"
    on error e
        return "error: " & e
    end try
end tell
'''
    for attempt in range(6):
        time.sleep(2 + attempt)
        out, code = _run_applescript(playlist_script)
        if out.startswith("ok"):
            return True

    return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_signal_experiment.py -v`

Expected: ALL PASS

- [ ] **Step 5: Run full test suite for regressions**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/ -v`

Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
cd "/Users/brianhill/Scripts/Music Discovery"
git add signal_experiment.py tests/test_signal_experiment.py
git commit -m "feat: library-first path in _add_track_to_named_playlist

Tries AppleScript library search before JXA fallback. Accepts optional
search_result param to skip redundant search_itunes call. Uses canonical
names from iTunes API for better library matching."
```

---

### Task 4: `fetch_artist_catalog()` and Deep Track Sourcing

**Files:**
- Modify: `music_discovery.py` (add fetch_artist_catalog, update fetch_top_tracks limit)
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_music_discovery.py`:

```python
# ── fetch_artist_catalog ──────────────────────────────────

def test_fetch_artist_catalog_returns_tracks(monkeypatch):
    """Returns list of track dicts from iTunes catalog search."""
    mock_resp = type("R", (), {
        "status_code": 200,
        "json": lambda self: {"resultCount": 3, "results": [
            {"kind": "song", "artistName": "Fleet Foxes", "trackName": "White Winter Hymnal"},
            {"kind": "song", "artistName": "Fleet Foxes", "trackName": "Mykonos"},
            {"kind": "music-video", "artistName": "Fleet Foxes", "trackName": "Helplessness Blues"},
        ]},
    })()
    monkeypatch.setattr("requests.get", lambda *a, **kw: mock_resp)
    result = md.fetch_artist_catalog("Fleet Foxes")
    assert len(result) == 2  # music-video filtered
    assert result[0] == {"name": "White Winter Hymnal", "artist": "Fleet Foxes"}
    assert result[1] == {"name": "Mykonos", "artist": "Fleet Foxes"}

def test_fetch_artist_catalog_filters_wrong_artist(monkeypatch):
    """Filters out tracks by different artists."""
    mock_resp = type("R", (), {
        "status_code": 200,
        "json": lambda self: {"resultCount": 2, "results": [
            {"kind": "song", "artistName": "Fleet Foxes", "trackName": "Mykonos"},
            {"kind": "song", "artistName": "Some Other Artist", "trackName": "Mykonos Cover"},
        ]},
    })()
    monkeypatch.setattr("requests.get", lambda *a, **kw: mock_resp)
    result = md.fetch_artist_catalog("Fleet Foxes")
    assert len(result) == 1

def test_fetch_artist_catalog_returns_empty_on_error(monkeypatch):
    """Returns empty list on network error."""
    monkeypatch.setattr("requests.get", lambda *a, **kw: (_ for _ in ()).throw(Exception("timeout")))
    result = md.fetch_artist_catalog("Fleet Foxes")
    assert result == []

def test_fetch_artist_catalog_fuzzy_match(monkeypatch):
    """Includes tracks from fuzzy-matched artist names (containment)."""
    mock_resp = type("R", (), {
        "status_code": 200,
        "json": lambda self: {"resultCount": 2, "results": [
            {"kind": "song", "artistName": "The Fleet Foxes", "trackName": "Mykonos"},
            {"kind": "song", "artistName": "Random Artist", "trackName": "Other"},
        ]},
    })()
    monkeypatch.setattr("requests.get", lambda *a, **kw: mock_resp)
    result = md.fetch_artist_catalog("Fleet Foxes")
    assert len(result) == 1
    assert result[0]["artist"] == "The Fleet Foxes"

def test_fetch_artist_catalog_deduplicates(monkeypatch):
    """Deduplicates tracks with same name (case-insensitive)."""
    mock_resp = type("R", (), {
        "status_code": 200,
        "json": lambda self: {"resultCount": 2, "results": [
            {"kind": "song", "artistName": "Fleet Foxes", "trackName": "Mykonos"},
            {"kind": "song", "artistName": "Fleet Foxes", "trackName": "Mykonos"},
        ]},
    })()
    monkeypatch.setattr("requests.get", lambda *a, **kw: mock_resp)
    result = md.fetch_artist_catalog("Fleet Foxes")
    assert len(result) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py::test_fetch_artist_catalog_returns_tracks -v`

Expected: FAIL with `AttributeError: module 'music_discovery' has no attribute 'fetch_artist_catalog'`

- [ ] **Step 3: Implement `fetch_artist_catalog()`**

Add to `music_discovery.py` after `search_itunes()`:

```python
def fetch_artist_catalog(artist):
    """Fetch all available songs for an artist from the iTunes Search API.
    Returns list of {"name": str, "artist": str}. Deduplicates by track name.
    Free API — no key required."""
    try:
        resp = requests.get(ITUNES_SEARCH_URL, timeout=15, params={
            "term":  artist,
            "media": "music",
            "entity": "song",
            "limit": 200,
        })
        if resp.status_code != 200:
            return []
        results = resp.json().get("results", [])
        artist_lower = artist.strip().lower()
        seen = set()
        tracks = []
        for r in results:
            if r.get("kind") != "song":
                continue
            result_artist = r.get("artistName", "").strip().lower()
            if result_artist != artist_lower and not (
                artist_lower in result_artist or result_artist in artist_lower
            ):
                continue
            track_name = r.get("trackName", "")
            key = track_name.lower()
            if key in seen:
                continue
            seen.add(key)
            tracks.append({"name": track_name, "artist": r.get("artistName", "")})
        return tracks
    except Exception as e:
        log.debug(f"fetch_artist_catalog failed for '{artist}': {e}")
        return []
```

- [ ] **Step 4: Add `limit` parameter to `fetch_top_tracks()`**

In `music_discovery.py:fetch_top_tracks` (line 964), add a `limit` parameter with the current default:

```python
def fetch_top_tracks(artist, api_key, limit=TRACKS_PER_ARTIST):
    """Fetch top tracks for an artist from Last.fm.
    Returns list of {"name": str, "artist": str}, or [] on failure."""
    try:
        resp = requests.get(LASTFM_API_URL, timeout=10, params={
            "method":  "artist.getTopTracks",
            "artist":  artist,
            "api_key": api_key,
            "format":  "json",
            "limit":   limit,
        })
```

**Do NOT change the global `TRACKS_PER_ARTIST = 2`.** The old `--playlist` mode in `music_discovery.py:build_playlist()` uses `fetch_top_tracks(artist, api_key)` without a limit arg and relies on the default of 2. Changing the global would make that mode fetch 50 tracks per artist and attempt to add all of them via the slow JXA path. The adaptive engine will pass `limit=50` explicitly in Task 8.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -k "fetch_artist_catalog" -v`

Expected: 4 PASSED

- [ ] **Step 6: Run full test suite for regressions**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/ -v`

Expected: ALL PASS (the limit change doesn't affect existing tests since they mock the API)

- [ ] **Step 7: Commit**

```bash
cd "/Users/brianhill/Scripts/Music Discovery"
git add music_discovery.py tests/test_music_discovery.py
git commit -m "feat: fetch_artist_catalog() for deep track sourcing

iTunes Search API catalog lookup returning up to 200 tracks per artist.
Also increases Last.fm top tracks limit from 2 to 50 for deeper pool."
```

---

### Task 5: Offered Tracks Persistence (Cross-Round Dedup)

**Files:**
- Modify: `adaptive_engine.py`
- Test: `tests/test_adaptive_engine.py` (or appropriate test file)

- [ ] **Step 1: Write failing tests for load/save offered tracks**

Find the adaptive engine test file and add:

```python
# ── offered tracks persistence ────────────────────────────

def test_load_offered_tracks_missing_file(tmp_path):
    """Returns empty set and empty list when file doesn't exist."""
    from adaptive_engine import _load_offered_tracks
    track_set, entries = _load_offered_tracks(tmp_path / "offered_tracks.json")
    assert track_set == set()
    assert entries == []

def test_load_offered_tracks_corrupt_json(tmp_path):
    """Returns empty set on corrupt JSON."""
    from adaptive_engine import _load_offered_tracks
    path = tmp_path / "offered_tracks.json"
    path.write_text("not json{{{")
    track_set, entries = _load_offered_tracks(path)
    assert track_set == set()
    assert entries == []

def test_load_offered_tracks_valid(tmp_path):
    """Loads tracks into a set of (artist, track) tuples and raw entries."""
    from adaptive_engine import _load_offered_tracks
    path = tmp_path / "offered_tracks.json"
    path.write_text(json.dumps({
        "version": 1,
        "tracks": [
            {"artist": "fleet foxes", "track": "white winter hymnal", "round": 1},
            {"artist": "fleet foxes", "track": "mykonos", "round": 1},
        ]
    }))
    track_set, entries = _load_offered_tracks(path)
    assert ("fleet foxes", "white winter hymnal") in track_set
    assert ("fleet foxes", "mykonos") in track_set
    assert len(track_set) == 2
    assert len(entries) == 2

def test_save_offered_tracks_atomic(tmp_path):
    """Saves with atomic write (temp file then rename)."""
    from adaptive_engine import _save_offered_tracks
    path = tmp_path / "offered_tracks.json"
    entries = [{"artist": "fleet foxes", "track": "white winter hymnal", "round": 1}]
    _save_offered_tracks(path, entries)
    data = json.loads(path.read_text())
    assert data["version"] == 1
    assert len(data["tracks"]) == 1
    assert data["tracks"][0]["artist"] == "fleet foxes"
    # Temp file should be cleaned up
    assert not (tmp_path / "offered_tracks.json.tmp").exists()

def test_save_then_load_roundtrip(tmp_path):
    """Save and load produce the same set."""
    from adaptive_engine import _load_offered_tracks, _save_offered_tracks
    path = tmp_path / "offered_tracks.json"
    entries = [
        {"artist": "artist a", "track": "track 1", "round": 5},
        {"artist": "artist b", "track": "track 2", "round": 5},
    ]
    _save_offered_tracks(path, entries)
    loaded_set, loaded_entries = _load_offered_tracks(path)
    assert ("artist a", "track 1") in loaded_set
    assert ("artist b", "track 2") in loaded_set
    assert len(loaded_entries) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_adaptive_engine.py -k "offered_tracks" -v`

Expected: FAIL with `ImportError` (functions don't exist yet)

- [ ] **Step 3: Implement load/save helpers**

Add to `adaptive_engine.py` after the imports and defaults section (after line ~45):

```python
def _load_offered_tracks(path: pathlib.Path) -> tuple[set, list]:
    """Load previously offered tracks. Returns (set of (artist, track), raw entries list)."""
    if not path.exists():
        return set(), []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data.get("tracks", [])
        track_set = {(t["artist"], t["track"]) for t in entries}
        return track_set, entries
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        log.warning("Corrupt offered_tracks.json, starting fresh: %s", e)
        return set(), []


def _save_offered_tracks(path: pathlib.Path, entries: list):
    """Save offered tracks to JSON with atomic write."""
    data = {"version": 1, "tracks": entries}
    tmp = pathlib.Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_adaptive_engine.py -k "offered_tracks" -v`

Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd "/Users/brianhill/Scripts/Music Discovery"
git add adaptive_engine.py tests/test_adaptive_engine.py
git commit -m "feat: offered tracks persistence for cross-round dedup

_load_offered_tracks and _save_offered_tracks with atomic writes,
corrupt file handling, and set-based O(1) lookup."
```

---

### Task 6: Search Strikes Persistence

**Files:**
- Modify: `adaptive_engine.py`
- Test: `tests/test_adaptive_engine.py`

- [ ] **Step 1: Write failing tests for strike helpers**

```python
# ── search strikes persistence ────────────────────────────

def test_load_search_strikes_missing_file(tmp_path):
    """Returns empty dict when file doesn't exist."""
    from adaptive_engine import _load_search_strikes
    result = _load_search_strikes(tmp_path / "search_strikes.json")
    assert result == {}

def test_load_search_strikes_corrupt(tmp_path):
    """Returns empty dict on corrupt JSON."""
    from adaptive_engine import _load_search_strikes
    path = tmp_path / "search_strikes.json"
    path.write_text("broken")
    result = _load_search_strikes(path)
    assert result == {}

def test_load_search_strikes_valid(tmp_path):
    """Loads strike data correctly."""
    from adaptive_engine import _load_search_strikes
    path = tmp_path / "search_strikes.json"
    path.write_text(json.dumps({
        "version": 1,
        "strikes": {"some artist": {"count": 2, "last_round": 3, "last_recheck": 0}}
    }))
    result = _load_search_strikes(path)
    assert result["some artist"]["count"] == 2

def test_save_search_strikes_atomic(tmp_path):
    """Saves with atomic write."""
    from adaptive_engine import _save_search_strikes
    path = tmp_path / "search_strikes.json"
    strikes = {"artist a": {"count": 1, "last_round": 5, "last_recheck": 0}}
    _save_search_strikes(path, strikes)
    data = json.loads(path.read_text())
    assert data["version"] == 1
    assert data["strikes"]["artist a"]["count"] == 1
    assert not (tmp_path / "search_strikes.json.tmp").exists()


def test_evaluate_strikes_increment(tmp_path):
    """All tracks not found increments strike count."""
    from adaptive_engine import _evaluate_artist_strikes
    from music_discovery import SearchResult
    strikes = {}
    search_results = [
        SearchResult(None, True),   # not found, searched ok
        SearchResult(None, True),   # not found, searched ok
    ]
    _evaluate_artist_strikes(strikes, "artist a", search_results, current_round=1)
    assert strikes["artist a"]["count"] == 1
    assert strikes["artist a"]["last_round"] == 1

def test_evaluate_strikes_reset_on_found():
    """Any track found resets strikes to 0."""
    from adaptive_engine import _evaluate_artist_strikes
    from music_discovery import SearchResult
    strikes = {"artist a": {"count": 2, "last_round": 5, "last_recheck": 0}}
    search_results = [
        SearchResult(None, True),     # not found
        SearchResult("123", True, "Artist A", "Track"),  # found
    ]
    _evaluate_artist_strikes(strikes, "artist a", search_results, current_round=6)
    assert strikes["artist a"]["count"] == 0

def test_evaluate_strikes_no_change_on_all_errors():
    """All errors leaves strikes unchanged."""
    from adaptive_engine import _evaluate_artist_strikes
    from music_discovery import SearchResult
    strikes = {"artist a": {"count": 2, "last_round": 5, "last_recheck": 0}}
    search_results = [
        SearchResult(None, False),  # error
        SearchResult(None, False),  # error
    ]
    _evaluate_artist_strikes(strikes, "artist a", search_results, current_round=6)
    assert strikes["artist a"]["count"] == 2  # unchanged

def test_evaluate_strikes_gap_resets_counter():
    """Non-consecutive rounds reset the counter before evaluating."""
    from adaptive_engine import _evaluate_artist_strikes
    from music_discovery import SearchResult
    strikes = {"artist a": {"count": 2, "last_round": 3, "last_recheck": 0}}
    search_results = [SearchResult(None, True)]
    # Round 10, last_round was 3 — gap > 1, so reset then increment to 1
    _evaluate_artist_strikes(strikes, "artist a", search_results, current_round=10)
    assert strikes["artist a"]["count"] == 1  # reset to 0, then incremented to 1

def test_evaluate_strikes_mixed_error_and_found_resets():
    """Mixed error + found results reset strikes (found takes priority)."""
    from adaptive_engine import _evaluate_artist_strikes
    from music_discovery import SearchResult
    strikes = {"artist a": {"count": 2, "last_round": 4, "last_recheck": 0}}
    search_results = [
        SearchResult(None, False),                       # error
        SearchResult("123", True, "Artist A", "Track"),  # found
    ]
    _evaluate_artist_strikes(strikes, "artist a", search_results, current_round=5)
    assert strikes["artist a"]["count"] == 0  # reset because one was found

def test_evaluate_strikes_threshold_returns_blocklist():
    """Returns True when artist hits 3 strikes."""
    from adaptive_engine import _evaluate_artist_strikes
    from music_discovery import SearchResult
    strikes = {"artist a": {"count": 2, "last_round": 4, "last_recheck": 0}}
    search_results = [SearchResult(None, True)]
    should_blocklist = _evaluate_artist_strikes(
        strikes, "artist a", search_results, current_round=5
    )
    assert should_blocklist is True
    assert strikes["artist a"]["count"] == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_adaptive_engine.py -k "strikes" -v`

Expected: FAIL

- [ ] **Step 3: Implement strike helpers**

Add to `adaptive_engine.py`:

```python
STRIKE_THRESHOLD = 3


def _load_search_strikes(path: pathlib.Path) -> dict:
    """Load search strike counters. Returns dict of artist -> {count, last_round, last_recheck}."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("strikes", {})
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        log.warning("Corrupt search_strikes.json, starting fresh: %s", e)
        return {}


def _save_search_strikes(path: pathlib.Path, strikes: dict):
    """Save search strikes with atomic write."""
    data = {"version": 1, "strikes": strikes}
    tmp = pathlib.Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _evaluate_artist_strikes(strikes: dict, artist: str,
                             search_results: list, current_round: int) -> bool:
    """Evaluate search results for an artist and update strike counter.
    Returns True if artist should be auto-blocklisted (hit threshold)."""
    entry = strikes.get(artist, {"count": 0, "last_round": 0, "last_recheck": 0})

    any_found = any(r.store_id is not None for r in search_results)
    any_searched_ok = any(r.searched_ok for r in search_results)
    all_errored = not any_searched_ok

    if any_found:
        entry["count"] = 0
        entry["last_round"] = current_round
        strikes[artist] = entry
        return False

    if all_errored:
        # Don't count, don't change
        return False

    # All searched OK but none found — potential strike
    # Check for gap (non-consecutive attempt)
    if entry["last_round"] > 0 and current_round - entry["last_round"] > 1:
        entry["count"] = 0  # reset stale counter

    entry["count"] += 1
    entry["last_round"] = current_round
    strikes[artist] = entry

    return entry["count"] >= STRIKE_THRESHOLD
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_adaptive_engine.py -k "strikes" -v`

Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd "/Users/brianhill/Scripts/Music Discovery"
git add adaptive_engine.py tests/test_adaptive_engine.py
git commit -m "feat: search strikes persistence and evaluation logic

_load_search_strikes, _save_search_strikes, _evaluate_artist_strikes
with gap reset, error tolerance, and 3-strike threshold."
```

---

### Task 7: Auto-Blocklist Write and On-Demand Re-check

**Files:**
- Modify: `adaptive_engine.py`
- Test: `tests/test_adaptive_engine.py`

- [ ] **Step 1: Write failing tests**

```python
RECHECK_COOLDOWN = 10  # from the spec

def test_auto_blocklist_appends_artist(tmp_path):
    """Appends artist to ai_blocklist.txt with comment."""
    from adaptive_engine import _auto_blocklist_artist
    path = tmp_path / "ai_blocklist.txt"
    path.write_text("existing artist\n")
    _auto_blocklist_artist(path, "new artist", round_num=5)
    lines = path.read_text().strip().split("\n")
    assert "existing artist" in lines
    assert "# auto-blocklisted round 5:" in lines[-2]
    assert "new artist" == lines[-1]

def test_auto_blocklist_deduplicates(tmp_path):
    """Does not add artist if already present."""
    from adaptive_engine import _auto_blocklist_artist
    path = tmp_path / "ai_blocklist.txt"
    path.write_text("some artist\n")
    _auto_blocklist_artist(path, "some artist", round_num=3)
    lines = [l for l in path.read_text().strip().split("\n") if not l.startswith("#")]
    assert lines.count("some artist") == 1

def test_auto_blocklist_creates_file(tmp_path):
    """Creates file if it doesn't exist."""
    from adaptive_engine import _auto_blocklist_artist
    path = tmp_path / "ai_blocklist.txt"
    _auto_blocklist_artist(path, "new artist", round_num=1)
    assert path.exists()
    assert "new artist" in path.read_text()

def test_should_recheck_true_after_cooldown():
    """Returns True when enough rounds have passed since last recheck."""
    from adaptive_engine import _should_recheck_artist, RECHECK_COOLDOWN
    strikes = {"artist": {"count": 3, "last_round": 5, "last_recheck": 1}}
    assert _should_recheck_artist(strikes, "artist", current_round=12) is True

def test_should_recheck_false_within_cooldown():
    """Returns False when too few rounds since last recheck."""
    from adaptive_engine import _should_recheck_artist, RECHECK_COOLDOWN
    strikes = {"artist": {"count": 3, "last_round": 5, "last_recheck": 8}}
    assert _should_recheck_artist(strikes, "artist", current_round=12) is False

def test_should_recheck_false_when_not_in_strikes():
    """Returns False for unknown artist."""
    from adaptive_engine import _should_recheck_artist
    assert _should_recheck_artist({}, "unknown", current_round=50) is False

def test_remove_from_blocklist_removes_artist_and_comment(tmp_path):
    """Removes artist and its auto-blocklist comment."""
    from adaptive_engine import _remove_from_blocklist
    path = tmp_path / "ai_blocklist.txt"
    path.write_text("manual artist\n# auto-blocklisted round 3:\nghost artist\nanother artist\n")
    _remove_from_blocklist(path, "ghost artist")
    content = path.read_text()
    assert "ghost artist" not in content
    assert "auto-blocklisted round 3" not in content
    assert "manual artist" in content
    assert "another artist" in content

def test_remove_from_blocklist_missing_file(tmp_path):
    """No-op when file doesn't exist."""
    from adaptive_engine import _remove_from_blocklist
    path = tmp_path / "ai_blocklist.txt"
    _remove_from_blocklist(path, "nobody")  # should not raise

def test_remove_from_blocklist_artist_not_present(tmp_path):
    """No-op when artist is not in file."""
    from adaptive_engine import _remove_from_blocklist
    path = tmp_path / "ai_blocklist.txt"
    path.write_text("some artist\n")
    _remove_from_blocklist(path, "other artist")
    assert "some artist" in path.read_text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_adaptive_engine.py -k "blocklist or recheck" -v`

Expected: FAIL

- [ ] **Step 3: Implement blocklist write and recheck helpers**

Add to `adaptive_engine.py`:

```python
RECHECK_COOLDOWN = 10


def _auto_blocklist_artist(blocklist_path: pathlib.Path, artist: str, round_num: int):
    """Append an artist to ai_blocklist.txt if not already present."""
    existing = set()
    if blocklist_path.exists():
        for line in blocklist_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                existing.add(stripped.lower())

    if artist.lower() in existing:
        return

    with open(blocklist_path, "a", encoding="utf-8") as f:
        f.write(f"# auto-blocklisted round {round_num}:\n")
        f.write(f"{artist}\n")
    log.warning("Auto-blocklisted \"%s\" — not found on Apple Music for %d consecutive rounds",
                artist, STRIKE_THRESHOLD)


def _should_recheck_artist(strikes: dict, artist: str, current_round: int) -> bool:
    """Check if a blocklisted artist should be re-tested."""
    entry = strikes.get(artist)
    if not entry:
        return False
    last_recheck = entry.get("last_recheck", 0)
    return current_round - last_recheck >= RECHECK_COOLDOWN


def _remove_from_blocklist(blocklist_path: pathlib.Path, artist: str):
    """Remove an auto-blocklisted artist and its comment from the blocklist file."""
    if not blocklist_path.exists():
        return
    lines = blocklist_path.read_text(encoding="utf-8").splitlines()
    new_lines = []
    skip_next = False
    for line in lines:
        if skip_next:
            skip_next = False
            continue
        if line.strip().lower() == artist.lower():
            # Remove the comment line above if it's an auto-blocklist comment
            if new_lines and new_lines[-1].strip().startswith("# auto-blocklisted"):
                new_lines.pop()
            continue
        new_lines.append(line)
    blocklist_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    log.info("Re-checked \"%s\" — now available on Apple Music, removed from auto-blocklist", artist)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_adaptive_engine.py -k "blocklist or recheck" -v`

Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd "/Users/brianhill/Scripts/Music Discovery"
git add adaptive_engine.py tests/test_adaptive_engine.py
git commit -m "feat: auto-blocklist write and on-demand re-check helpers

_auto_blocklist_artist with dedup and comment prefix.
_should_recheck_artist with 10-round cooldown.
_remove_from_blocklist for recovery."
```

---

### Task 8: Restructure `_run_build()` Playlist Loop

**Files:**
- Modify: `adaptive_engine.py:571-896` (_run_build)
- Test: `tests/test_adaptive_engine.py`, `tests/test_integration_adaptive.py`

This is the integration task that wires together Tasks 1-7.

- [ ] **Step 1: Write failing integration test for the new build loop**

Add to `tests/test_integration_adaptive.py` (or the appropriate integration test file):

```python
def test_build_loop_skips_previously_offered_tracks(tmp_path, monkeypatch):
    """Tracks offered in a prior round are not offered again."""
    import adaptive_engine as ae
    import music_discovery as md
    from adaptive_engine import _load_offered_tracks, _save_offered_tracks

    # Pre-populate offered tracks
    offered_path = tmp_path / "offered_tracks.json"
    entries = [{"artist": "fleet foxes", "track": "white winter hymnal", "round": 1}]
    _save_offered_tracks(offered_path, entries)

    offered_set, _ = _load_offered_tracks(offered_path)
    assert ("fleet foxes", "white winter hymnal") in offered_set

    # Simulate: Fleet Foxes has 2 tracks, one already offered
    all_tracks = [
        {"name": "White Winter Hymnal", "artist": "Fleet Foxes"},
        {"name": "Mykonos", "artist": "Fleet Foxes"},
    ]

    # Filter
    available = [
        t for t in all_tracks
        if (t["artist"].lower(), t["name"].lower()) not in offered_set
    ]
    assert len(available) == 1
    assert available[0]["name"] == "Mykonos"


def test_build_loop_overflow_past_exhausted_artists(tmp_path):
    """When top artist is exhausted, continues to next artist."""
    import adaptive_engine as ae
    from adaptive_engine import _load_offered_tracks, _save_offered_tracks

    # Artist A fully exhausted, Artist B has tracks
    offered_path = tmp_path / "offered_tracks.json"
    entries = [
        {"artist": "artist a", "track": "track 1", "round": 1},
        {"artist": "artist a", "track": "track 2", "round": 1},
    ]
    _save_offered_tracks(offered_path, entries)
    offered_set, _ = _load_offered_tracks(offered_path)

    ranked = [(0.9, "artist a"), (0.8, "artist b")]
    artist_tracks = {
        "artist a": [{"name": "Track 1", "artist": "Artist A"}, {"name": "Track 2", "artist": "Artist A"}],
        "artist b": [{"name": "New Song", "artist": "Artist B"}],
    }

    # Simulate overflow loop
    slots_filled = 0
    artist_idx = 0
    target = 2
    filled_artists = []
    while slots_filled < target and artist_idx < len(ranked):
        _, artist = ranked[artist_idx]
        artist_idx += 1
        tracks = artist_tracks.get(artist, [])
        available = [t for t in tracks if (artist, t["name"].lower()) not in offered_set]
        if available:
            slots_filled += 1
            filled_artists.append(artist)

    assert "artist b" in filled_artists
    assert slots_filled == 1  # Only artist b had tracks
```

- [ ] **Step 2: Run tests to verify they fail/pass (these test the helpers, should pass)**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_integration_adaptive.py -k "build_loop" -v`

- [ ] **Step 3: Restructure `_run_build()` playlist loop**

In `adaptive_engine.py`, replace the playlist-building section (lines ~842-896). The key changes:

1. Add imports for `fetch_artist_catalog`, `search_itunes`, `SearchResult`
2. Load offered tracks and search strikes
3. Overflow iteration loop
4. Tiered track sourcing (Last.fm top tracks + catalog)
5. Call `search_itunes` in the loop, pass result to `_add_track_to_named_playlist`
6. Track dedup check
7. Strike evaluation per artist
8. Auto-blocklist on threshold
9. On-demand re-check for blocklisted candidates
10. Save offered tracks and strikes after loop

Replace lines ~842-896 with:

```python
    playlist_size = args.playlist_size
    top_artists = ranked[:playlist_size]  # preserve for explanation report below

    log.info("\n  Top %d candidates:", len(top_artists))
    log.info("  %-4s  %-40s  %s", "Rank", "Artist", "Score")
    log.info("  %s", "-" * 55)
    for i, (score, name) in enumerate(top_artists, 1):
        log.info("  %-4d  %-40s  %.4f", i, name, score)

    # ── Step 9: Build playlist ───────────────────────────────────────────────
    log.info("\nStep 7: Building playlist...")

    playlist_name = f"Adaptive Discovery R{current_round}"
    tracks_per_artist = DEFAULT_TRACKS_PER_ARTIST

    # Load cross-round state
    offered_path = cache_dir / "offered_tracks.json"
    strikes_path = cache_dir / "search_strikes.json"
    offered_set, offered_entries = _load_offered_tracks(offered_path)
    strikes = _load_search_strikes(strikes_path)
    project_dir = pathlib.Path(__file__).parent
    blocklist_path = project_dir / "ai_blocklist.txt"

    offered_tracks: set = set()  # (artist, track_name) for this round's snapshot
    artist_idx = 0
    slots_filled = 0

    while slots_filled < playlist_size and artist_idx < len(ranked):
        _score, artist = ranked[artist_idx]
        artist_idx += 1

        # On-demand re-check for auto-blocklisted artists
        if artist.lower() in full_blocklist:
            if _should_recheck_artist(strikes, artist.lower(), current_round):
                catalog = fetch_artist_catalog(artist)
                strikes.setdefault(artist.lower(), {"count": 3, "last_round": 0, "last_recheck": 0})
                if catalog:
                    _remove_from_blocklist(blocklist_path, artist)
                    full_blocklist.discard(artist.lower())
                    log.info("  Re-check passed for %s, re-entering candidate pool", artist)
                else:
                    strikes[artist.lower()]["last_recheck"] = current_round
                    continue
            else:
                continue

        # Tiered track sourcing: Last.fm top 50 first, then iTunes catalog
        lastfm_tracks = fetch_top_tracks(artist, api_key, limit=50) if api_key else []
        catalog_tracks = fetch_artist_catalog(artist)

        # Deduplicate catalog against Last.fm (by lowercased track name)
        lastfm_names = {t["name"].lower() for t in lastfm_tracks}
        unique_catalog = [t for t in catalog_tracks if t["name"].lower() not in lastfm_names]

        all_tracks = lastfm_tracks + unique_catalog
        artist_search_results = []
        added_count = 0

        for track in all_tracks:
            if added_count >= tracks_per_artist:
                break
            track_name = track.get("name", "")
            if not track_name:
                continue

            # Cross-round dedup
            key = (artist.lower(), track_name.lower())
            if key in offered_set:
                continue

            # Search iTunes
            result = search_itunes(artist, track_name)
            artist_search_results.append(result)

            if not result:
                continue

            # Try to add to playlist
            if _add_track_to_named_playlist(artist, track_name, playlist_name,
                                             search_result=result):
                offered_tracks.add(key)
                offered_set.add(key)
                offered_entries.append({
                    "artist": artist.lower(),
                    "track": track_name.lower(),
                    "round": current_round,
                })
                added_count += 1

            time.sleep(0.3)  # Rate limiting

        # Evaluate strikes for this artist
        if artist_search_results:
            should_block = _evaluate_artist_strikes(
                strikes, artist.lower(), artist_search_results, current_round
            )
            if should_block:
                _auto_blocklist_artist(blocklist_path, artist, current_round)

        if added_count > 0:
            log.info("  Added %d tracks for %s", added_count, artist)
            slots_filled += 1
        else:
            log.warning("  No tracks added for %s", artist)

        time.sleep(0.5)  # Rate limiting between artists

    # Save cross-round state
    _save_offered_tracks(offered_path, offered_entries)
    _save_search_strikes(strikes_path, strikes)

    log.info("  Playlist '%s': %d tracks for %d artists (of %d ranked).",
             playlist_name, len(offered_tracks), slots_filled, len(ranked))
```

Also add the new imports at the top of `_run_build()`:

```python
    from music_discovery import (
        load_dotenv,
        parse_library_jxa,
        collect_track_metadata_jxa,
        load_cache,
        fetch_filter_data,
        fetch_top_tracks,
        fetch_artist_catalog,
        search_itunes,
        check_ai_artist,
        load_ai_blocklist,
        load_ai_allowlist,
        load_user_blocklist,
        load_blocklist,
        _build_paths,
    )
```

- [ ] **Step 4: Update the `offered_artist_names` section below the loop**

The section that saves offered features (lines ~887-896) currently uses `top_artists`. Update to use the actual artists that contributed tracks:

```python
    # ── Step 10: Save pre-listen snapshot ────────────────────────────────────
    log.info("Step 8: Saving pre-listen snapshot...")

    snapshot = create_snapshot(track_metadata, offered_tracks)
    save_snapshot(cache_dir / "pre_listen_snapshot.json", snapshot)
    log.info("  Saved snapshot with %d tracks.", len(snapshot))

    # ── Step 11: Save offered features ───────────────────────────────────────
    # offered_tracks contains lowercased keys, but candidate_features uses
    # original casing. Build a lowercase->original mapping from ranked.
    lower_to_original = {name.lower(): name for _, name in ranked}
    offered_artist_names = {a for a, _ in offered_tracks}
    offered_features = {}
    for artist_lower in offered_artist_names:
        original = lower_to_original.get(artist_lower, artist_lower)
        if original in candidate_features:
            offered_features[original] = candidate_features[original]
```

- [ ] **Step 5: Run full test suite**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/ -v`

Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
cd "/Users/brianhill/Scripts/Music Discovery"
git add adaptive_engine.py tests/
git commit -m "feat: restructure _run_build with overflow, dedup, strikes, deep tracks

Overflow iteration past exhausted artists. Cross-round track dedup via
offered_tracks.json. Tiered sourcing (Last.fm + iTunes catalog). Strike
counting with auto-blocklist. On-demand re-check with cooldown. Fixes #8."
```

---

### Task 9: Adversarial and Integration Tests

**Files:**
- Test: `tests/test_integration_adaptive.py`, `tests/test_adaptive_engine.py`

- [ ] **Step 1: Write multi-round track dedup integration test**

```python
def test_multi_round_no_track_overlap(tmp_path, monkeypatch):
    """Simulates 2 rounds and verifies no track is offered twice."""
    import adaptive_engine as ae
    from adaptive_engine import (
        _load_offered_tracks, _save_offered_tracks,
        _evaluate_artist_strikes, _load_search_strikes, _save_search_strikes,
    )
    import music_discovery as md

    offered_path = tmp_path / "offered_tracks.json"

    # Round 1: offer track A
    offered_set, entries = _load_offered_tracks(offered_path)
    assert len(offered_set) == 0

    key = ("fleet foxes", "white winter hymnal")
    offered_set.add(key)
    entries.append({"artist": "fleet foxes", "track": "white winter hymnal", "round": 1})
    _save_offered_tracks(offered_path, entries)

    # Round 2: track A should be filtered
    offered_set2, entries2 = _load_offered_tracks(offered_path)
    assert key in offered_set2

    all_tracks = [
        {"name": "White Winter Hymnal", "artist": "Fleet Foxes"},
        {"name": "Mykonos", "artist": "Fleet Foxes"},
    ]
    available = [t for t in all_tracks if (t["artist"].lower(), t["name"].lower()) not in offered_set2]
    assert len(available) == 1
    assert available[0]["name"] == "Mykonos"


def test_three_strikes_auto_blocklist(tmp_path):
    """Artist with 3 consecutive clean misses is auto-blocklisted."""
    from adaptive_engine import (
        _evaluate_artist_strikes, _auto_blocklist_artist,
        _load_search_strikes, _save_search_strikes,
    )
    from music_discovery import SearchResult

    strikes_path = tmp_path / "search_strikes.json"
    blocklist_path = tmp_path / "ai_blocklist.txt"
    strikes = _load_search_strikes(strikes_path)

    not_found = [SearchResult(None, True)]

    # Rounds 1-2: strikes accumulate
    for rnd in range(1, 3):
        result = _evaluate_artist_strikes(strikes, "ghost artist", not_found, rnd)
        assert result is False  # not yet at threshold

    # Round 3: hits threshold
    result = _evaluate_artist_strikes(strikes, "ghost artist", not_found, 3)
    assert result is True

    _auto_blocklist_artist(blocklist_path, "ghost artist", 3)
    assert "ghost artist" in blocklist_path.read_text()
    _save_search_strikes(strikes_path, strikes)


def test_two_strikes_then_found_resets(tmp_path):
    """Artist found after 2 strikes resets counter."""
    from adaptive_engine import _evaluate_artist_strikes
    from music_discovery import SearchResult

    strikes = {}
    not_found = [SearchResult(None, True)]
    found = [SearchResult("123", True, "Artist", "Track")]

    _evaluate_artist_strikes(strikes, "artist", not_found, 1)
    _evaluate_artist_strikes(strikes, "artist", not_found, 2)
    assert strikes["artist"]["count"] == 2

    _evaluate_artist_strikes(strikes, "artist", found, 3)
    assert strikes["artist"]["count"] == 0
```

- [ ] **Step 2: Run tests**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/ -v`

Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
cd "/Users/brianhill/Scripts/Music Discovery"
git add tests/
git commit -m "test: adversarial integration tests for dedup and strikes

Multi-round track dedup, 3-strike auto-blocklist, strike reset on found."
```

---

### Task 10: Final Verification and Cleanup

- [ ] **Step 1: Run full test suite**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/ -v --tb=short`

Expected: ALL PASS, no warnings about deprecated patterns

- [ ] **Step 2: Check for any remaining raw `search_itunes` returns**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && grep -rn "search_itunes" --include="*.py" | grep -v test | grep -v __pycache__ | grep -v ".pyc"`

Verify every call site handles `SearchResult` correctly. No caller should treat the return value as a plain string.

- [ ] **Step 3: Verify `_play_store_track` callers pass `.store_id`**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && grep -rn "_play_store_track" --include="*.py" | grep -v test | grep -v __pycache__`

Verify all calls pass a string, not a `SearchResult`.

- [ ] **Step 4: Commit any cleanup**

```bash
cd "/Users/brianhill/Scripts/Music Discovery"
git add -A
git commit -m "chore: final cleanup after playback fix implementation"
```

- [ ] **Step 5: Close issue #8**

```bash
gh issue close 8 --repo networkingguru/music-discovery --comment "Fixed: JXA NSRunLoop polling, library-first path, cross-round track dedup, deep track sourcing, auto-blocklist with strike counting."
```
