# Auto-Import & Playlist Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-export a fresh Music Library XML on macOS and audit the previous Music Discovery playlist to blocklist rejected artists before scoring.

**Architecture:** Two new functions (`auto_export_library`, `audit_md_playlist`) added to `music_discovery.py`, called early in `main()`. The auto-export replaces `_resolve_library_path` on macOS when no `--library` flag is given. The audit runs after `parse_library` but before scoring, writing rejected artists to `blocklist_cache.json` via the existing `save_blocklist` mechanism.

**Tech Stack:** Python, plistlib, subprocess (osascript), existing blocklist infrastructure.

**Spec:** `docs/superpowers/specs/2026-03-19-auto-import-playlist-audit-design.md`

---

### Task 1: Auto-export library XML via AppleScript

**Files:**
- Modify: `music_discovery.py` (add `auto_export_library` after `_resolve_library_path`, ~line 60)
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write failing tests for `auto_export_library`**

Add to `tests/test_music_discovery.py`:

```python
from unittest.mock import patch, MagicMock
import platform

def test_auto_export_library_returns_path_on_success(tmp_path):
    """On macOS, auto_export_library should call osascript and return the export path."""
    export_path = tmp_path / "Library.xml"
    # Create a minimal valid plist so the file-exists check passes
    export_path.write_bytes(plistlib.dumps({"Tracks": {}}))
    mock_result = MagicMock(returncode=0, stderr="")
    with patch('subprocess.run', return_value=mock_result) as mock_run:
        result = md.auto_export_library(tmp_path)
    assert result == export_path
    mock_run.assert_called_once()
    # Verify osascript was called
    assert mock_run.call_args[0][0][0] == "osascript"

def test_auto_export_library_returns_none_on_failure(tmp_path):
    """If osascript returns non-zero, return None."""
    mock_result = MagicMock(returncode=1, stderr="error")
    with patch('subprocess.run', return_value=mock_result):
        result = md.auto_export_library(tmp_path)
    assert result is None

def test_auto_export_library_returns_none_on_timeout(tmp_path):
    """If osascript times out, return None."""
    with patch('subprocess.run', side_effect=subprocess.TimeoutExpired("osascript", 120)):
        result = md.auto_export_library(tmp_path)
    assert result is None

def test_auto_export_library_returns_none_when_no_file(tmp_path):
    """If osascript succeeds but no file is produced, return None."""
    mock_result = MagicMock(returncode=0, stderr="")
    with patch('subprocess.run', return_value=mock_result):
        result = md.auto_export_library(tmp_path)
    assert result is None  # Library.xml doesn't exist
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py::test_auto_export_library_returns_path_on_success tests/test_music_discovery.py::test_auto_export_library_returns_none_on_failure tests/test_music_discovery.py::test_auto_export_library_returns_none_on_timeout -v`

Expected: FAIL — `auto_export_library` does not exist yet.

- [ ] **Step 3: Implement `auto_export_library`**

Add to `music_discovery.py` after `_resolve_library_path` (around line 60):

```python
def auto_export_library(cache_dir):
    """Export a fresh Music Library XML via AppleScript (macOS only).
    Exports to cache_dir/Library.xml, overwriting any previous export.
    Returns the Path on success, or None on failure.
    Uses a 120-second timeout to handle large libraries."""
    export_path = pathlib.Path(cache_dir) / "Library.xml"
    script = (
        f'tell application "Music" to export library playlist 1 '
        f'to POSIX file "{export_path}"'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            log.error(f"Library export failed: {result.stderr.strip()}")
            return None
        if not export_path.exists():
            log.error("Library export produced no file.")
            return None
        return export_path
    except subprocess.TimeoutExpired:
        log.error("Library export timed out (120s). Try --library instead.")
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py::test_auto_export_library_returns_path_on_success tests/test_music_discovery.py::test_auto_export_library_returns_none_on_failure tests/test_music_discovery.py::test_auto_export_library_returns_none_on_timeout -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add music_discovery.py tests/test_music_discovery.py
git commit -m "feat: add auto_export_library function for macOS"
```

---

### Task 2: Integrate auto-export into `_resolve_library_path` and `main()`

**Files:**
- Modify: `music_discovery.py:29-59` (`_resolve_library_path`)
- Modify: `music_discovery.py:1064-1098` (`main`)
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write failing tests for updated `_resolve_library_path`**

