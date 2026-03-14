# Distribution & Documentation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare the Music Discovery repo for public GitHub release — cross-platform support, optional Last.fm, and comprehensive documentation.

**Architecture:** Three surgical code changes to `music_discovery.py` (library path auto-detect, optional Last.fm, playlist platform guard), then five documentation files (README, user guide, technical overview, clever bits, changelog). Repo cleanup (requirements.txt, .gitignore, MB_USER_AGENT).

**Tech Stack:** Python stdlib (`platform`, `argparse`), existing dependencies unchanged.

**Spec:** `docs/superpowers/specs/2026-03-13-distribution-design.md`

---

## Chunk 1: Code Changes

### Task 1: Add `_resolve_library_path()` with tests

**Files:**
- Modify: `music_discovery.py:29` (replace `LIBRARY_PATH` constant)
- Modify: `music_discovery.py:1017-1034` (update `main()` to use new function)
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_music_discovery.py`:

```python
def test_resolve_library_path_cli_override(tmp_path):
    """CLI --library flag takes precedence over auto-detect."""
    fake_xml = tmp_path / "MyLibrary.xml"
    fake_xml.write_bytes(b"<plist></plist>")
    result = md._resolve_library_path(str(fake_xml))
    assert result == fake_xml


def test_resolve_library_path_cli_override_missing():
    """CLI --library with nonexistent file returns None."""
    result = md._resolve_library_path("/nonexistent/library.xml")
    assert result is None


def test_resolve_library_path_auto_detect(monkeypatch):
    """Auto-detect returns a Path based on platform."""
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    result = md._resolve_library_path(None)
    # Should return the macOS default path (may not exist, that's OK)
    assert "Music" in str(result) or result is None


def test_resolve_library_path_windows(monkeypatch):
    """Auto-detect on Windows returns iTunes path."""
    monkeypatch.setattr("platform.system", lambda: "Windows")
    result = md._resolve_library_path(None)
    assert result is None or "iTunes" in str(result)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py::test_resolve_library_path_cli_override -v`
Expected: FAIL with `AttributeError: module 'music_discovery' has no attribute '_resolve_library_path'`

- [ ] **Step 3: Add `import platform` and implement `_resolve_library_path()`**

In `music_discovery.py`, add `import platform` to the imports section (after `import pathlib` on line 20).

Replace the `LIBRARY_PATH` constant (line 29) with:

```python
def _resolve_library_path(cli_override=None):
    """Resolve the Music Library XML path.
    Priority: CLI flag > platform auto-detect.
    Returns a pathlib.Path if found, or None if not found (with helpful log message)."""
    if cli_override:
        p = pathlib.Path(cli_override).expanduser().resolve()
        if p.exists():
            return p
        log.error(f"Library file not found: {p}")
        return None

    system = platform.system()
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

- [ ] **Step 4: Update `main()` to use `_resolve_library_path()` and add `--library` arg**

In `main()`, update the argparse section and library loading:

```python
def main():
    # ── 0. Load config ─────────────────────────────────────
    parser = argparse.ArgumentParser(description="Apple Music Discovery Tool")
    parser.add_argument(
        "--playlist", action="store_true",
        help="After discovery, fetch top tracks and build an Apple Music playlist.",
    )
    parser.add_argument(
        "--library", type=str, default=None,
        help="Path to Music Library XML file (auto-detected if omitted).",
    )
    args = parser.parse_args()

    load_dotenv()
    paths = _build_paths()

    # ── 1. Parse library ───────────────────────────────────
    library_path = _resolve_library_path(args.library)
    if library_path is None:
        return

    log.info(f"Reading library: {library_path}")
```

Remove the old `LIBRARY_PATH` references in the rest of `main()` — replace `LIBRARY_PATH` with `library_path` on the `parse_library()` call (currently line 1042).

- [ ] **Step 5: Run all tests**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
cd "/Users/brianhill/Scripts/Music Discovery"
git add music_discovery.py tests/test_music_discovery.py
git commit -m "feat: add --library CLI flag and cross-platform library auto-detect"
```

---

### Task 2: Make Last.fm optional (skip with Enter)

**Files:**
- Modify: `music_discovery.py:243-289` (update `prompt_for_api_key()`)
- Modify: `music_discovery.py:1036-1041` (update `main()` API key flow)
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_music_discovery.py`:

