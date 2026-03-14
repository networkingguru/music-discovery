# Playlist Generation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the playlist generation feature: add missing XML fallback wiring, add subprocess timeout, and write tests for all new functions.

**Architecture:** Most functions are already implemented in `music_discovery.py` (lines 322–482, 548–655). This plan adds the XML fallback path in `main()`, a timeout to `_run_applescript`, and comprehensive tests for: `fetch_top_tracks`, `sanitize_for_applescript`, `_run_applescript`, `setup_playlist`, `add_track_to_playlist`, `write_playlist_xml`, and `build_playlist`.

**Tech Stack:** Python stdlib (`subprocess`, `plistlib`, `argparse`), existing `requests`, pytest with `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-03-12-playlist-generation-design.md`

---

## Chunk 1: Bug Fixes

### Task 1: Add timeout to _run_applescript

**Files:**
- Modify: `music_discovery.py:354-361`

Up to 500 osascript calls are made. A hung process could block indefinitely.

- [ ] **Step 1: Write failing test**

```python
def test_run_applescript_has_timeout(monkeypatch):
    """_run_applescript passes a timeout to subprocess.run."""
    captured = {}
    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        result = MagicMock()
        result.stdout = ""
        result.returncode = 0
        return result
    monkeypatch.setattr(subprocess, "run", fake_run)
    md._run_applescript('return "hi"')
    assert "timeout" in captured
    assert captured["timeout"] >= 30
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py::test_run_applescript_has_timeout -v`
Expected: FAIL — `timeout` not in captured kwargs

- [ ] **Step 3: Add timeout to _run_applescript and handle TimeoutExpired**

In `music_discovery.py` line 354, update to include `timeout=30` and convert
`TimeoutExpired` to `RuntimeError` so it's caught by `build_playlist`'s
existing error handler:

```python
def _run_applescript(script):
    """Run an AppleScript via osascript. Returns (stdout, returncode)."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip(), result.returncode
    except subprocess.TimeoutExpired:
        raise RuntimeError("osascript timed out after 30 seconds")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py::test_run_applescript_has_timeout -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add music_discovery.py tests/test_music_discovery.py
git commit -m "fix: add 30s timeout to _run_applescript subprocess calls"
```

---

### Task 2: Wire XML fallback into main()

**Files:**
- Modify: `music_discovery.py:650-652` (the `--playlist` block in main)

The spec requires that if `build_playlist` fails during playlist setup (stage 1),
the code falls back to writing an importable XML plist. Currently `build_playlist`
returns silently on failure with no fallback. The fix: wrap the call in main and
trigger the fallback.

- [ ] **Step 1: Modify build_playlist to return status**

Change `build_playlist` (line 431) to return a tuple `(success, all_tracks)` so
`main()` can decide whether to fall back.

Current line 458-460:
```python
    if not setup_playlist():
        print("ERROR: Could not create/clear playlist — aborting playlist build.")
        return
```

Change to:
```python
    if not setup_playlist():
        print("ERROR: Could not create/clear playlist in Music.app.")
        return False, all_tracks
```

Current line 475-478 (RuntimeError handler):
```python
            except RuntimeError as e:
                print(f"ERROR: {e}")
                print("Apple Music may not be running or osascript permissions are denied.")
                return
```

Change to:
```python
            except RuntimeError as e:
                print(f"ERROR: {e}")
                print("Apple Music may not be running or osascript permissions are denied.")
                return False, all_tracks
```

Add at the end of `build_playlist` (after the success print):
```python
    return True, all_tracks
```

Also change the early return for empty artists (line 435-436):
```python
        print("No artists in results — skipping playlist generation.")
        return True, []
```

- [ ] **Step 2: Add fallback in main()**

Replace `music_discovery.py` lines 650-652:

```python
    # ── 8. Build playlist (optional) ───────────────────────
    if args.playlist:
        success, all_tracks = build_playlist(ranked, api_key, paths)
        if not success and all_tracks:
            print(f"\nFalling back to XML playlist export...")
            write_playlist_xml(all_tracks, paths["playlist_xml"])
            print(f"Import {paths['playlist_xml']} in Music.app via "
                  f"File → Library → Import Playlist.")
```

- [ ] **Step 3: Write test for fallback path**