```python
def test_resolve_library_path_auto_exports_on_macos(tmp_path):
    """On macOS with no CLI override, should attempt auto-export first."""
    export_path = tmp_path / "Library.xml"
    export_path.write_bytes(plistlib.dumps({"Tracks": {}}))
    with patch('platform.system', return_value='Darwin'), \
         patch.object(md, 'auto_export_library', return_value=export_path) as mock_export:
        result = md._resolve_library_path(cli_override=None, cache_dir=tmp_path)
    assert result == export_path
    mock_export.assert_called_once_with(tmp_path)

def test_resolve_library_path_falls_back_on_export_failure(tmp_path):
    """If auto-export fails, fall back to default XML path detection."""
    default_xml = tmp_path / "Music" / "Music" / "Music Library.xml"
    default_xml.parent.mkdir(parents=True)
    default_xml.write_bytes(plistlib.dumps({"Tracks": {}}))
    with patch('platform.system', return_value='Darwin'), \
         patch.object(md, 'auto_export_library', return_value=None), \
         patch('pathlib.Path.home', return_value=tmp_path):
        result = md._resolve_library_path(cli_override=None, cache_dir=tmp_path)
    assert result == default_xml

def test_resolve_library_path_skips_export_with_cli_override(tmp_path):
    """CLI --library flag should skip auto-export entirely."""
    lib_path = tmp_path / "my_lib.xml"
    lib_path.write_bytes(plistlib.dumps({"Tracks": {}}))
    with patch.object(md, 'auto_export_library') as mock_export:
        result = md._resolve_library_path(cli_override=str(lib_path), cache_dir=tmp_path)
    assert result == lib_path
    mock_export.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py::test_resolve_library_path_auto_exports_on_macos tests/test_music_discovery.py::test_resolve_library_path_falls_back_on_export_failure tests/test_music_discovery.py::test_resolve_library_path_skips_export_with_cli_override -v`

Expected: FAIL — `_resolve_library_path` doesn't accept `cache_dir` param yet.

- [ ] **Step 3: Update `_resolve_library_path` to accept `cache_dir` and attempt auto-export**

Replace `_resolve_library_path` at line 30:

```python
def _resolve_library_path(cli_override=None, cache_dir=None):
    """Resolve the Music Library XML path.
    Priority: CLI flag > auto-export (macOS) > platform auto-detect.
    Returns a pathlib.Path if found, or None if not found (with helpful log message)."""
    if cli_override:
        p = pathlib.Path(cli_override).expanduser().resolve()
        if p.exists():
            return p
        log.error(f"Library file not found: {p}")
        return None

    system = platform.system()

    # macOS: try auto-export first
    if system == "Darwin" and cache_dir is not None:
        log.info("Auto-exporting Music Library...")
        exported = auto_export_library(cache_dir)
        if exported:
            log.info(f"Fresh library exported to: {exported}")
            return exported
        log.warning("Auto-export failed — falling back to existing XML.")

    if system == "Darwin":
        default = pathlib.Path.home() / "Music/Music/Music Library.xml"
        export_hint = 'Open Music.app → File → Library → Export Library…'
    elif system == "Windows":
        default = pathlib.Path.home() / "Music/iTunes/iTunes Music Library.xml"
        export_hint = 'Open iTunes → File → Library → Export Library…'
    else:
        log.error("Could not auto-detect library path on this platform.")
        log.error("Specify it manually: python music_discovery.py --library /path/to/Library.xml")
        return None

    if default.exists():
        return default

    log.error(f"Music Library not found at {default}")
    log.error(f"  {export_hint}")
    log.error("  Or specify the path manually: python music_discovery.py --library /path/to/Library.xml")
    return None
```

- [ ] **Step 4: Update `main()` to pass `cache_dir` to `_resolve_library_path`**

At `music_discovery.py:1081`, change:

```python
# old
library_path = _resolve_library_path(args.library)

# new
library_path = _resolve_library_path(args.library, cache_dir=paths["cache"].parent)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -v -k "resolve_library_path""`

Expected: PASS (new tests and existing tests that call `_resolve_library_path` without `cache_dir` still work due to default `None`).

- [ ] **Step 6: Commit**

```bash
git add music_discovery.py tests/test_music_discovery.py
git commit -m "feat: integrate auto-export into library path resolution"
```

---

### Task 3: Parse playlist data from XML

**Files:**
- Modify: `music_discovery.py` (add `parse_md_playlist` after `parse_library`)
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write failing tests for `parse_md_playlist`**