```python
def test_prompt_for_api_key_skip(monkeypatch):
    """Pressing Enter (empty input) returns None immediately."""
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "")
    result = md.prompt_for_api_key(env_path="/tmp/fake.env")
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py::test_prompt_for_api_key_skip -v`
Expected: FAIL (currently empty input counts as invalid attempt, retries 3 times).

- [ ] **Step 3: Modify `prompt_for_api_key()` to allow skip**

In `prompt_for_api_key()`, add the skip hint to the intro text and check for empty input before validation:

```python
def prompt_for_api_key(env_path=None):
    """Interactive first-run prompt for the Last.fm API key.
    Validates, encrypts (if possible), writes to .env, returns plain key.
    Returns None if user skips (empty input) or after 3 failed attempts."""
    log.info("\n" + "=" * 60)
    log.info("  Last.fm API Key Setup")
    log.info("=" * 60)
    log.info("\nThis tool uses the Last.fm API to filter and enrich results.")
    log.info("You need a free API key for the best experience.\n")
    log.info("  1. Go to: https://www.last.fm/api/account/create")
    log.info("  2. Log in (or create a free account)")
    log.info("  3. Fill in an application name and description (anything works)")
    log.info("  4. Copy the 'API Key' shown on the next page\n")
    log.info("Press Enter with no input to skip (results won't be filtered as well).\n")

    for attempt in range(3):
        key = getpass.getpass("Enter your Last.fm API key: ").strip()
        if not key:
            log.info("\nSkipping Last.fm setup.")
            return None
        if _validate_api_key(key):
            seed = _get_machine_seed()
            if seed is not None:
                value = "ENC:" + encrypt_key(key)
            else:
                log.info("NOTE: Could not detect stable hardware ID.")
                log.info("      Key will be stored in plain text.")
                value = key
            _write_key_to_env(value, env_path)
            log.info("API key saved to .env successfully.\n")
            # Create .env.example if it doesn't exist
            example_path = pathlib.Path(__file__).parent / ".env.example"
            if not example_path.exists():
                example_path.write_text(
                    "# Last.fm API key (optional, recommended)\n"
                    "# Get yours at: https://www.last.fm/api/account/create\n"
                    "LASTFM_API_KEY=\n"
                    "\n"
                    "# Optional: override default cache/output directories\n"
                    "# CACHE_DIR=~/.cache/music_discovery\n"
                    "# OUTPUT_DIR=~/.cache/music_discovery\n",
                    encoding="utf-8",
                )
            return key
        remaining = 2 - attempt
        if remaining > 0:
            log.info(f"Invalid key (must be 32 hex characters). {remaining} attempt(s) left.")
        else:
            log.info("Invalid key. No attempts remaining.")
            log.info("Get your key at: https://www.last.fm/api/account/create")
    return None
```

- [ ] **Step 4: Update `main()` to handle `api_key is None` gracefully**

Replace the current API key block in `main()` (lines 1036–1040, which currently does `if not api_key: return`) with the following. The old early-return (`if not api_key: return`) must be removed — the script now continues without an API key:

```python
    api_key = os.environ.get("LASTFM_API_KEY", "").strip()
    if not api_key:
        api_key = prompt_for_api_key()
        # api_key is None if user skipped or exhausted attempts

    if not api_key:
        log.info("\nRunning without Last.fm — results will include well-known artists")
        log.info("that would normally be filtered out.\n")

    library_artists = parse_library(library_path)
    log.info(f"Found {len(library_artists)} unique loved/favorited artists.\n")

    # ── 2. Load caches ─────────────────────────────────────
    cache        = load_cache(paths["cache"])
    filter_cache = load_cache(paths["filter_cache"]) if api_key else {}
    file_blocklist = load_blocklist(paths["blocklist"]) if api_key else set()
```

Then wrap steps 6 and 6b in an `if api_key:` guard. Step 7 (`filter_candidates`) remains outside the guard — it still runs unconditionally using whatever `filter_cache` and `file_blocklist` were set above (empty dicts/sets when no API key):

