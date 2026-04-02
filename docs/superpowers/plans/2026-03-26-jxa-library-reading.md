# JXA Library Reading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace manual XML export with live JXA queries to Music.app for reading favorited tracks

**Architecture:** Add `parse_library_jxa()` and `parse_md_playlist_jxa()` that use the existing `_run_jxa()` helper to query Music.app directly. On macOS, prefer JXA; fall back to XML if JXA fails or `--library` is explicitly specified. Return the same data format as existing functions for seamless integration.

**Tech Stack:** JXA (JavaScript for Automation), osascript, JSON

---

### Task 1: Implement `parse_library_jxa()`

**Files:**
- Modify: `music_discovery.py` (add `parse_library_jxa` after `parse_library`, ~line 374)
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write failing tests for `parse_library_jxa`**

Add to `tests/test_music_discovery.py`:

```python
# ── JXA library reading tests ────────────────────────────────

def test_parse_library_jxa_basic():
    """parse_library_jxa returns {artist: count} dict from JXA output."""
    jxa_output = json.dumps(["Tom Waits", "Radiohead", "Tom Waits", "Tom Waits"])
    with patch.object(md, "_run_jxa", return_value=(jxa_output, 0)):
        result = md.parse_library_jxa()
    assert result == {"tom waits": 3, "radiohead": 1}

def test_parse_library_jxa_empty_library():
    """Empty favorited list returns empty dict."""
    jxa_output = json.dumps([])
    with patch.object(md, "_run_jxa", return_value=(jxa_output, 0)):
        result = md.parse_library_jxa()
    assert result == {}

def test_parse_library_jxa_case_folding():
    """Artist names are lowercased and deduplicated."""
    jxa_output = json.dumps(["Radiohead", "RADIOHEAD", "radiohead"])
    with patch.object(md, "_run_jxa", return_value=(jxa_output, 0)):
        result = md.parse_library_jxa()
    assert result == {"radiohead": 3}

def test_parse_library_jxa_strips_whitespace():
    """Leading/trailing whitespace in artist names is stripped."""
    jxa_output = json.dumps(["  Tom Waits  ", "Tom Waits"])
    with patch.object(md, "_run_jxa", return_value=(jxa_output, 0)):
        result = md.parse_library_jxa()
    assert result == {"tom waits": 2}

def test_parse_library_jxa_skips_empty_artists():
    """Empty string artists are excluded."""
    jxa_output = json.dumps(["Tom Waits", "", "  ", "Radiohead"])
    with patch.object(md, "_run_jxa", return_value=(jxa_output, 0)):
        result = md.parse_library_jxa()
    assert result == {"tom waits": 1, "radiohead": 1}

def test_parse_library_jxa_nonzero_exit():
    """Non-zero return code raises RuntimeError."""
    with patch.object(md, "_run_jxa", return_value=("", 1)):
        with pytest.raises(RuntimeError, match="JXA library read failed"):
            md.parse_library_jxa()

def test_parse_library_jxa_invalid_json():
    """Malformed JSON raises RuntimeError."""
    with patch.object(md, "_run_jxa", return_value=("not json at all", 0)):
        with pytest.raises(RuntimeError, match="Failed to parse JXA output"):
            md.parse_library_jxa()

def test_parse_library_jxa_timeout():
    """osascript timeout propagates as RuntimeError from _run_jxa."""
    with patch.object(md, "_run_jxa", side_effect=RuntimeError("osascript (JXA) timed out after 30 seconds")):
        with pytest.raises(RuntimeError, match="timed out"):
            md.parse_library_jxa()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -k "parse_library_jxa" -v`

Expected: FAIL — `parse_library_jxa` does not exist yet.

- [ ] **Step 3: Implement `parse_library_jxa`**

Add to `music_discovery.py` after the `parse_library` function (after line 373):