```python
SAMPLE_PLIST_WITH_PLAYLIST = {
    "Tracks": {
        "100": {"Artist": "Artist A", "Name": "Song 1", "Loved": True, "Play Count": 5},
        "101": {"Artist": "Artist B", "Name": "Song 2", "Play Count": 0},
        "102": {"Artist": "Artist B", "Name": "Song 3"},  # no Play Count = unplayed
        "103": {"Artist": "Artist C", "Name": "Song 4", "Play Count": 2},
        "104": {"Artist": "Artist D", "Name": "Song 5", "Loved": True, "Play Count": 1},
    },
    "Playlists": [
        {"Name": "Library", "Playlist Items": [
            {"Track ID": 100}, {"Track ID": 101}, {"Track ID": 102},
            {"Track ID": 103}, {"Track ID": 104},
        ]},
        {"Name": "Music Discovery", "Playlist Items": [
            {"Track ID": 101}, {"Track ID": 102}, {"Track ID": 103},
        ]},
    ],
}

def test_parse_md_playlist_finds_tracks():
    path = write_temp_plist(SAMPLE_PLIST_WITH_PLAYLIST)
    result = md.parse_md_playlist(path)
    assert result is not None
    artists, total, unplayed = result
    assert total == 3
    assert "artist b" in artists
    assert "artist c" in artists

def test_parse_md_playlist_counts_unplayed():
    path = write_temp_plist(SAMPLE_PLIST_WITH_PLAYLIST)
    result = md.parse_md_playlist(path)
    artists, total, unplayed = result
    # Track 101 has Play Count 0, Track 102 has no Play Count key -> both unplayed
    assert unplayed == 2

def test_parse_md_playlist_returns_none_when_missing():
    data = {"Tracks": {}, "Playlists": [{"Name": "Other"}]}
    path = write_temp_plist(data)
    result = md.parse_md_playlist(path)
    assert result is None

def test_parse_md_playlist_returns_none_when_empty():
    data = {"Tracks": {}, "Playlists": [
        {"Name": "Music Discovery", "Playlist Items": []}
    ]}
    path = write_temp_plist(data)
    result = md.parse_md_playlist(path)
    assert result is None

def test_parse_md_playlist_artist_names_lowercased():
    path = write_temp_plist(SAMPLE_PLIST_WITH_PLAYLIST)
    result = md.parse_md_playlist(path)
    artists, _, _ = result
    for name in artists:
        assert name == name.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -v -k "parse_md_playlist"`

Expected: FAIL — function doesn't exist.

- [ ] **Step 3: Implement `parse_md_playlist`**

Add after `parse_library` (around line 367):

```python
def parse_md_playlist(xml_path):
    """Find the 'Music Discovery' playlist in the XML and return audit data.
    Returns (artist_set, total_tracks, unplayed_count) or None if no MD playlist.
    artist_set contains lowercased artist names from the playlist.
    A track is 'unplayed' if Play Count is 0 or absent."""
    try:
        with open(xml_path, "rb") as f:
            library = plistlib.load(f)
    except Exception:
        return None

    tracks_dict = library.get("Tracks", {})
    playlists = library.get("Playlists", [])

    # Find the Music Discovery playlist
    md_playlist = None
    for pl in playlists:
        if pl.get("Name") == "Music Discovery":
            md_playlist = pl
            break
    if md_playlist is None:
        return None

    items = md_playlist.get("Playlist Items", [])
    if not items:
        return None

    artists = set()
    unplayed = 0
    total = 0
    for item in items:
        track_id = str(item.get("Track ID", ""))
        track = tracks_dict.get(track_id)
        if track is None:
            continue
        total += 1
        artist = track.get("Artist", "").strip().lower()
        if artist:
            artists.add(artist)
        if track.get("Play Count", 0) == 0:
            unplayed += 1

    if total == 0:
        return None

    return artists, total, unplayed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -v -k "parse_md_playlist"`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add music_discovery.py tests/test_music_discovery.py
git commit -m "feat: add parse_md_playlist to extract playlist audit data from XML"
```

---

### Task 4: Implement `audit_md_playlist` (blocklist rejected artists)

**Files:**
- Modify: `music_discovery.py` (add `audit_md_playlist` after `parse_md_playlist`)
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write failing tests for `audit_md_playlist`**

```python
def test_audit_blocklists_unfavorited_artists():
    """Artists in MD playlist with no loved tracks should be blocklisted."""
    playlist_artists = {"artist b", "artist c"}
    library_artists = {"artist a": 3, "artist c": 1}  # artist c is loved, b is not
    existing_blocklist = set()
    result = md.audit_md_playlist(
        playlist_artists, library_artists, existing_blocklist,
        total=10, unplayed=2, interactive=False,
    )
    assert "artist b" in result
    assert "artist c" not in result