```python
    # ── 6. Fetch filter data for new candidates ────────────
    if api_key:
        candidates     = [name for _, name in scored]
        new_candidates = [c for c in candidates if not filter_cache.get(c)]
        if new_candidates:
            log.info(f"Fetching filter data for {len(new_candidates)} candidates...")
            for i, candidate in enumerate(new_candidates, 1):
                if i % 50 == 0:
                    log.info(f"  [{i}/{len(new_candidates)}]")
                data = fetch_filter_data(candidate, api_key)
                filter_cache[candidate] = data
                save_cache(filter_cache, paths["filter_cache"])
                time.sleep(RATE_LIMIT)

        # ── 6b. Auto-detect and persist new blocklist entries ──
        new_blocked = detect_blocklist_candidates(scored, filter_cache)
        new_blocked -= ARTIST_BLOCKLIST
        new_blocked -= file_blocklist
        if new_blocked:
            log.info(f"Auto-blocking {len(new_blocked)} non-artist entries: {sorted(new_blocked)}")
            file_blocklist |= new_blocked
            save_blocklist(file_blocklist, paths["blocklist"])
            top_tracks_cache = load_cache(paths["top_tracks"])
            purged = [a for a in new_blocked if a in top_tracks_cache]
            if purged:
                for a in purged:
                    del top_tracks_cache[a]
                save_cache(top_tracks_cache, paths["top_tracks"])
                log.info(f"Purged {len(purged)} blocked artist(s) from top_tracks_cache.")

    # Steps 5 (score) and 7 (filter_candidates) remain OUTSIDE the `if api_key:` guard.
    # They run unconditionally — filter_candidates uses whatever filter_cache/file_blocklist
    # were set above (empty when no API key, so only static blocklist + decade regex apply).
```

- [ ] **Step 5: Run all tests**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
cd "/Users/brianhill/Scripts/Music Discovery"
git add music_discovery.py tests/test_music_discovery.py
git commit -m "feat: make Last.fm optional — press Enter to skip API key setup"
```

---

### Task 3: Platform-guard the playlist

**Files:**
- Modify: `music_discovery.py` (step 8 in `main()`)

- [ ] **Step 1: Add platform + API key guards to playlist section**

Replace the current step 8 block in `main()`:

```python
    # ── 8. Build playlist (optional) ───────────────────────
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

Note: The playlist guards are two simple `if`/`elif` checks — no dedicated test needed. The guard logic is trivially verifiable by code review.

- [ ] **Step 2: Run all tests**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -v`
Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
cd "/Users/brianhill/Scripts/Music Discovery"
git add music_discovery.py
git commit -m "feat: guard playlist builder — macOS only, requires API key"
```

---

### Task 4: Repo cleanup

**Files:**
- Modify: `music_discovery.py:42` (update `MB_USER_AGENT`)
- Modify: `.gitignore` (add `run.log`, `music_discovery_results.txt`)
- Create: `requirements.txt`

- [ ] **Step 1: Update `MB_USER_AGENT`**

In `music_discovery.py`, change line 42:

```python
MB_USER_AGENT       = "MusicDiscoveryTool/1.0 (https://github.com/brianhill/music-discovery)"
```

- [ ] **Step 2: Update `.gitignore`**

Add to `.gitignore`:

```
run.log
music_discovery_results.txt
```

- [ ] **Step 3: Create `requirements.txt`**

```
requests
beautifulsoup4
playwright
python-dotenv
```

- [ ] **Step 4: Run all tests to verify nothing broke**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python -m pytest tests/test_music_discovery.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
cd "/Users/brianhill/Scripts/Music Discovery"
git add music_discovery.py .gitignore requirements.txt
git commit -m "chore: repo cleanup — requirements.txt, .gitignore, user-agent string"
```

---

## Chunk 2: Documentation

### Task 5: Write README.md

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`**

```markdown
# Music Discovery

Discover new music based on the artists you already love.

This tool reads loved/favorited artists from your Apple Music (or iTunes) library, finds similar artists via [music-map.com](https://www.music-map.com/), scores them by proximity, and filters out well-known artists so only genuine discoveries appear. Optionally builds an Apple Music playlist with top tracks from your discoveries.

## Quick Start

```bash
git clone https://github.com/brianhill/music-discovery.git
cd music-discovery
pip install -r requirements.txt
playwright install chromium
python music_discovery.py
```

## Requirements

- **Python 3.9+**
- **macOS or Windows** (Linux users: specify library path with `--library`)
- **Apple Music or iTunes library** exported as XML
- **Last.fm API key** (optional, free) — improves results by filtering out well-known artists

## Usage

```bash
# Basic discovery
python music_discovery.py

