# Distribution & Documentation Design

**Date:** 2026-03-13
**Goal:** Prepare the Music Discovery repo for public GitHub release with cross-platform support, comprehensive docs, and a changelog.

---

## 1. Code Changes

### 1a. `--library` CLI argument + platform auto-detect

Replace the hardcoded `LIBRARY_PATH` constant with a `_resolve_library_path(cli_override)` function:

- If `--library /path/to/file.xml` is passed via argparse, use that path directly.
- Otherwise, detect `platform.system()`:
  - **macOS (`Darwin`):** `~/Music/Music/Music Library.xml`
  - **Windows:** `~\Music\iTunes\iTunes Music Library.xml`
- If the resolved path doesn't exist, print a platform-specific help message:
  - macOS: `"Open Music.app → File → Library → Export Library…"`
  - Windows: `"Open iTunes → File → Library → Export Library…"`
  - Both: `"Or specify the path manually: python music_discovery.py --library /path/to/Library.xml"`
- Exit gracefully (not crash) if no library file is found.

**Files changed:** `music_discovery.py` — remove `LIBRARY_PATH` constant, add `_resolve_library_path()`, update `main()` argparse and library loading.

### 1b. Optional Last.fm (escape to skip)

Modify `prompt_for_api_key()`:

- Add a line to the prompt: `"Press Enter with no input to skip (results won't be filtered as well)"`
- If the user submits empty input (just presses Enter), return `None` immediately — don't count it as a failed attempt.
- In `main()`, when `api_key` is `None`:
  - Log: `"Running without Last.fm — results will include well-known artists that would normally be filtered out."`
  - Skip step 6 (filter data fetch) and step 6b (auto-blocklist detection).
  - Pass an empty `filter_cache` and empty `file_blocklist` to `filter_candidates()` — the static blocklist and decade regex still apply.
  - (Playlist guard for missing API key is handled in section 1c.)

**Files changed:** `music_discovery.py` — modify `prompt_for_api_key()`, update `main()` flow.

### 1c. Platform-guard the playlist

Add playlist guard checks in `main()` step 8, in this order:

1. **Platform check first:** If `--playlist` is passed and `platform.system() != "Darwin"`, log: `"Playlist building requires macOS with Apple Music. Skipping — discovery results are still saved."` and continue. Do not check API key.
2. **API key check second:** If `--playlist` is passed, platform is macOS, but `api_key is None`, log: `"Playlist building requires a Last.fm API key. Skipping."` and continue.

This ordering ensures only one skip message prints per run.

**Files changed:** `music_discovery.py` — add platform + API key checks in `main()` step 8.

### 1d. Repo cleanup

- **`MB_USER_AGENT`:** Update to `"MusicDiscoveryTool/1.0 (https://github.com/brianhill/music-discovery)"`. If Brian's GitHub username or repo name differs, update post-publish — this is a courtesy string for MusicBrainz rate-limit compliance, not a functional dependency.
- **`.gitignore` review:** Verify `run.log` and `music_discovery_results.txt` are excluded. Add if missing.
- **`requirements.txt`:** Create with: `requests`, `beautifulsoup4`, `playwright`, `python-dotenv`. Note: `playwright install chromium` is required after pip install — document in README quick start and user guide.
- **Keep `delete_playlist.py`** — it's a useful utility and part of the story.
- **Keep `tests/`** — demonstrates the project is tested.

---

## 2. Documentation

### 2a. README.md

Top-level README for the GitHub landing page:

- **What it does** — one-paragraph summary of the discovery pipeline.
- **Quick start** — 3 steps: clone, install deps, run.
- **Requirements** — Python 3.9+, macOS or Windows, optional Last.fm API key.
- **Usage** — CLI flags: `--playlist` (Mac only), `--library /path/to/file.xml`.
- **Platform notes** — recommender works on macOS and Windows; playlist builder is Mac-only.
- **Links** to user guide and technical overview.
- **License** — MIT (include a `LICENSE` file). Brian can change this before publishing if preferred.

### 2b. User Guide (`docs/user-guide.md`)

Step-by-step for non-technical users:

- **Prerequisites** — Python installation (link to python.org), how to export Apple Music library XML (Mac and Windows instructions with screenshots-as-text).
- **Installation** — `git clone`, `pip install -r requirements.txt`, `playwright install chromium`.
- **First run** — what to expect: API key prompt (with escape option), scraping progress, rate limiting.
- **Understanding results** — what the scores mean, the output file format, how proximity scoring works in plain language.
- **Building a playlist** (Mac only) — the `--playlist` flag, what happens in Music.app, why playback starts briefly.
- **Configuration** — `.env` options (`CACHE_DIR`, `OUTPUT_DIR`), cache management, re-running after library changes.
- **Troubleshooting** — common issues: library not found, Music.app beachball, playwright install problems, rate limit errors.

### 2c. Technical Overview (`docs/how-it-works.md`)

For developers and curious users:

- **Pipeline overview** — the 8-step flow from library parse to output, with a text diagram.
- **Scraping** — music-map.com's visual layout, why proximity matters, the Plan A/Plan B scraper strategy (requests vs Playwright), auto-detection.
- **Scoring algorithm** — the weighted proximity formula: `score(c) = Σ log(loved_count + 1) × proximity`. Why log-weighting prevents power users' most-loved artists from dominating.
- **Filtering** — Last.fm listener threshold (50k), MusicBrainz debut year cutoff (2006), the static blocklist, auto-blocklist detection for non-artists, decade regex.
- **Playlist building** — the three-layer stack (iTunes Search API → MediaPlayer framework → AppleScript), why each layer is needed, the stale-playback detection, cover/dupe filtering, the safety cap.
- **Caching** — what's cached (scrapes, filter data, blocklist, top tracks), where, staleness detection, why cache-per-artist-write prevents data loss on interrupt.
- **API key management** — XOR encryption with hardware-seeded SHA-256, platform-specific machine ID sources, graceful fallback to plaintext.

