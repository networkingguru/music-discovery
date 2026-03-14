# Documentation Sanitization & Distribution Readiness — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare all documentation and code for public distribution — fix URLs, remove Linux references, add safety warnings, extract personal blocklist entries, and enable Windows playlist generation.

**Architecture:** Two-phase approach. Phase 1 edits four documentation files (README, CHANGELOG, user guide, how-it-works). Phase 2 makes three code changes (blocklist extraction, Windows XML playlist, URL fix) with corresponding tests and CHANGELOG entries.

**Tech Stack:** Python 3.9+, pytest, plistlib (stdlib)

**Spec:** `docs/superpowers/specs/2026-03-14-docs-sanitization-design.md`

---

## Chunk 1: Documentation Changes

### Task 1: Update README.md

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Fix GitHub URL in clone command**

Change line 10:
```
git clone https://github.com/brianhill/music-discovery.git
```
to:
```
git clone https://github.com/networkingguru/music-discovery.git
```

- [ ] **Step 2: Update requirements section**

Replace lines 19-22:
```markdown
- **Python 3.9+**
- **macOS or Windows** (Linux users: specify library path with `--library`)
- **Apple Music or iTunes library** exported as XML
- **Last.fm API key** (optional, free) — improves results by filtering out well-known artists
```
with:
```markdown
- **Python 3.9+**
- **macOS or Windows**
- **Apple Music or iTunes library** exported as XML, with loved or favorited tracks (the tool discovers new artists based on artists you've loved — without any loved or favorited tracks, it has nothing to work with)
- **Last.fm API key** (optional, free) — improves results by filtering out well-known artists
- **Apple Music subscription** (recommended for playlist building) — without one, adding tracks to your library may purchase them individually instead of streaming. See the warning in Usage below.
```

- [ ] **Step 3: Update usage section**

Replace lines 33-34:
```markdown
# Discovery + build an Apple Music playlist (macOS only)
python music_discovery.py --playlist
```
with:
```markdown
# Discovery + build an Apple Music playlist
python music_discovery.py --playlist
```