# Specify a custom library path
python music_discovery.py --library ~/path/to/Library.xml

# Discovery + build an Apple Music playlist (macOS only)
python music_discovery.py --playlist
```

## Platform Notes

| Feature | macOS | Windows | Linux |
|---------|-------|---------|-------|
| Artist discovery | Yes | Yes | Yes* |
| Last.fm filtering | Yes | Yes | Yes |
| Playlist building | Yes | No | No |

*Linux users must export their library XML and specify the path with `--library`.

## How It Works

See [Technical Overview](docs/how-it-works.md) for the full pipeline, scoring algorithm, and architecture.

## Documentation

- [User Guide](docs/user-guide.md) — installation, first run, configuration, troubleshooting
- [Technical Overview](docs/how-it-works.md) — how the scoring, filtering, and playlist systems work
- [Clever Bits](docs/clever-bits.md) — the non-obvious engineering challenges
- [Changelog](CHANGELOG.md) — milestones and notable incidents

## License

[MIT](LICENSE)
```

- [ ] **Step 2: Create `LICENSE` file (MIT)**

Standard MIT license with Brian Hill as the copyright holder, year 2026.

- [ ] **Step 3: Commit**

```bash
cd "/Users/brianhill/Scripts/Music Discovery"
git add README.md LICENSE
git commit -m "docs: add README and MIT license"
```

---

### Task 6: Write User Guide

**Files:**
- Create: `docs/user-guide.md`

- [ ] **Step 1: Write `docs/user-guide.md`**

Contents should cover (in this order):