```python
def test_fallback_writes_xml_when_build_fails(tmp_path):
    """When build_playlist returns (False, tracks), the fallback writes XML."""
    tracks = [
        {"name": "Creep", "artist": "Radiohead"},
        {"name": "Karma Police", "artist": "Radiohead"},
    ]
    xml_path = tmp_path / "Music Discovery.xml"
    # Simulate the fallback logic from main()
    success = False
    if not success and tracks:
        md.write_playlist_xml(tracks, xml_path)
    assert xml_path.exists()
    with open(xml_path, "rb") as f:
        plist = plistlib.load(f)
    assert len(plist["Tracks"]) == 2

def test_fallback_skips_xml_when_no_tracks(tmp_path):
    """No XML written if build_playlist fails with empty track list."""
    xml_path = tmp_path / "Music Discovery.xml"
    success = False
    tracks = []
    if not success and tracks:
        md.write_playlist_xml(tracks, xml_path)
    assert not xml_path.exists()
```

- [ ] **Step 4: Run test**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py::test_main_playlist_falls_back_to_xml -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add music_discovery.py tests/test_music_discovery.py
git commit -m "fix: wire XML plist fallback when playlist creation fails"
```

---

## Chunk 2: Tests for Existing Functions

### Task 3: Tests for fetch_top_tracks

**Files:**
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write tests**

```python
# ── fetch_top_tracks ──────────────────────────────────────

def test_fetch_top_tracks_returns_track_list():
    """Returns list of {name, artist} dicts from Last.fm getTopTracks."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "toptracks": {"track": [
            {"name": "Creep", "artist": {"name": "Radiohead"}},
            {"name": "Karma Police", "artist": {"name": "Radiohead"}},
        ]}
    }
    with patch("requests.get", return_value=resp):
        result = md.fetch_top_tracks("radiohead", "fake_key")
    assert result == [
        {"name": "Creep", "artist": "Radiohead"},
        {"name": "Karma Police", "artist": "Radiohead"},
    ]

def test_fetch_top_tracks_api_error_returns_empty():
    """Non-200 response returns empty list."""
    resp = MagicMock()
    resp.status_code = 500
    with patch("requests.get", return_value=resp):
        result = md.fetch_top_tracks("radiohead", "fake_key")
    assert result == []

def test_fetch_top_tracks_skips_nameless():
    """Tracks with empty name are skipped."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "toptracks": {"track": [
            {"name": "Creep", "artist": {"name": "Radiohead"}},
            {"name": "", "artist": {"name": "Radiohead"}},
        ]}
    }
    with patch("requests.get", return_value=resp):
        result = md.fetch_top_tracks("radiohead", "fake_key")
    assert len(result) == 1
    assert result[0]["name"] == "Creep"

def test_fetch_top_tracks_network_error_returns_empty():
    """Network exception returns empty list."""
    with patch("requests.get", side_effect=Exception("timeout")):
        result = md.fetch_top_tracks("radiohead", "fake_key")
    assert result == []
```

- [ ] **Step 2: Run tests**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -k "fetch_top_tracks" -v`
Expected: 4 PASSED

- [ ] **Step 3: Commit**

```bash
git add tests/test_music_discovery.py
git commit -m "test: add tests for fetch_top_tracks"
```

---

### Task 4: Tests for sanitize_for_applescript

**Files:**
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write tests**

```python
# ── sanitize_for_applescript ──────────────────────────────

def test_sanitize_for_applescript_escapes_quotes():
    """Double quotes are escaped with backslash."""
    assert md.sanitize_for_applescript('Say "Hello"') == 'Say \\"Hello\\"'

def test_sanitize_for_applescript_escapes_backslashes():
    """Backslashes are escaped."""
    assert md.sanitize_for_applescript("AC\\DC") == "AC\\\\DC"

def test_sanitize_for_applescript_strips_control_chars():
    """Control characters are removed."""
    assert md.sanitize_for_applescript("Hello\x00World\x1f") == "HelloWorld"

def test_sanitize_for_applescript_plain_text():
    """Plain text passes through unchanged."""
    assert md.sanitize_for_applescript("Radiohead") == "Radiohead"

def test_sanitize_for_applescript_ampersand():
    """Ampersands pass through (fine in AppleScript strings)."""
    assert md.sanitize_for_applescript("Nick Cave & The Bad Seeds") == "Nick Cave & The Bad Seeds"
```

