# Test Fixes — Broken Mock Design

**Date:** 2026-03-14
**Approach:** Fix mocks to match current code behavior

---

## Overview

Four tests in `tests/test_music_discovery.py` have been failing since the playlist and API-key features were implemented. All four use blanket mocks that don't match the stateful call patterns of the functions they test. The fix is to replace each blanket mock with a stateful mock that returns the correct value for each call in sequence.

---

## Fix 1: `test_setup_playlist_returns_true_on_success` (line 684)

**Root cause:** Blanket `lambda script: ("", 0)` returns empty string for the count query. `setup_playlist()` calls `int(out)` at line 691, which raises `ValueError` on `""`. The function catches this and returns `False`.

**Fix:** Stateful mock returning two responses:
1. Count query → `("-1", 0)` — playlist doesn't exist
2. Create playlist → `("", 0)` — success

This exercises the "playlist doesn't exist" branch (line 697-704).

```python
def test_setup_playlist_returns_true_on_success(monkeypatch):
    """Returns True when osascript succeeds."""
    responses = iter([("-1", 0), ("", 0)])
    monkeypatch.setattr(md, "_run_applescript", lambda script: next(responses))
    assert md.setup_playlist() is True
```

---

## Fix 2: `test_add_track_to_playlist_returns_true_on_ok` (line 707)

**Root cause:** Blanket `lambda script: ("ok", 0)` returns `"ok"` for all calls. The snapshot (call 2) returns `"ok"`, then the poll loop (call 3+) also returns `"ok"`. Since `out == prev_track`, the loop never breaks — it exhausts all 10 iterations and the `for...else` returns `False`.

**Fix:** Stateful mock matching the 4-call sequence:
1. Dedup check → `("not_found", 0)` — track not in playlist
2. Snapshot → `("Old|||Track", 0)` — current track before play
3. Poll (first iteration) → `("Creep|||Radiohead", 0)` — different from snapshot, breaks loop
4. Add-to-playlist → `("ok", 0)` — success

```python
def test_add_track_to_playlist_returns_true_on_ok(monkeypatch):
    """Returns True when full flow succeeds."""
    monkeypatch.setattr(md, "search_itunes", lambda a, t: "12345")
    monkeypatch.setattr(md, "_play_store_track", lambda sid: True)
    responses = iter([("not_found", 0), ("Old|||Track", 0), ("Creep|||Radiohead", 0), ("ok", 0)])
    monkeypatch.setattr(md, "_run_applescript", lambda script: next(responses))
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert md.add_track_to_playlist("Radiohead", "Creep") is True
```

---

## Fix 3: `test_add_track_to_playlist_raises_on_osascript_failure` (line 720)

**Root cause:** Blanket `lambda script: ("", 1)` returns failure code for every call. The dedup check gets `out=""` (not `"already_exists"`), continues. Snapshot sets `prev_track=""`. Poll returns `out=""` which is falsy, so `out and out != prev_track` is False every iteration. Loop exhausts and returns False — never reaches the `RuntimeError` at line 876-877.

**Fix:** Stateful mock — let dedup/snapshot/poll succeed, fail only on the final add-to-playlist call:
1. Dedup → `("not_found", 0)`
2. Snapshot → `("Old|||Track", 0)`
3. Poll → `("Creep|||Radiohead", 0)`
4. Add-to-playlist → `("", 1)` — triggers `RuntimeError`

```python
def test_add_track_to_playlist_raises_on_osascript_failure(monkeypatch):
    """Raises RuntimeError when osascript returns non-zero."""
    monkeypatch.setattr(md, "search_itunes", lambda a, t: "12345")
    monkeypatch.setattr(md, "_play_store_track", lambda sid: True)
    responses = iter([("not_found", 0), ("Old|||Track", 0), ("Creep|||Radiohead", 0), ("", 1)])
    monkeypatch.setattr(md, "_run_applescript", lambda script: next(responses))
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(RuntimeError):
        md.add_track_to_playlist("Radiohead", "Creep")
```

---

## Fix 4: `test_get_machine_seed_random_mac_returns_none` (line 883)

**Root cause:** Test patches `uuid.getnode` but on macOS, `_get_machine_seed()` uses `subprocess.run(["ioreg", ...])` — the `uuid.getnode` fallback was removed during implementation. The test exercises a code path that no longer exists.

**Fix:** Delete the old test. Replace with three platform-specific tests that each mock the platform and force the platform-specific lookup to fail:

### 4a — macOS: ioreg fails

```python
def test_get_machine_seed_darwin_ioreg_fails_returns_none():
    """On macOS, if ioreg fails, returns None."""
    with patch("music_discovery.platform.system", return_value="Darwin"), \
         patch("music_discovery.subprocess.run", side_effect=Exception("no ioreg")):
        assert md._get_machine_seed() is None
```

### 4b — Windows: registry fails

```python
def test_get_machine_seed_windows_registry_fails_returns_none():
    """On Windows, if registry read fails, returns None."""
    mock_winreg = MagicMock()
    mock_winreg.OpenKey = MagicMock(side_effect=Exception("no key"))
    mock_winreg.HKEY_LOCAL_MACHINE = 0x80000002
    with patch("music_discovery.platform.system", return_value="Windows"), \
         patch.dict("sys.modules", {"winreg": mock_winreg}):
        assert md._get_machine_seed() is None
```

### 4c — Linux: /etc/machine-id missing

```python
def test_get_machine_seed_linux_no_machine_id_returns_none():
    """On Linux, if /etc/machine-id is missing, returns None."""
    with patch("music_discovery.platform.system", return_value="Linux"), \
         patch("music_discovery.pathlib.Path.read_text", side_effect=FileNotFoundError):
        assert md._get_machine_seed() is None
```

**Import needed:** `MagicMock` from `unittest.mock` (already imported as `patch` is used).

---

## Out of Scope

- Adding new tests beyond fixing the 4 broken ones
- Changes to production code
- Changes to other test functions