### 2d. Clever Bits (`docs/clever-bits.md`)

Bullet-pointed list of non-obvious engineering challenges and solutions, written so Brian can cherry-pick for his intro. Each entry: what the problem was, why it was hard, what the solution was. Covering at minimum:

- **Proximity-based scoring from a visual map** — music-map.com renders similar artists as a spatial cloud. The Playwright scraper extracts actual pixel coordinates and converts distance-from-center to a 0–1 proximity score. The requests fallback uses link order as a proxy. This turns a visual UI into quantitative similarity data.
- **The three-layer playlist pipeline** — no single API can do "find a song on Apple Music and add it to a playlist." The solution chains three systems: iTunes Search API (find the store ID), MediaPlayer framework via JXA (play the track to make it visible to Music.app), then AppleScript (grab the current track and add it to the playlist). Each layer solves one piece.
- **Stale playback detection** — the original playlist builder used `time.sleep(3)` after playing a track, but sometimes the previous track was still playing. The fix: snapshot the current track before playing, then poll until the current track changes. This eliminated duplicate playlist entries from the previous track getting grabbed instead.
- **The monster playlist incident** — a bug in playlist clearing caused tracks to accumulate across runs (thousands of tracks). Music.app beachballed when trying to delete them. The fix: detect oversized playlists, delete the whole playlist object and recreate it, rather than trying to delete individual tracks.
- **Auto-blocklist detection** — music-map.com sometimes returns non-artist entries (song titles like "Let Her Go", genre labels like "Classic Rock", decade tags like "80s"). The auto-detection system flags any scored candidate that returns `{}` from Last.fm after retry — meaning Last.fm has no record of them as an artist. Combined with a regex for decade patterns and a cover-song regex, this catches most noise without manual curation.
- **Log-weighted scoring** — a naive sum of proximity scores would let a user's single most-loved artist dominate recommendations. Using `log(loved_count + 1)` as a weight compresses the influence of heavily-loved artists, so recommendations reflect breadth of taste rather than obsessive replays.
- **Hardware-seeded API key encryption** — the Last.fm API key is XOR-encrypted using a SHA-256 hash of the machine's hardware UUID (IOPlatformUUID on Mac, MachineGuid on Windows, /etc/machine-id on Linux). Not bank-grade crypto, but it means the `.env` file isn't storing a plaintext API key, and the key is tied to the specific machine.
- **Scraper auto-detection** — music-map.com's anti-scraping measures change. The script tests Plan A (lightweight `requests` + BeautifulSoup) against a known artist, and automatically falls back to Plan B (headless Chromium via Playwright) if Plan A returns too few results. Users never need to configure this.

### 2e. Changelog (`CHANGELOG.md`)

Reverse chronological, covering milestones and notable incidents:

- **2026-03-13** — Distribution prep: Windows support, optional Last.fm, `--library` flag, documentation.
- **2026-03-13** — API key management: encrypted storage, first-run interactive prompt, hardware-seeded encryption.
- **2026-03-12** — Playlist fixes: stale playback detection, cover/dupe filtering, monster playlist safety cap (500 tracks), oversized playlist delete-and-recreate.
- **2026-03-12** — Filter refinements: POPULAR_THRESHOLD lowered to 50k, static ARTIST_BLOCKLIST, auto-blocklist detection for non-artist entries.
- **2026-03-11** — Playlist builder: iTunes Search API + MediaPlayer framework + AppleScript pipeline, XML fallback export.
- **2026-03-10** — Last.fm integration: listener count filtering, MusicBrainz debut year lookup, canonical name resolution via artist.search.
- **2026-03-10** — Cache system: persistent JSON caches, staleness detection, format migration.
- **2026-03-09** — Environment config: .env support, configurable CACHE_DIR/OUTPUT_DIR.
- **2026-03-09** — Scoring algorithm: weighted proximity formula with log-compressed loved counts.
- **2026-03-08** — Initial build: library XML parsing, music-map.com scraping (requests + Playwright), basic scoring, text output.

Notable incidents section:
- **The Monster Playlist** — A bug in playlist clearing caused tracks to accumulate instead of being replaced. After several runs, the playlist had thousands of tracks. Music.app beachballed when attempting to clear them, requiring a force-quit. Fixed by detecting oversized playlists and deleting the entire playlist object before recreating.
- **REO Speedwagon's 2,500 Listeners** — Last.fm reported REO Speedwagon as having 2,500 listeners (actual: millions). This exposed that Last.fm data can be wildly wrong for some artists, motivating the static blocklist as a safety net alongside the automated threshold filter.
- **The iCloud Sync Problem** — After building a playlist via AppleScript, tracks sometimes appeared missing because iCloud hadn't synced them yet. The MediaPlayer framework approach (play → grab → add) solved this by making each track locally visible before adding it.

---

## 3. Out of Scope

- PyPI packaging / `pyproject.toml` — not needed; clone-and-run is sufficient.
- CI/CD — no automated testing pipeline for now.
- The auto-detection function for blocklist candidates (planned but separate from distribution work).
- Web UI or hosted service.