```python
def parse_library_jxa():
    """Read favorited tracks from Music.app via JXA, return {artist: count} dict.
    Artists are lowercase. Raises RuntimeError on failure."""
    script = '''
var music = Application("Music");
var lib = music.libraryPlaylists[0];
var favTracks = lib.tracks.whose({favorited: true});
var artists = favTracks.artist();
JSON.stringify(artists);
'''
    stdout, code = _run_jxa(script)
    if code != 0:
        raise RuntimeError(f"JXA library read failed (exit {code}): {stdout}")
    try:
        artist_list = json.loads(stdout)
    except (json.JSONDecodeError, TypeError) as e:
        raise RuntimeError(f"Failed to parse JXA output: {e}")
    counts = {}
    for artist in artist_list:
        if not isinstance(artist, str):
            continue
        artist = artist.strip().lower()
        if artist:
            counts[artist] = counts.get(artist, 0) + 1
    return counts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -k "parse_library_jxa" -v`

Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && git add music_discovery.py tests/test_music_discovery.py && git commit -m "feat: add parse_library_jxa() for reading favorited tracks via JXA"`

---

### Task 2: Implement `parse_md_playlist_jxa()`

**Files:**
- Modify: `music_discovery.py` (add `parse_md_playlist_jxa` after `parse_library_jxa`)
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write failing tests for `parse_md_playlist_jxa`**

Add to `tests/test_music_discovery.py`:

```python
# ── JXA playlist reading tests ────────────────────────────────

def test_parse_md_playlist_jxa_basic():
    """Returns (artist_set, total_tracks, unplayed_count) from JXA output."""
    jxa_output = json.dumps({
        "tracks": [
            {"artist": "Nick Cave", "playCount": 5},
            {"artist": "Leonard Cohen", "playCount": 0},
            {"artist": "PJ Harvey", "playCount": 3},
            {"artist": "Nick Cave", "playCount": 2},
        ]
    })
    with patch.object(md, "_run_jxa", return_value=(jxa_output, 0)):
        result = md.parse_md_playlist_jxa()
    artists, total, unplayed = result
    assert artists == {"nick cave", "leonard cohen", "pj harvey"}
    assert total == 4
    assert unplayed == 1

def test_parse_md_playlist_jxa_all_unplayed():
    """All tracks with playCount 0 are counted as unplayed."""
    jxa_output = json.dumps({
        "tracks": [
            {"artist": "A", "playCount": 0},
            {"artist": "B", "playCount": 0},
        ]
    })
    with patch.object(md, "_run_jxa", return_value=(jxa_output, 0)):
        artists, total, unplayed = md.parse_md_playlist_jxa()
    assert total == 2
    assert unplayed == 2

def test_parse_md_playlist_jxa_no_playlist():
    """Returns None when the playlist does not exist (JXA returns 'null')."""
    jxa_output = "null"
    with patch.object(md, "_run_jxa", return_value=(jxa_output, 0)):
        result = md.parse_md_playlist_jxa()
    assert result is None

def test_parse_md_playlist_jxa_empty_playlist():
    """Returns None when the playlist exists but has no tracks."""
    jxa_output = json.dumps({"tracks": []})
    with patch.object(md, "_run_jxa", return_value=(jxa_output, 0)):
        result = md.parse_md_playlist_jxa()
    assert result is None

def test_parse_md_playlist_jxa_nonzero_exit():
    """Non-zero return code raises RuntimeError."""
    with patch.object(md, "_run_jxa", return_value=("error text", 1)):
        with pytest.raises(RuntimeError, match="JXA playlist read failed"):
            md.parse_md_playlist_jxa()

def test_parse_md_playlist_jxa_invalid_json():
    """Malformed JSON raises RuntimeError."""
    with patch.object(md, "_run_jxa", return_value=("broken{json", 0)):
        with pytest.raises(RuntimeError, match="Failed to parse JXA playlist output"):
            md.parse_md_playlist_jxa()