- [ ] **Step 2: Run tests**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -k "sanitize_for_applescript" -v`
Expected: 5 PASSED

- [ ] **Step 3: Commit**

```bash
git add tests/test_music_discovery.py
git commit -m "test: add tests for sanitize_for_applescript"
```

---

### Task 5: Tests for setup_playlist

**Files:**
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write tests**

```python
# ── setup_playlist ────────────────────────────────────────

def test_setup_playlist_returns_true_on_success(monkeypatch):
    """Returns True when osascript succeeds."""
    monkeypatch.setattr(md, "_run_applescript", lambda script: ("", 0))
    assert md.setup_playlist() is True

def test_setup_playlist_returns_false_on_failure(monkeypatch):
    """Returns False when osascript fails."""
    monkeypatch.setattr(md, "_run_applescript", lambda script: ("error", 1))
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

- [ ] **Step 2: Run tests**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -k "setup_playlist" -v`
Expected: 3 PASSED

- [ ] **Step 3: Commit**

```bash
git add tests/test_music_discovery.py
git commit -m "test: add tests for setup_playlist"
```

---

### Task 6: Tests for add_track_to_playlist

**Files:**
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write tests**

```python
# ── add_track_to_playlist ─────────────────────────────────

def test_add_track_to_playlist_returns_true_on_ok(monkeypatch):
    """Returns True when AppleScript returns 'ok'."""
    monkeypatch.setattr(md, "_run_applescript", lambda script: ("ok", 0))
    assert md.add_track_to_playlist("Radiohead", "Creep") is True

def test_add_track_to_playlist_returns_false_on_notfound(monkeypatch):
    """Returns False when track is not found."""
    monkeypatch.setattr(md, "_run_applescript", lambda script: ("notfound", 0))
    assert md.add_track_to_playlist("Nobody", "Fake Song") is False

def test_add_track_to_playlist_raises_on_osascript_failure(monkeypatch):
    """Raises RuntimeError when osascript returns non-zero."""
    monkeypatch.setattr(md, "_run_applescript", lambda script: ("", 1))
    import pytest
    with pytest.raises(RuntimeError):
        md.add_track_to_playlist("Radiohead", "Creep")

def test_add_track_to_playlist_escapes_special_chars(monkeypatch):
    """Quotes in artist/track names are escaped in the AppleScript."""
    captured = []
    def fake_run(script):
        captured.append(script)
        return ("ok", 0)
    monkeypatch.setattr(md, "_run_applescript", fake_run)
    md.add_track_to_playlist('Artist "X"', 'Song "Y"')
    assert '\\"' in captured[0]
```

- [ ] **Step 2: Run tests**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -k "add_track_to_playlist" -v`
Expected: 4 PASSED

- [ ] **Step 3: Commit**

```bash
git add tests/test_music_discovery.py
git commit -m "test: add tests for add_track_to_playlist"
```

---

### Task 7: Tests for write_playlist_xml

**Files:**
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write tests**

```python
# ── write_playlist_xml ────────────────────────────────────

def test_write_playlist_xml_creates_valid_plist(tmp_path):
    """Writes an XML plist with Tracks and Playlists keys."""
    output = tmp_path / "test.xml"
    tracks = [
        {"name": "Creep", "artist": "Radiohead"},
        {"name": "Red Right Hand", "artist": "Nick Cave"},
    ]
    md.write_playlist_xml(tracks, output)
    assert output.exists()
    with open(output, "rb") as f:
        plist = plistlib.load(f)
    assert "Tracks" in plist
    assert "Playlists" in plist
    assert len(plist["Tracks"]) == 2
    assert len(plist["Playlists"][0]["Playlist Items"]) == 2

def test_write_playlist_xml_empty_tracks(tmp_path):
    """Empty track list produces valid plist with no tracks."""
    output = tmp_path / "test.xml"
    md.write_playlist_xml([], output)
    with open(output, "rb") as f:
        plist = plistlib.load(f)
    assert plist["Tracks"] == {}
    assert plist["Playlists"][0]["Playlist Items"] == []

def test_write_playlist_xml_track_metadata(tmp_path):
    """Track entries contain Name and Artist."""
    output = tmp_path / "test.xml"
    md.write_playlist_xml([{"name": "Creep", "artist": "Radiohead"}], output)
    with open(output, "rb") as f:
        plist = plistlib.load(f)
    track = list(plist["Tracks"].values())[0]
    assert track["Name"] == "Creep"
    assert track["Artist"] == "Radiohead"
```