def test_audit_skips_already_blocklisted():
    """Artists already in the blocklist should not be re-added."""
    playlist_artists = {"artist b", "artist c"}
    library_artists = {}
    existing_blocklist = {"artist b"}
    result = md.audit_md_playlist(
        playlist_artists, library_artists, existing_blocklist,
        total=10, unplayed=2, interactive=False,
    )
    assert "artist b" not in result
    assert "artist c" in result

def test_audit_prompts_when_over_25_percent_unplayed(monkeypatch):
    """If >25% unplayed and user says 'n', return empty set."""
    monkeypatch.setattr('builtins.input', lambda _: 'n')
    playlist_artists = {"artist b"}
    library_artists = {}
    result = md.audit_md_playlist(
        playlist_artists, library_artists, set(),
        total=10, unplayed=5, interactive=True,
    )
    assert result == set()

def test_audit_prompts_when_over_25_percent_user_says_yes(monkeypatch):
    """If >25% unplayed and user says 'y', proceed with blocklisting."""
    monkeypatch.setattr('builtins.input', lambda _: 'y')
    playlist_artists = {"artist b"}
    library_artists = {}
    result = md.audit_md_playlist(
        playlist_artists, library_artists, set(),
        total=10, unplayed=5, interactive=True,
    )
    assert "artist b" in result

def test_audit_no_prompt_when_under_25_percent():
    """If <=25% unplayed, no prompt — just blocklist."""
    playlist_artists = {"artist b"}
    library_artists = {}
    result = md.audit_md_playlist(
        playlist_artists, library_artists, set(),
        total=10, unplayed=2, interactive=True,
    )
    assert "artist b" in result

def test_audit_skips_in_non_interactive_mode_when_over_25():
    """Non-interactive + >25% unplayed → safe default: skip blocklisting."""
    playlist_artists = {"artist b"}
    library_artists = {}
    result = md.audit_md_playlist(
        playlist_artists, library_artists, set(),
        total=10, unplayed=5, interactive=False,
    )
    assert result == set()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -v -k "audit"`

Expected: FAIL — function doesn't exist.

- [ ] **Step 3: Implement `audit_md_playlist`**

Add after `parse_md_playlist`:

```python
def audit_md_playlist(playlist_artists, library_artists, existing_blocklist,
                      total, unplayed, interactive=True):
    """Check MD playlist artists against loved artists. Return set of artists to blocklist.
    - playlist_artists: set of lowercased artist names from the MD playlist.
    - library_artists: dict {artist: loved_count} from parse_library.
    - existing_blocklist: set of already-blocklisted names (won't be re-added).
    - total: total tracks in MD playlist.
    - unplayed: count of tracks with play count 0.
    - interactive: if True and >25% unplayed, prompt user. If False, skip blocklisting.
    Returns set of new artist names to add to blocklist."""
    unplayed_pct = (unplayed / total) * 100 if total > 0 else 0
    log.info(f"Music Discovery playlist: {total} tracks, {unplayed} unplayed "
             f"({unplayed_pct:.0f}%).")

    if unplayed_pct > 25:
        if not interactive:
            log.info("Non-interactive mode — skipping playlist audit blocklisting.")
            return set()
        answer = input(
            f"Over 25% of your Music Discovery playlist is unplayed "
            f"({unplayed}/{total}). Blocklist unheard artists anyway? (y/n): "
        ).strip().lower()
        if answer != 'y':
            log.info("Skipping playlist audit blocklisting.")
            return set()

    # Identify rejected artists: in playlist but no loved tracks in library
    rejected = set()
    for artist in playlist_artists:
        if artist in library_artists:
            continue  # user loved at least one track by this artist
        if artist in existing_blocklist:
            continue  # already blocked
        rejected.add(artist)

    if rejected:
        log.info(f"Blocklisting {len(rejected)} rejected artist(s) from playlist audit: "
                 f"{sorted(rejected)}")
    else:
        log.info("No new artists to blocklist from playlist audit.")

    return rejected
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -v -k "audit"`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add music_discovery.py tests/test_music_discovery.py
git commit -m "feat: add audit_md_playlist to blocklist rejected artists"
```

---

### Task 5: Wire everything into `main()`

**Files:**
- Modify: `music_discovery.py:1064-1200` (`main`)
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write an integration test for the audit flow in `main()`**