def test_parse_md_playlist_jxa_skips_empty_artists():
    """Tracks with empty artist strings are counted but artist is not added to set."""
    jxa_output = json.dumps({
        "tracks": [
            {"artist": "Nick Cave", "playCount": 1},
            {"artist": "", "playCount": 0},
        ]
    })
    with patch.object(md, "_run_jxa", return_value=(jxa_output, 0)):
        artists, total, unplayed = md.parse_md_playlist_jxa()
    assert artists == {"nick cave"}
    assert total == 2
    assert unplayed == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -k "parse_md_playlist_jxa" -v`

Expected: FAIL — `parse_md_playlist_jxa` does not exist yet.

- [ ] **Step 3: Implement `parse_md_playlist_jxa`**

Add to `music_discovery.py` after `parse_library_jxa`:

```python
def parse_md_playlist_jxa():
    """Read the Music Discovery playlist from Music.app via JXA.
    Returns (artist_set, total_tracks, unplayed_count) or None if no playlist.
    Raises RuntimeError on JXA failure."""
    script = '''
var music = Application("Music");
var playlists = music.userPlaylists.whose({name: "Music Discovery"});
if (playlists.length === 0) {
    JSON.stringify(null);
} else {
    var pl = playlists[0];
    var tracks = pl.tracks;
    var count = tracks.length;
    var result = [];
    if (count > 0) {
        var artists = tracks.artist();
        var playCounts = tracks.playedCount();
        for (var i = 0; i < count; i++) {
            result.push({artist: artists[i] || "", playCount: playCounts[i] || 0});
        }
    }
    JSON.stringify({tracks: result});
}
'''
    stdout, code = _run_jxa(script)
    if code != 0:
        raise RuntimeError(f"JXA playlist read failed (exit {code}): {stdout}")
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, TypeError) as e:
        raise RuntimeError(f"Failed to parse JXA playlist output: {e}")
    if data is None:
        return None
    track_list = data.get("tracks", [])
    if not track_list:
        return None
    artists = set()
    unplayed = 0
    total = len(track_list)
    for t in track_list:
        artist = t.get("artist", "").strip().lower()
        if artist:
            artists.add(artist)
        if t.get("playCount", 0) == 0:
            unplayed += 1
    return artists, total, unplayed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -k "parse_md_playlist_jxa" -v`

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && git add music_discovery.py tests/test_music_discovery.py && git commit -m "feat: add parse_md_playlist_jxa() for reading MD playlist via JXA"`

---

### Task 3: Update `main()` to prefer JXA, with XML fallback

**Files:**
- Modify: `music_discovery.py` (update `main()`, ~lines 1302-1347)
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write failing tests for the JXA/XML selection logic**

Add to `tests/test_music_discovery.py`:

```python
# ── main() JXA/XML fallback tests ────────────────────────────

def test_main_uses_jxa_on_darwin(tmp_path):
    """On Darwin with no --library flag, main() calls parse_library_jxa."""
    fake_artists = {"tom waits": 3, "radiohead": 1}
    with patch("sys.argv", ["music_discovery.py"]), \
         patch.object(md, "load_dotenv"), \
         patch.object(md, "_build_paths", return_value={
             "cache": str(tmp_path / "cache.json"),
             "filter_cache": str(tmp_path / "filter.json"),
             "blocklist": str(tmp_path / "blocklist.json"),
         }), \
         patch("platform.system", return_value="Darwin"), \
         patch.object(md, "parse_library_jxa", return_value=fake_artists) as mock_jxa, \
         patch.object(md, "parse_md_playlist_jxa", return_value=None), \
         patch.object(md, "load_cache", return_value={}), \
         patch.object(md, "load_blocklist", return_value=set()), \
         patch.object(md, "load_user_blocklist", return_value=set()), \
         patch.object(md, "prompt_for_api_key", return_value=None), \
         patch.object(md, "scrape_all_artists", return_value={}), \
         patch.object(md, "save_cache"), \
         patch.object(md, "score_artists", return_value=[]), \
         patch.object(md, "display_results"):
        md.main()
    mock_jxa.assert_called_once()

def test_main_falls_back_to_xml_on_jxa_failure(tmp_path):
    """If JXA fails, main() falls back to XML parsing."""
    fake_artists = {"tom waits": 3}
    plist_data = {"Tracks": {"1": {"Artist": "Tom Waits", "Loved": True}}, "Playlists": []}
    plist_path = tmp_path / "Library.xml"
    import plistlib as pl
    plist_path.write_bytes(pl.dumps(plist_data))
    with patch("sys.argv", ["music_discovery.py"]), \
         patch.object(md, "load_dotenv"), \
         patch.object(md, "_build_paths", return_value={
             "cache": str(tmp_path / "cache.json"),
             "filter_cache": str(tmp_path / "filter.json"),
             "blocklist": str(tmp_path / "blocklist.json"),
         }), \
         patch("platform.system", return_value="Darwin"), \
         patch.object(md, "parse_library_jxa", side_effect=RuntimeError("Music.app not running")), \
         patch.object(md, "_resolve_library_path", return_value=plist_path), \
         patch.object(md, "parse_library", return_value=(fake_artists, plist_data)) as mock_xml, \
         patch.object(md, "parse_md_playlist", return_value=None), \
         patch.object(md, "load_cache", return_value={}), \
         patch.object(md, "load_blocklist", return_value=set()), \
         patch.object(md, "load_user_blocklist", return_value=set()), \
         patch.object(md, "prompt_for_api_key", return_value=None), \
         patch.object(md, "scrape_all_artists", return_value={}), \
         patch.object(md, "save_cache"), \
         patch.object(md, "score_artists", return_value=[]), \
         patch.object(md, "display_results"):
        md.main()
    mock_xml.assert_called_once()

def test_main_uses_xml_when_library_flag_passed(tmp_path):
    """When --library is explicit, skip JXA and use XML directly."""
    fake_artists = {"tom waits": 3}
    plist_data = {"Tracks": {"1": {"Artist": "Tom Waits", "Loved": True}}, "Playlists": []}
    plist_path = tmp_path / "Library.xml"
    import plistlib as pl
    plist_path.write_bytes(pl.dumps(plist_data))
    with patch("sys.argv", ["music_discovery.py", "--library", str(plist_path)]), \
         patch.object(md, "load_dotenv"), \
         patch.object(md, "_build_paths", return_value={
             "cache": str(tmp_path / "cache.json"),
             "filter_cache": str(tmp_path / "filter.json"),
             "blocklist": str(tmp_path / "blocklist.json"),
         }), \
         patch.object(md, "parse_library_jxa") as mock_jxa, \
         patch.object(md, "parse_library", return_value=(fake_artists, plist_data)) as mock_xml, \
         patch.object(md, "parse_md_playlist", return_value=None), \
         patch.object(md, "load_cache", return_value={}), \
         patch.object(md, "load_blocklist", return_value=set()), \
         patch.object(md, "load_user_blocklist", return_value=set()), \
         patch.object(md, "prompt_for_api_key", return_value=None), \
         patch.object(md, "scrape_all_artists", return_value={}), \
         patch.object(md, "save_cache"), \
         patch.object(md, "score_artists", return_value=[]), \
         patch.object(md, "display_results"):
        md.main()
    mock_jxa.assert_not_called()
    mock_xml.assert_called_once()

def test_main_uses_xml_on_non_darwin(tmp_path):
    """On non-Darwin platforms, use XML parsing (no JXA attempt)."""
    fake_artists = {"tom waits": 3}
    plist_data = {"Tracks": {"1": {"Artist": "Tom Waits", "Loved": True}}, "Playlists": []}
    plist_path = tmp_path / "Library.xml"
    import plistlib as pl
    plist_path.write_bytes(pl.dumps(plist_data))
    with patch("sys.argv", ["music_discovery.py"]), \
         patch.object(md, "load_dotenv"), \
         patch.object(md, "_build_paths", return_value={
             "cache": str(tmp_path / "cache.json"),
             "filter_cache": str(tmp_path / "filter.json"),
             "blocklist": str(tmp_path / "blocklist.json"),
         }), \
         patch("platform.system", return_value="Linux"), \
         patch.object(md, "parse_library_jxa") as mock_jxa, \
         patch.object(md, "_resolve_library_path", return_value=plist_path), \
         patch.object(md, "parse_library", return_value=(fake_artists, plist_data)) as mock_xml, \
         patch.object(md, "parse_md_playlist", return_value=None), \
         patch.object(md, "load_cache", return_value={}), \
         patch.object(md, "load_blocklist", return_value=set()), \
         patch.object(md, "load_user_blocklist", return_value=set()), \
         patch.object(md, "prompt_for_api_key", return_value=None), \
         patch.object(md, "scrape_all_artists", return_value={}), \
         patch.object(md, "save_cache"), \
         patch.object(md, "score_artists", return_value=[]), \
         patch.object(md, "display_results"):
        md.main()
    mock_jxa.assert_not_called()
    mock_xml.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -k "test_main_uses_jxa or test_main_falls_back or test_main_uses_xml" -v`