1. **Prerequisites**
   - Python 3.9+ installation (link to https://www.python.org/downloads/)
   - How to export your library XML:
     - macOS: Music.app → File → Library → Export Library...
     - Windows: iTunes → File → Library → Export Library...
   - Note the default paths the script looks for:
     - macOS: `~/Music/Music/Music Library.xml`
     - Windows: `~\Music\iTunes\iTunes Music Library.xml`

2. **Installation**
   ```bash
   git clone https://github.com/brianhill/music-discovery.git
   cd music-discovery
   pip install -r requirements.txt
   playwright install chromium
   ```

3. **First Run**
   - What happens: the script asks for your Last.fm API key
   - How to get one (link to https://www.last.fm/api/account/create — it's free)
   - You can press Enter to skip — discovery still works, but results include well-known artists that would normally be filtered
   - After entering a valid key, it's encrypted and saved to `.env`
   - The script then scrapes music-map.com for each of your loved artists (rate-limited to 1 request/second)
   - First run takes a while depending on library size. Results are cached for subsequent runs.

4. **Understanding Results**
   - Output is saved to `~/.cache/music_discovery/music_discovery_results.txt`
   - Higher score = more of your artists point to this discovery, and from closer proximity
   - The score formula weights artists you've loved more heavily (but with diminishing returns)
   - Artists are filtered if they're too popular (>50k Last.fm listeners) AND debuted before 2006

5. **Building a Playlist** (macOS only)
   - Run with `--playlist` flag
   - Creates a "Music Discovery" playlist in Music.app with top tracks from your top 50 discoveries
   - You'll hear brief playback during the process — this is normal (it's how tracks get added to your library)
   - The playlist is cleared and rebuilt each run
   - Maximum 500 tracks per playlist

6. **Configuration**
   - `.env` file supports:
     - `LASTFM_API_KEY` — your API key (encrypted automatically)
     - `CACHE_DIR` — override cache location (default: `~/.cache/music_discovery`)
     - `OUTPUT_DIR` — override output location (default: same as CACHE_DIR)
   - Delete cache files in `~/.cache/music_discovery/` to force a fresh scrape

7. **Troubleshooting**
   - "Library file not found" — export your library as XML (instructions above) or use `--library`
   - Music.app beachballs during playlist build — force-quit Music.app, wait, re-run
   - "Playwright not installed" — run `playwright install chromium`
   - Rate limit errors — the script respects 1-second delays; if you hit limits, wait a few minutes
   - Results seem wrong — delete `~/.cache/music_discovery/filter_cache.json` to re-fetch filter data

- [ ] **Step 2: Commit**

```bash
cd "/Users/brianhill/Scripts/Music Discovery"
git add docs/user-guide.md
git commit -m "docs: add user guide"
```

---

### Task 7: Write Technical Overview

**Files:**
- Create: `docs/how-it-works.md`

- [ ] **Step 1: Write `docs/how-it-works.md`**

Contents should cover:

1. **Pipeline Overview**
   A text diagram showing the 8 steps:
   ```
   Library XML → Parse Loved Artists → Scrape music-map.com → Score Candidates
   → Fetch Last.fm/MusicBrainz Data → Auto-Blocklist → Filter → Output Results
   → (Optional) Build Playlist
   ```

2. **Scraping**
   - music-map.com displays similar artists as a spatial cloud around a center artist
   - Closer = more similar
   - **Plan A** (requests + BeautifulSoup): lightweight, uses link order as proximity proxy (first link = most similar)
   - **Plan B** (Playwright): headless Chromium, extracts actual pixel coordinates, computes Euclidean distance from viewport center, normalizes to 0–1 proximity score
   - Auto-detection: tests Plan A against "radiohead", falls back to Plan B if <3 results

3. **Scoring Algorithm**
   - For each library artist, we have a dict of `{candidate: proximity_score}`
   - Final score: `score(candidate) = Σ log(loved_count_i + 1) × proximity(i, candidate)`
   - The sum is across all library artists that point to this candidate
   - `log(loved_count + 1)` compresses the influence of heavily-loved artists — an artist you've loved 50 tracks from gets more weight than one with 2, but not 25x more
   - Result: sorted list of (score, candidate_name), descending

4. **Filtering**
   - Three layers:
     - **Static blocklist** — hardcoded names of artists/non-artists that slip through (wrong Last.fm data, song titles scraped as artists)
     - **Auto-blocklist** — any candidate returning `{}` from Last.fm after lookup is flagged as likely not a real artist
     - **Threshold filter** — candidates with >50,000 Last.fm listeners AND debut year ≤2006 are excluded (you probably already know them)
   - Decade regex catches entries like "80s", "70's music"
   - Cover regex catches entries like "(as made famous by Metallica)"

5. **Playlist Building**
   - Three-layer approach (no single API can search + add to playlist):
     1. **iTunes Search API** (free, no key): find the Apple Music store track ID
     2. **MediaPlayer framework** (via JXA): play the track, making it visible to Music.app
     3. **AppleScript**: grab the current track, add to library, add to "Music Discovery" playlist
   - Stale playback detection: snapshot current track before playing, poll until it changes
   - Cover/dupe filtering: strip parentheticals and "Live at…" suffixes before comparing
   - Safety cap: 500 tracks max, aborts if exceeded
   - Oversized playlist handling: if existing playlist >500 tracks, delete entire playlist and recreate

6. **Caching**
   - Four caches in `~/.cache/music_discovery/`:
     - `music_map_cache.json` — scrape results per artist
     - `filter_cache.json` — Last.fm/MusicBrainz data per candidate
     - `blocklist_cache.json` — auto-detected non-artists
     - `top_tracks_cache.json` — Last.fm top tracks per artist
   - Saved after every artist to prevent data loss on interrupt
   - Staleness detection: old flat-list cache entries are re-scraped to get proximity scores

7. **API Key Management**
   - XOR encryption using SHA-256 hash of hardware UUID as key
   - Platform-specific machine IDs: IOPlatformUUID (macOS), MachineGuid (Windows), /etc/machine-id (Linux)
   - Stored as `ENC:<hex>` in `.env`
   - Falls back to plaintext if no hardware ID available

- [ ] **Step 2: Commit**

```bash
cd "/Users/brianhill/Scripts/Music Discovery"
git add docs/how-it-works.md
git commit -m "docs: add technical overview"
```

---

### Task 8: Write Clever Bits

**Files:**
- Create: `docs/clever-bits.md`

- [ ] **Step 1: Write `docs/clever-bits.md`**

A bullet-pointed list of non-obvious engineering challenges, each with: what the problem was, why it was hard, and what the solution was. Written for Brian to cherry-pick for his tongue-in-cheek intro. Include these entries:

1. **Proximity-based scoring from a visual map** — music-map.com renders similar artists as a spatial cloud with no API. The Playwright scraper extracts actual pixel coordinates from the rendered page, computes Euclidean distance from the viewport center, and converts that to a 0–1 proximity score. The lightweight requests fallback uses DOM link order as a proxy. This turns a visual UI — designed for humans to browse — into quantitative similarity data.

2. **The three-layer playlist pipeline** — there is no Apple Music API that lets you search for a song and add it to a playlist. The solution chains three completely different systems: the iTunes Search API (find the store track ID — free, no key needed), the macOS MediaPlayer framework via JavaScript for Automation (play the track to make it appear in Music.app's scope), and AppleScript (grab the now-playing track and add it to the playlist). Each layer exists because the one before it can't finish the job alone.

3. **Stale playback detection** — the original playlist builder played a track, waited 3 seconds, then grabbed "current track" from Music.app and added it to the playlist. But sometimes the previous track was still playing when the grab happened, resulting in duplicates. The fix: snapshot whatever is playing before starting playback, then poll every 0.5 seconds until the current track changes (up to 5 seconds). Simple in hindsight, but the symptom — wrong songs appearing in the playlist — took real debugging to trace back to a timing race.

4. **The monster playlist** — a bug in playlist setup caused tracks to accumulate instead of being replaced across runs. After several test runs, the playlist had thousands of tracks. Attempting to clear it via AppleScript caused Music.app to beachball indefinitely (it tries to delete tracks one by one). The fix: check the track count before clearing. If it's over 500, delete the entire playlist object and create a fresh one. This is faster and doesn't lock up the app.

5. **Auto-blocklist detection** — music-map.com doesn't just return artist names. It sometimes returns song titles ("Let Her Go"), genre labels ("Classic Rock"), decade tags ("80s"), and other noise. These look like artists in the raw data. The auto-detection system flags any scored candidate that returns empty results (`{}`) from Last.fm — meaning Last.fm has never heard of them as an artist. Combined with regex filters for decade patterns and cover-song tags, this catches most noise without requiring manual curation per user.

6. **Log-weighted scoring** — a user who has loved 200 tracks by one artist and 3 tracks by another shouldn't get recommendations dominated by the first artist. The scoring formula uses `log(loved_count + 1)` as a weight, which compresses the gap: 200 loved tracks gives about 3.7x the weight of 3 loved tracks, not 67x. This means your deep obsessions still matter more, but your casual likes contribute meaningfully.

7. **Hardware-seeded API key encryption** — storing a plaintext API key in a `.env` file felt wrong. The solution: XOR the key against a SHA-256 hash of the machine's hardware UUID (IOPlatformUUID on macOS, MachineGuid on Windows, /etc/machine-id on Linux). It's not bank-grade cryptography, but the key is useless if the `.env` file is copied to another machine. Falls back to plaintext gracefully if no hardware ID is available.

8. **Scraper auto-detection** — music-map.com's anti-scraping measures change unpredictably. Sometimes a simple HTTP request gets the full page; sometimes it returns a skeleton that needs JavaScript rendering. The script tests Plan A (lightweight requests) against a known artist ("radiohead") at startup. If it gets fewer than 3 results, it silently switches to Plan B (headless Chromium via Playwright). Users never need to know or configure which scraper is running.

- [ ] **Step 2: Commit**

```bash
cd "/Users/brianhill/Scripts/Music Discovery"
git add docs/clever-bits.md
git commit -m "docs: add clever bits — engineering challenges for Brian's intro"
```

---

### Task 9: Write Changelog

**Files:**
- Create: `CHANGELOG.md`

- [ ] **Step 1: Write `CHANGELOG.md`**

Reverse chronological format with milestones and a "Notable Incidents" section at the end:

```markdown
# Changelog

## 2026-03-13 — Distribution & Documentation
- Windows support for the recommender (auto-detect library path, `--library` CLI flag)
- Last.fm API key is now optional — press Enter to skip during setup
- Playlist builder guarded to macOS only, with API key requirement
- Added README, user guide, technical overview, and changelog
- Added `requirements.txt` for easy dependency installation

## 2026-03-13 — API Key Management
- First-run interactive prompt for Last.fm API key
- XOR encryption with hardware-seeded SHA-256 for secure `.env` storage
- Platform-specific machine ID detection (macOS, Windows, Linux)
- Graceful fallback to plaintext if hardware ID unavailable

## 2026-03-12 — Playlist Fixes
- Stale playback detection: poll for track change instead of fixed sleep
- Cover version filtering (skip "(as made famous by…)" tracks)
- Track name deduplication (strip parentheticals and "Live at…" suffixes)
- Monster playlist safety: 500-track hard cap, delete-and-recreate for oversized playlists
- Post-playlist stop playback so the user isn't left listening to the last added track

## 2026-03-12 — Filter Refinements
- Lowered POPULAR_THRESHOLD from 2,000,000 to 50,000 (Last.fm listener counts skew young/indie)
- Added static ARTIST_BLOCKLIST for known false positives
- Auto-blocklist detection: flag candidates with empty Last.fm results as non-artists
- Decade regex filter ("80s", "70's music") and cover-song regex

## 2026-03-11 — Playlist Builder
- iTunes Search API integration (free, no key) for Apple Music catalog search
- MediaPlayer framework via JXA for track playback and library addition
- AppleScript automation for playlist creation and track management
- XML playlist fallback export for when AppleScript fails

## 2026-03-10 — Last.fm Integration
- Last.fm API: listener count filtering and MBID retrieval
- MusicBrainz API: debut year lookup for classic artist detection
- Canonical name resolution via artist.search (fixes mismatches between music-map and Last.fm names)

## 2026-03-10 — Cache System
- Persistent JSON caches (scrape, filter, blocklist, top tracks)
- Save-after-every-artist strategy to prevent data loss on interrupt
- Staleness detection and format migration (flat list → proximity dict)
- Cache path migration from script directory to `~/.cache/music_discovery/`

## 2026-03-09 — Environment Configuration
- `.env` file support via custom `load_dotenv()`
- Configurable `CACHE_DIR` and `OUTPUT_DIR`

## 2026-03-09 — Scoring Algorithm
- Weighted proximity formula: `score = Σ log(loved_count + 1) × proximity`
- Proximity-based scraping: Playwright extracts pixel coordinates, requests uses link order
- Proof-of-concept validation: coordinate-based scoring vs link-order scoring

## 2026-03-08 — Initial Build
- Apple Music Library XML parsing (loved/favorited tracks)
- music-map.com scraping with requests + BeautifulSoup (Plan A)
- Playwright headless browser fallback (Plan B) with auto-detection
- Basic artist tallying and text output

---

## Notable Incidents

### The Monster Playlist
A bug in playlist clearing caused tracks to accumulate instead of being replaced. After several test runs, the playlist had thousands of tracks. Attempting to clear it via AppleScript caused Music.app to beachball indefinitely — AppleScript deletes tracks one at a time, and thousands of delete operations locked up the app. Required force-quitting Music.app. Fixed by checking the track count before clearing: if over 500, the entire playlist object is deleted and recreated from scratch.

### REO Speedwagon's 2,500 Listeners
Last.fm reported REO Speedwagon as having 2,500 listeners. Their actual listener count is in the millions. This exposed that Last.fm's data can be wildly inaccurate for some artists, and a pure threshold-based filter will always have blind spots. Motivated the addition of a static blocklist as a manual safety net alongside the automated threshold filter.

### The iCloud Sync Problem
After building a playlist via AppleScript, tracks sometimes appeared missing. The root cause: adding a track to the library via AppleScript doesn't guarantee it's immediately available for search — iCloud sync can introduce delays. The MediaPlayer framework approach (play the track via the system music player first) solved this by making each track locally visible to Music.app before the AppleScript search-and-add step runs.
```

- [ ] **Step 2: Commit**

```bash
cd "/Users/brianhill/Scripts/Music Discovery"
git add CHANGELOG.md
git commit -m "docs: add changelog with milestones and notable incidents"
```