```python
def test_main_runs_playlist_audit(tmp_path, monkeypatch):
    """Verify main() calls audit and adds rejected artists to blocklist."""
    # Build a plist with an MD playlist containing an unloved artist
    plist_data = {
        "Tracks": {
            "1": {"Artist": "Loved One", "Loved": True, "Favorited": True},
            "2": {"Artist": "Rejected", "Name": "Song", "Play Count": 3},
        },
        "Playlists": [
            {"Name": "Music Discovery", "Playlist Items": [{"Track ID": 2}]},
        ],
    }
    lib_path = tmp_path / "Library.xml"
    lib_path.write_bytes(plistlib.dumps(plist_data))

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    # Patch out everything that hits the network or filesystem defaults
    monkeypatch.setattr('sys.argv', ['music_discovery.py', '--library', str(lib_path)])
    monkeypatch.setenv('CACHE_DIR', str(cache_dir))
    monkeypatch.setenv('OUTPUT_DIR', str(cache_dir))
    monkeypatch.setenv('LASTFM_API_KEY', 'dummy_key_for_test_00000000000')
    # Skip interactive API key prompt
    monkeypatch.setattr(md, 'prompt_for_api_key', lambda *a, **kw: None)
    # Provide a scraper that returns no similar artists (fast)
    monkeypatch.setattr(md, 'detect_scraper', lambda: lambda artist: {})
    # Skip network calls for filter data
    monkeypatch.setattr(md, 'fetch_filter_data', lambda *a, **kw: {})

    md.main()

    # Check that 'rejected' was added to blocklist_cache.json
    import json
    blocklist_path = cache_dir / "blocklist_cache.json"
    assert blocklist_path.exists(), "blocklist_cache.json should have been created"
    data = json.loads(blocklist_path.read_text())
    assert "rejected" in data.get("blocked", [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py::test_main_runs_playlist_audit -v`

Expected: FAIL — `main()` doesn't call the audit functions yet.

- [ ] **Step 3: Wire audit into `main()`**

In `main()`, move the blocklist loading to happen **before** the audit so we can pass the existing blocklist. After `parse_library` (line ~1097), restructure the flow:

```python
    # ── 2. Load caches ─────────────────────────────────────
    cache        = load_cache(paths["cache"])
    filter_cache = load_cache(paths["filter_cache"]) if api_key else {}
    file_blocklist = load_blocklist(paths["blocklist"])
    user_blocklist_path = pathlib.Path(__file__).parent / "blocklist.txt"
    user_blocklist = load_user_blocklist(user_blocklist_path)
    file_blocklist |= user_blocklist

    already_done = len(cache)
    if already_done:
        log.info(f"Loaded scrape cache: {already_done} artists.")

    # ── 2b. Audit previous Music Discovery playlist ────────
    md_audit = parse_md_playlist(library_path)
    if md_audit is not None:
        md_artists, md_total, md_unplayed = md_audit
        interactive = sys.stdin.isatty()
        newly_rejected = audit_md_playlist(
            md_artists, library_artists, file_blocklist,
            total=md_total, unplayed=md_unplayed, interactive=interactive,
        )
        if newly_rejected:
            file_blocklist |= newly_rejected
            save_blocklist(file_blocklist, paths["blocklist"])
            log.info(f"Saved {len(newly_rejected)} rejected artist(s) to blocklist.")
```

Note: `load_blocklist` is now called unconditionally (was previously guarded by `if api_key`). This is safe — it just returns `set()` if the file doesn't exist. Loading it always ensures the audit doesn't cause data loss by overwriting existing entries.

- [ ] **Step 4: Run the full test suite**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -v`

Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add music_discovery.py tests/test_music_discovery.py
git commit -m "feat: wire playlist audit into main() flow"
```

---

### Task 6: Manual smoke test with live data

**Files:** None (read-only verification)

- [ ] **Step 1: Run discovery without `--library` flag to test auto-export**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python music_discovery.py 2>&1 | head -20`

Expected: Should see "Auto-exporting Music Library..." followed by "Fresh library exported to: ..." and then normal discovery output.

- [ ] **Step 2: Verify the export was created**

Run: `ls -lh ~/.cache/music_discovery/Library.xml`

Expected: A fresh file with today's date.

- [ ] **Step 3: Verify `--library` override still works**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python music_discovery.py --library ~/Music/Music/"Music Library.xml" 2>&1 | head -5`

Expected: Should NOT see "Auto-exporting" message. Should read the specified file directly.

- [ ] **Step 4: Commit any fixes if needed**