Expected: FAIL — `main()` does not yet have the JXA logic.

- [ ] **Step 3: Update `main()` to prefer JXA on macOS**

Replace the library-reading section of `main()` in `music_discovery.py`. Change lines ~1302-1347 from:

```python
    # ── 1. Parse library ───────────────────────────────────
    library_path = _resolve_library_path(args.library)
    if library_path is None:
        return

    log.info(f"Reading library: {library_path}")

    api_key = os.environ.get("LASTFM_API_KEY", "").strip()
    if not api_key:
        api_key = prompt_for_api_key()
        # api_key is None if user skipped or exhausted attempts

    if not api_key:
        log.info("\nRunning without Last.fm — results will include well-known artists")
        log.info("that would normally be filtered out.\n")

    library_artists, raw_library = parse_library(library_path)
    log.info(f"Found {len(library_artists)} unique loved/favorited artists.\n")

    # ── 2. Load caches ─────────────────────────────────────
    cache        = load_cache(paths["cache"])
    filter_cache = load_cache(paths["filter_cache"]) if api_key else {}
    file_blocklist = load_blocklist(paths["blocklist"])
    user_blocklist_path = pathlib.Path(__file__).parent / "blocklist.txt"
    user_blocklist = load_user_blocklist(user_blocklist_path)
    file_blocklist |= user_blocklist

    # ── 2b. Audit previous Music Discovery playlist ────────
    # The XML file can be stale — verify playlist exists in Music.app first
    md_audit = None
    if platform.system() == "Darwin":
        out, code = _run_applescript('''
tell application "Music"
    if (exists user playlist "Music Discovery") then
        return "yes"
    else
        return "no"
    end if
end tell
''')
        if code == 0 and out == "yes":
            md_audit = parse_md_playlist(raw_library)
        elif code == 0 and out == "no":
            log.info("No existing Music Discovery playlist found.")
    else:
        md_audit = parse_md_playlist(raw_library)
```

To:

```python
    # ── 1. Parse library ───────────────────────────────────
    use_jxa = platform.system() == "Darwin" and args.library is None
    library_artists = None
    raw_library = None

    if use_jxa:
        try:
            log.info("Reading library from Music.app via JXA...")
            library_artists = parse_library_jxa()
            log.info(f"Found {len(library_artists)} unique loved/favorited artists.\n")
        except RuntimeError as e:
            log.warning(f"JXA library read failed: {e}")
            log.warning("Falling back to XML library parsing...")
            use_jxa = False

    if library_artists is None:
        library_path = _resolve_library_path(args.library)
        if library_path is None:
            return
        log.info(f"Reading library: {library_path}")
        library_artists, raw_library = parse_library(library_path)
        log.info(f"Found {len(library_artists)} unique loved/favorited artists.\n")

    api_key = os.environ.get("LASTFM_API_KEY", "").strip()
    if not api_key:
        api_key = prompt_for_api_key()
        # api_key is None if user skipped or exhausted attempts

    if not api_key:
        log.info("\nRunning without Last.fm — results will include well-known artists")
        log.info("that would normally be filtered out.\n")

    # ── 2. Load caches ─────────────────────────────────────
    cache        = load_cache(paths["cache"])
    filter_cache = load_cache(paths["filter_cache"]) if api_key else {}
    file_blocklist = load_blocklist(paths["blocklist"])
    user_blocklist_path = pathlib.Path(__file__).parent / "blocklist.txt"
    user_blocklist = load_user_blocklist(user_blocklist_path)
    file_blocklist |= user_blocklist

    # ── 2b. Audit previous Music Discovery playlist ────────
    md_audit = None
    if use_jxa:
        try:
            md_audit = parse_md_playlist_jxa()
            if md_audit is None:
                log.info("No existing Music Discovery playlist found.")
        except RuntimeError as e:
            log.warning(f"JXA playlist read failed: {e}")
    elif platform.system() == "Darwin" and raw_library is not None:
        out, code = _run_applescript('''
tell application "Music"
    if (exists user playlist "Music Discovery") then
        return "yes"
    else
        return "no"
    end if
end tell
''')
        if code == 0 and out == "yes":
            md_audit = parse_md_playlist(raw_library)
        elif code == 0 and out == "no":
            log.info("No existing Music Discovery playlist found.")
    elif raw_library is not None:
        md_audit = parse_md_playlist(raw_library)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -k "test_main_uses_jxa or test_main_falls_back or test_main_uses_xml" -v`

Expected: all 4 tests PASS.

- [ ] **Step 5: Run the full test suite to check for regressions**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -v`

Expected: all tests PASS (existing + new).

- [ ] **Step 6: Commit**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && git add music_discovery.py tests/test_music_discovery.py && git commit -m "feat: prefer JXA for library reading on macOS, fall back to XML"`

---

### Task 4: Manual smoke test with live data

- [ ] **Step 1: Run with JXA (no --library flag)**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python music_discovery.py 2>&1 | head -20`

Verify: output says "Reading library from Music.app via JXA..." and reports the artist count.

- [ ] **Step 2: Run with explicit --library flag to test XML fallback**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python music_discovery.py --library ~/Music/Music/Music\ Library.xml 2>&1 | head -20`

Verify: output says "Reading library:" with the XML path (no JXA mention).

- [ ] **Step 3: Verify artist counts match between JXA and XML**

Run both modes and compare the number of unique artists. They should be identical (or very close — the XML may be stale if not recently exported).

---

### Task 5: Expert review and cleanup

- [ ] **Step 1: Review all new code for correctness**

Check:
- JXA scripts handle edge cases (no Music.app, empty library, permission denied)
- JSON parsing is robust (handles null, empty arrays, malformed data)
- The `_run_jxa` timeout (30s) is sufficient for large libraries
- Error messages are clear and actionable
- No raw_library leaks when using JXA path

- [ ] **Step 2: Review test coverage**

Verify tests cover:
- Happy path for both new functions
- Error paths (non-zero exit, invalid JSON, timeout)
- Edge cases (empty library, empty artists, whitespace)
- Fallback logic in main() (4 scenarios: JXA success, JXA failure, --library flag, non-Darwin)

- [ ] **Step 3: Run full test suite one final time**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -v`

Expected: all tests PASS.

- [ ] **Step 4: Final commit if any cleanup was needed**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && git add -A && git commit -m "chore: cleanup from expert review of JXA library reading"`