- [ ] **Step 2: Run tests**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -k "write_playlist_xml" -v`
Expected: 3 PASSED

- [ ] **Step 3: Commit**

```bash
git add tests/test_music_discovery.py
git commit -m "test: add tests for write_playlist_xml"
```

---

### Task 8: Tests for build_playlist

**Files:**
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write tests**

```python
# ── build_playlist ────────────────────────────────────────

def test_build_playlist_calls_setup_and_adds_tracks(monkeypatch, tmp_path):
    """build_playlist calls setup_playlist then adds each track."""
    monkeypatch.setattr(md, "setup_playlist", lambda: True)
    add_calls = []
    monkeypatch.setattr(md, "add_track_to_playlist",
                        lambda artist, track: add_calls.append((artist, track)) or True)
    monkeypatch.setattr(md, "load_cache", lambda p: {
        "radiohead": [{"name": "Creep", "artist": "Radiohead"}],
    })
    monkeypatch.setattr(md, "save_cache", lambda c, p: None)
    monkeypatch.setattr(md, "fetch_top_tracks", lambda a, k: [])
    monkeypatch.setattr("time.sleep", lambda s: None)
    ranked = [(10.0, "radiohead")]
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    paths = md._build_paths()
    success, tracks = md.build_playlist(ranked, "fake_key", paths)
    assert success is True
    assert ("Radiohead", "Creep") in add_calls

def test_build_playlist_returns_false_on_setup_failure(monkeypatch, tmp_path):
    """Returns (False, tracks) when setup_playlist fails."""
    monkeypatch.setattr(md, "setup_playlist", lambda: False)
    monkeypatch.setattr(md, "load_cache", lambda p: {})
    monkeypatch.setattr(md, "save_cache", lambda c, p: None)
    monkeypatch.setattr(md, "fetch_top_tracks", lambda a, k: [])
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    paths = md._build_paths()
    ranked = [(10.0, "radiohead")]
    success, _ = md.build_playlist(ranked, "fake_key", paths)
    assert success is False

def test_build_playlist_empty_ranked(monkeypatch, tmp_path):
    """Empty ranked list skips playlist generation."""
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    paths = md._build_paths()
    success, tracks = md.build_playlist([], "fake_key", paths)
    assert success is True
    assert tracks == []

def test_build_playlist_returns_false_on_runtime_error(monkeypatch, tmp_path):
    """Returns (False, tracks) when add_track_to_playlist raises RuntimeError."""
    monkeypatch.setattr(md, "setup_playlist", lambda: True)
    monkeypatch.setattr(md, "add_track_to_playlist",
                        lambda artist, track: (_ for _ in ()).throw(
                            RuntimeError("osascript failed")))
    monkeypatch.setattr(md, "load_cache", lambda p: {
        "radiohead": [{"name": "Creep", "artist": "Radiohead"}],
    })
    monkeypatch.setattr(md, "save_cache", lambda c, p: None)
    monkeypatch.setattr(md, "fetch_top_tracks", lambda a, k: [])
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    paths = md._build_paths()
    ranked = [(10.0, "radiohead")]
    success, tracks = md.build_playlist(ranked, "fake_key", paths)
    assert success is False
    assert len(tracks) > 0
```

- [ ] **Step 2: Run tests**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -k "build_playlist" -v`
Expected: 3 PASSED

- [ ] **Step 3: Commit**

```bash
git add tests/test_music_discovery.py
git commit -m "test: add tests for build_playlist"
```

---

## Chunk 3: Final Verification

### Task 9: Run full test suite and manual test

- [ ] **Step 1: Run full test suite**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -v`
Expected: All tests PASS

- [ ] **Step 2: Run without --playlist to verify no regression**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 music_discovery.py`
Expected: Normal discovery output, no playlist step.

- [ ] **Step 3: Run with --playlist**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 music_discovery.py --playlist`
Expected: Discovery runs, top tracks fetched, "Music Discovery" playlist created in Music.app.

- [ ] **Step 4: Commit any fixes from manual testing**