Add after line 35 (after the closing ``` of the code block):
```markdown

> **Important:** Playlist building adds tracks to your Apple Music library. Without an active Apple Music subscription, this may purchase individual tracks instead of streaming them. The author is not responsible for any charges incurred. Use at your own risk.
```

- [ ] **Step 4: Replace platform table**

Replace lines 39-45:
```markdown
| Feature | macOS | Windows | Linux |
|---------|-------|---------|-------|
| Artist discovery | Yes | Yes | Yes* |
| Last.fm filtering | Yes | Yes | Yes |
| Playlist building | Yes | No | No |

\*Linux users must export their library XML and specify the path with `--library`.
```
with:
```markdown
| Feature | macOS | Windows |
|---------|-------|---------|
| Artist discovery | Yes | Yes |
| Last.fm filtering | Yes | Yes |
| Playlist building | Yes (native) | Yes (XML import) |
```

- [ ] **Step 5: Update description**

Replace line 5:
```markdown
This tool reads loved/favorited artists from your Apple Music (or iTunes) library, finds similar artists via [music-map.com](https://www.music-map.com/), scores them by proximity, and filters out well-known artists so only genuine discoveries appear. Optionally builds an Apple Music playlist with top tracks from your discoveries.
```
with:
```markdown
This tool reads artists from tracks you've marked as **Loved** or **Favorited** in your Apple Music (or iTunes) library, finds similar artists via [music-map.com](https://www.music-map.com/), scores them by proximity, and filters out well-known artists so only genuine discoveries appear. Optionally builds an Apple Music playlist with top tracks from your discoveries.
```

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs: update README — fix URLs, remove Linux, add warnings"
```

---

### Task 2: Update CHANGELOG.md

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Fix monster playlist description**

Replace on line 66:
```
the playlist had thousands of tracks
```
with:
```
the playlist had 1.3 million tracks
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: fix monster playlist scale in changelog (1.3M tracks)"
```

---

### Task 3: Update user-guide.md

**Files:**
- Modify: `docs/user-guide.md`

- [ ] **Step 1: Fix GitHub URLs**

Replace line 45:
```
git clone https://github.com/brianhill/music-discovery.git
```
with:
```
git clone https://github.com/networkingguru/music-discovery.git
```

Replace line 204:
```markdown
If you run into an issue not covered here, check the project's GitHub page or open an issue at [github.com/brianhill/music-discovery](https://github.com/brianhill/music-discovery).
```
with:
```markdown
If you run into an issue not covered here, check the project's GitHub page or open an issue at [github.com/networkingguru/music-discovery](https://github.com/networkingguru/music-discovery).
```

- [ ] **Step 2: Add loved/favorited prerequisite**

After the "Default file locations" subsection (after line 36), add a new subsection:

```markdown

### Loved or Favorited tracks required

The script identifies your favorite artists by looking for tracks you have marked as **Loved** or **Favorited** in your library. If you don't have any loved or favorited tracks, the tool has nothing to work with and will produce no results.

To love a track in Music.app: right-click a song → **Love**. To favorite: click the star icon (if enabled).
```

- [ ] **Step 3: Update beachball troubleshooting section**

Replace lines 168-170:
```markdown
### Music.app beachballs (spinning wheel) during playlist build

This can happen if Music.app gets overloaded. **Force-quit Music.app** (right-click its Dock icon → Force Quit), wait a minute, then re-run the script. Do not attempt to retry while it's unresponsive.
```
with:
```markdown
### Music.app beachballs (spinning wheel) during playlist build

This can happen if Music.app gets overloaded. **Force-quit Music.app** (right-click its Dock icon → Force Quit). You may need to **reboot your Mac** to recover — Music.app can get stuck on "Loading Library" indefinitely after a force-quit. Do not attempt to retry while it's unresponsive.
```

- [ ] **Step 4: Add playlist warnings**

Replace lines 112-131 (the entire "5. Building a Playlist" section content):
```markdown
## 5. Building a Playlist (macOS only)

If you're on a Mac, you can have the script automatically create a playlist in Music.app:

```bash
python music_discovery.py --playlist
```

This will:

1. Take the top 50 discovered artists
2. Pull top tracks for each from your library (if you have them) or from iTunes Search
3. Create a playlist called **"Music Discovery"** in Music.app
4. Populate it with up to **500 tracks**

**A few things to expect:**
- You may hear brief audio playback during the process — this is normal. It's how tracks get added via AppleScript.
- The playlist is cleared and rebuilt from scratch each time you run with `--playlist`.
- Make sure Music.app is open before running.
```
with:
```markdown
## 5. Building a Playlist

> **Important — Please read before using `--playlist`:**
>
> The playlist generator is complex. It bridges three separate Apple APIs (iTunes Search, MediaPlayer, and AppleScript) and can cause Music.app to become unresponsive. See the Troubleshooting section for recovery steps if this happens.
>
> **An active Apple Music subscription is required.** Without one, the process may **purchase individual tracks** instead of streaming them. This could result in significant unexpected charges. The author is not responsible for any purchases incurred. **Use at your own risk.**

### macOS

On a Mac, the script automatically creates a playlist in Music.app:

```bash
python music_discovery.py --playlist
```

This will:

1. Take the top 50 discovered artists
2. Pull top tracks for each from your library (if you have them) or from iTunes Search
3. Create a playlist called **"Music Discovery"** in Music.app
4. Populate it with up to **500 tracks**

**A few things to expect:**
- You may hear brief audio playback during the process — this is normal. It's how tracks get added via AppleScript.
- The playlist is cleared and rebuilt from scratch each time you run with `--playlist`.
- Make sure Music.app is open before running.

### Windows

On Windows, the script generates an XML playlist file that you can import into iTunes:

```bash
python music_discovery.py --playlist
```

This will create a file at `~/.cache/music_discovery/Music Discovery.xml`. To use it:

1. Open iTunes
2. Go to **File → Library → Import Playlist...**
3. Select the generated XML file
```

- [ ] **Step 5: Verify no Linux mentions remain**

Confirm there are no Linux references in user-guide.md. The default paths table (lines 31-34) already only lists macOS and Windows. No action needed unless references are found.

- [ ] **Step 6: Commit**

```bash
git add docs/user-guide.md
git commit -m "docs: update user guide — warnings, loved/fav prereq, beachball reboot"
```

---

### Task 4: Update how-it-works.md

**Files:**
- Modify: `docs/how-it-works.md`

- [ ] **Step 1: Add Layer 3 purchase warning**

Replace lines 89-91:
```markdown
### Layer 3 — AppleScript

Once the track is playing and visible in Music.app, an AppleScript grabs the current track object, adds it to the library, and then adds it to the target playlist.
```
with:
```markdown
### Layer 3 — AppleScript

Once the track is playing and visible in Music.app, an AppleScript grabs the current track object, adds it to the library, and then adds it to the target playlist.

> **Warning:** The "add to library" step (`duplicate ct to source "Library"`) may **purchase the track** if you do not have an active Apple Music subscription. When running across dozens of artists and hundreds of tracks, this could result in very significant charges (potentially $150+). An active Apple Music subscription is strongly recommended before using `--playlist`.
```

- [ ] **Step 2: Clarify oversized playlist handling**

Replace line 98:
```markdown
- **Oversized playlist handling** — if an existing playlist exceeds the cap, it is deleted and recreated from scratch.
```
with:
```markdown
- **Oversized playlist handling** — if the existing **Music Discovery** playlist exceeds the cap, it is deleted and recreated from scratch. This check applies only to the Music Discovery playlist — no other playlists are affected.
```

- [ ] **Step 3: Update playlist building intro and add Windows section**

Replace lines 77-79:
```markdown
## 5. Playlist Building

Building a playlist requires bridging three separate Apple APIs because no single API can both find a track and add it to a user library playlist.
```
with:
```markdown
## 5. Playlist Building

On macOS, building a playlist requires bridging three separate Apple APIs because no single API can both find a track and add it to a user library playlist. On Windows, the script generates an XML playlist file that can be imported into iTunes (see XML Playlist Export below).
```

After the Safeguards subsection (after line 99, after the closing `---`), add a new subsection:

```markdown

### XML Playlist Export (Windows)

On Windows, the AppleScript/MediaPlayer pipeline is unavailable. Instead, the script:

1. Fetches top tracks for each discovered artist via the iTunes Search API and Last.fm
2. Generates an Apple-compatible XML plist file (`Music Discovery.xml`) containing track metadata
3. The user imports this file into iTunes via **File → Library → Import Playlist**

The XML export uses Python's built-in `plistlib` module and produces a valid Apple XML plist on any platform. This is also used as a fallback on macOS when the native pipeline fails.
```

- [ ] **Step 4: Remove Linux from UUID table**

Replace lines 122-127:
```markdown
### Platform UUID sources

| Platform | Source |
|---|---|
| macOS | `IOPlatformUUID` (via `ioreg`) |
| Windows | `HKLM\SOFTWARE\Microsoft\Cryptography\MachineGuid` |
| Linux | `/etc/machine-id` |
```
with:
```markdown
### Platform UUID sources

| Platform | Source |
|---|---|
| macOS | `IOPlatformUUID` (via `ioreg`) |
| Windows | `HKLM\SOFTWARE\Microsoft\Cryptography\MachineGuid` |
```

- [ ] **Step 5: Commit**

```bash
git add docs/how-it-works.md
git commit -m "docs: update how-it-works — purchase warning, playlist clarifications"
```

---

## Chunk 2: Code Changes

### Task 5: Extract blocklist to user-editable file

**Files:**
- Modify: `music_discovery.py:79-93` (trim ARTIST_BLOCKLIST)
- Modify: `music_discovery.py:1092` (load user blocklist)
- Create: `blocklist.txt` (personal entries, will be .gitignored)
- Modify: `.gitignore` (add blocklist.txt)
- Modify: `tests/test_music_discovery.py` (add tests for load_user_blocklist)

- [ ] **Step 1: Write failing test for load_user_blocklist**

Add to `tests/test_music_discovery.py`:

```python
# ── load_user_blocklist ───────────────────────────────────

def test_load_user_blocklist_reads_names(tmp_path):
    """Reads one name per line, lowercased, ignoring blanks and comments."""
    f = tmp_path / "blocklist.txt"
    f.write_text("Hall and Oates\n# a comment\n\nBlondie\n")
    result = md.load_user_blocklist(f)
    assert result == {"hall and oates", "blondie"}


def test_load_user_blocklist_missing_file(tmp_path):
    """Returns empty set when file does not exist."""
    result = md.load_user_blocklist(tmp_path / "nope.txt")
    assert result == set()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py::test_load_user_blocklist_reads_names tests/test_music_discovery.py::test_load_user_blocklist_missing_file -v`
Expected: FAIL with `AttributeError: module has no attribute 'load_user_blocklist'`

- [ ] **Step 3: Implement load_user_blocklist**

Add after `save_blocklist()` (after line 497 in `music_discovery.py`):

```python
def load_user_blocklist(path):
    """Load a plain-text blocklist file (one artist per line).
    Blank lines and lines starting with # are ignored.
    Names are lowercased for case-insensitive matching.
    Returns an empty set if file does not exist."""
    path = pathlib.Path(path)
    if not path.exists():
        return set()
    names = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                names.add(line.lower())
    return names
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py::test_load_user_blocklist_reads_names tests/test_music_discovery.py::test_load_user_blocklist_missing_file -v`
Expected: PASS

- [ ] **Step 5: Trim ARTIST_BLOCKLIST to non-artist entries only**

Replace lines 79-93:
```python
ARTIST_BLOCKLIST = {
    # Classic artists with missing debut year in MusicBrainz
    "hall and oates", "cat stevens", "neil young & crazy horse",
    "jackson 5", "the jackson five", "bob seger and the silver bullet band",
    "pretenders", "eric burdon & war", "destinys child",
    "jimi hendrix and the experience",
    # Classic artists with wrong/implausibly low Last.fm listener counts
    "cars", "reo speedwagon", "reo speed wagon",
    "emerson lake and palmer", "mister mister",
    "blondie", "ultravox", "uriah heep", "j. j. cale",
    # Classic artists whose Last.fm API call cached as {} (transient failure fallback)
    "christina aguilera",
    # Non-artists scraped from music-map.com (song titles, genres, etc.)
    "let her go", "say something", "riptide", "classic rock",
}
```
with:
```python
ARTIST_BLOCKLIST = {
    # Non-artists scraped from music-map.com (song titles, genres, etc.)
    "let her go", "say something", "riptide", "classic rock",
}
# User-managed blocklist: add artist names to blocklist.txt in the project root.
# See blocklist.txt for format details.
```

- [ ] **Step 6: Create blocklist.txt with personal entries**

Create `blocklist.txt` in the project root:

```
# Artist Blocklist — Music Discovery
# One artist name per line (case-insensitive). Blank lines and # comments are ignored.
# Add artists here that slip through the automated filters.
# This file is .gitignored — it won't be committed to the repo.

# Classic artists with missing debut year in MusicBrainz
hall and oates
cat stevens
neil young & crazy horse
jackson 5
the jackson five
bob seger and the silver bullet band
pretenders
eric burdon & war
destinys child
jimi hendrix and the experience

# Classic artists with wrong/implausibly low Last.fm listener counts
cars
reo speedwagon
reo speed wagon
emerson lake and palmer
mister mister
blondie
ultravox
uriah heep
j. j. cale

# Transient Last.fm API failure
christina aguilera
```

- [ ] **Step 7: Add blocklist.txt to .gitignore**

Add `blocklist.txt` to `.gitignore`.

- [ ] **Step 8: Integrate load_user_blocklist in main()**

In `music_discovery.py`, after line 1092 (`file_blocklist = load_blocklist(paths["blocklist"]) if api_key else set()`), add:

```python
    user_blocklist_path = pathlib.Path(__file__).parent / "blocklist.txt"
    user_blocklist = load_user_blocklist(user_blocklist_path)
    file_blocklist |= user_blocklist
```

Also insert a new line between the existing dedup lines (lines 1144-1145) to exclude user blocklist entries. The existing two lines are:
```python
        new_blocked -= ARTIST_BLOCKLIST  # don't duplicate hardcoded entries
        new_blocked -= file_blocklist    # don't re-add already-known entries
```
Add `new_blocked -= user_blocklist` between them so the result is:
```python
        new_blocked -= ARTIST_BLOCKLIST  # don't duplicate hardcoded entries
        new_blocked -= user_blocklist    # don't duplicate user blocklist entries
        new_blocked -= file_blocklist    # don't re-add already-known entries
```

Note: `user_blocklist` must be accessible at this scope. Since it's set earlier in `main()`, this works.

- [ ] **Step 9: Run full test suite**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 10: Commit**

```bash
git add music_discovery.py tests/test_music_discovery.py .gitignore
git commit -m "feat: extract personal blocklist to user-editable blocklist.txt"
```

---

### Task 6: Enable Windows `--playlist` via XML export

**Files:**
- Modify: `music_discovery.py:1164-1177` (platform branch in main)

- [ ] **Step 1: Replace the platform guard with a branch**

Replace lines 1165-1177:
```python
    if args.playlist:
        if platform.system() != "Darwin":
            log.info("\nPlaylist building requires macOS with Apple Music.")
            log.info("Skipping — discovery results are still saved.")
        elif not api_key:
            log.info("\nPlaylist building requires a Last.fm API key. Skipping.")
        else:
            success, all_tracks = build_playlist(ranked, api_key, paths)
            if not success and all_tracks:
                log.info("\nFalling back to XML playlist export...")
                write_playlist_xml(all_tracks, paths["playlist_xml"])
                log.info(f"Import {paths['playlist_xml']} in Music.app via "
                         f"File → Library → Import Playlist.")
```
with:
```python
    if args.playlist:
        if not api_key:
            log.info("\nPlaylist building requires a Last.fm API key. Skipping.")
        elif platform.system() == "Darwin":
            success, all_tracks = build_playlist(ranked, api_key, paths)
            if not success and all_tracks:
                log.info("\nFalling back to XML playlist export...")
                write_playlist_xml(all_tracks, paths["playlist_xml"])
                log.info(f"Import {paths['playlist_xml']} in Music.app via "
                         f"File → Library → Import Playlist.")
        else:
            # Windows (or other non-macOS): XML-only export
            log.info("\nBuilding XML playlist for import into iTunes...")
            _, all_tracks = build_playlist(ranked, api_key, paths,
                                           xml_only=True)
            if all_tracks:
                write_playlist_xml(all_tracks, paths["playlist_xml"])
                log.info(f"\nPlaylist saved to: {paths['playlist_xml']}")
                log.info("Import it in iTunes via File → Library → Import Playlist.")
            else:
                log.info("No tracks found — skipping playlist generation.")
```

- [ ] **Step 2: Write failing test for xml_only mode**

Add to `tests/test_music_discovery.py`:

```python
def test_build_playlist_xml_only_skips_setup(monkeypatch, tmp_path):
    """xml_only=True returns tracks without calling setup_playlist."""
    paths = {
        "top_tracks": tmp_path / "top_tracks.json",
        "playlist_xml": tmp_path / "playlist.xml",
    }
    paths["top_tracks"].write_text("{}")
    ranked = [(5.0, "test artist")]

    # Mock fetch_top_tracks to return a track
    monkeypatch.setattr(md, "fetch_top_tracks", lambda *a, **kw: [{"name": "Song", "artist": "Test Artist"}])
    monkeypatch.setattr(md, "save_cache", lambda *a: None)

    # setup_playlist should NOT be called — if it is, fail
    monkeypatch.setattr(md, "setup_playlist", lambda: (_ for _ in ()).throw(AssertionError("setup_playlist should not be called")))

    success, tracks = md.build_playlist(ranked, "fake-key", paths, xml_only=True)
    assert success is True
    assert len(tracks) >= 1
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py::test_build_playlist_xml_only_skips_setup -v`
Expected: FAIL (xml_only parameter doesn't exist yet)

- [ ] **Step 4: Add xml_only parameter to build_playlist**

In `build_playlist()` (line 909), change the signature from:
```python
def build_playlist(ranked, api_key, paths):
```
to:
```python
def build_playlist(ranked, api_key, paths, xml_only=False):
```

Then before line 948 (the `# ── Stage 1: setup playlist` comment), add:
```python
    if xml_only:
        return True, all_tracks

```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py::test_build_playlist_xml_only_skips_setup -v`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add music_discovery.py tests/test_music_discovery.py
git commit -m "feat: enable --playlist on Windows via XML export"
```

---

### Task 7: Fix GitHub URL in code and add CHANGELOG entries

**Files:**
- Modify: `music_discovery.py:75` (MB_USER_AGENT URL)
- Modify: `CHANGELOG.md` (new entries)

- [ ] **Step 1: Fix MB_USER_AGENT URL**

Replace line 75:
```python
MB_USER_AGENT       = "MusicDiscoveryTool/1.0 (https://github.com/brianhill/music-discovery)"
```
with:
```python
MB_USER_AGENT       = "MusicDiscoveryTool/1.0 (https://github.com/networkingguru/music-discovery)"
```

- [ ] **Step 2: Add CHANGELOG entries for code changes**

Add after line 2 (after `# Changelog`), before the existing first entry:

```markdown

## 2026-03-14 — Distribution Sanitization
- Personal artist blocklist entries moved to user-editable `blocklist.txt` (`.gitignore`d)
- `--playlist` now works on Windows via XML export (import in iTunes via File → Library → Import Playlist)
- Fixed GitHub URLs throughout documentation and code
```

- [ ] **Step 3: Run full test suite**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add music_discovery.py CHANGELOG.md
git commit -m "chore: fix GitHub URL in user-agent, add changelog entries"
```
