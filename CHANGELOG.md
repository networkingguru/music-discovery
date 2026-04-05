# Changelog

## 2026-04-05 — Playlist Build Improvements (R3)
- Normalized track name dedup: catches alternate versions (Live, Remastered, etc.) of songs already in library
- Fixed cooldown system: artists offered and ignored/skipped are now properly cooled down between rounds (was silently failing due to date-string-as-int parsing)
- Fixed library artist scoring: removed playlists signal penalty that was incorrectly tanking scores for known artists
- Stratified playlist: 60% new artist discovery (2 tracks each) + 40% library deep cuts (1 track each), targeting 100 tracks
- Fuzzy library matching: handles spacing/punctuation/case differences between iTunes API and Music.app track names
- Graceful JXA timeout recovery: one failed track no longer aborts the entire build
- Single reusable "Adaptive Discovery" playlist (delete and recreate each round instead of per-round names)
- Snapshot now records actual added track names for accurate feedback detection
- Presumed-skip logic for streaming tracks with no play/skip counters

## 2026-04-02 — Adaptive Music Discovery Engine
- New adaptive engine (`adaptive_engine.py`) with three CLI modes: `--seed`, `--build`, `--feedback`
- Logistic regression model (`weight_learner.py`) learns signal weights from listening feedback
- Affinity graph (`affinity_graph.py`) with propagation, pruning, and recency decay
- Feedback module (`feedback.py`) with pre/post listening snapshots and diff-based outcome detection
- 9 signals: favorites, play count, playlists, ratings, heavy rotation, recommendations, Last.fm similar, Last.fm loved, AI heuristic
- Multi-round learning cycle: seed → build playlist → listen → feedback → retrain → build next round
- Cross-round track dedup via `offered_tracks` persistence
- Library-first track add path (fast, no JXA playback needed for owned tracks)
- `SearchResult` dataclass for iTunes search with canonical name resolution
- Search strikes and auto-blocklist for unfindable artists
- Library artists included as candidates for deep cut discovery

## 2026-04-02 — Playback Fix & Playlist Robustness
- Poll `isPreparedToPlay` via NSRunLoop in `_play_store_track` (fixes silent playback failures)
- Tiered track sourcing: Last.fm top 50 + iTunes catalog deep cuts
- Cap search attempts per artist to prevent multi-minute stalls
- Pre-seed dedup set with library tracks to skip known tracks
- Create playlist before build loop (fixes missing playlist on first run)

## 2026-03-31 — AI Artist Detection
- Three-layer detection: curated blocklist, Last.fm bio/tag analysis, MusicBrainz type check
- AI blocklist (`ai_blocklist.txt`) and allowlist (`ai_allowlist.txt`) for manual overrides
- Extended `fetch_filter_data()` with bio, tags, and MusicBrainz artist type
- Detection log written to `~/.cache/music_discovery/ai_detection_log.txt` for transparency
- MusicBrainz audit of blocklist to remove false positive collisions

## 2026-03-28 — Signal Wargaming Experiment
- 4-phase signal wargaming framework: signal profiling, ablation, degraded scenarios, recommendations
- MusicKit user-token auth module with Playwright automation and manual fallback
- JXA signal collectors for play counts, playlist membership, and star ratings
- Apple Music API collectors for heavy rotation and recommendations
- Evaluation playlist builder (80 artists per config for statistical significance)
- Post-listen scoring with manifest tracking
- Negative scoring rework: rejected artists replace manual blocklist proximity

## 2026-03-27 — Tuning Experiment
- Apple Music API proof-of-concept (heavy rotation, recommendations)
- Tunable scoring function with configurable `apple_weight`
- Result: `apple_weight=0.2` selected as optimal blend
- Apple Music prefetch with caching for experiment repeatability

## 2026-03-26 — V2 Foundation
- JXA library reading (`parse_library_jxa()`) replaces XML parsing for live data
- JXA playlist reading (`parse_md_playlist_jxa()`) for current playlist state
- Apple Music API vs music-map.com similarity comparison POC
- Always delete-and-recreate playlist to avoid iCloud sync race
- Negative scoring for candidates near blocklisted artists

## 2026-03-19 — Auto Import & Playlist Audit
- Playlist audit: parse Music Discovery playlist, blocklist rejected artists
- Exclude existing playlist artists from new discovery results
- Verify playlist exists in Music.app before trusting stale XML
- Split library-add and playlist-add into separate AppleScript calls

## 2026-03-14 — Distribution Sanitization
- Personal artist blocklist entries moved to user-editable `blocklist.txt` (`.gitignore`d)
- `--playlist` now works on Windows via XML export (import in iTunes via File → Library → Import Playlist)
- Fixed GitHub URLs throughout documentation and code

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

### The Little Lion Man Dedup Bug
During R3 playlist testing, "Little Lion Man" by Mumford & Sons kept appearing on the discovery playlist even though it was already in the library. The dedup system was comparing exact track names, but the iTunes Search API returned `"Little Lion Man"` while the library copy was `"Little Lion Man (Live from Bull Moose)"`. The parenthetical suffix made them look like different tracks. Fixed by normalizing track names before comparison — stripping parentheticals, "Live at/from" suffixes, and "Remastered" tags. This same normalization bug was also hiding other duplicate alternate versions.

### The Monster Playlist
A bug in playlist clearing caused tracks to accumulate instead of being replaced. After several test runs, the playlist had 1.3 million tracks. Attempting to clear it via AppleScript caused Music.app to beachball indefinitely — AppleScript deletes tracks one at a time, and thousands of delete operations locked up the app. Required force-quitting Music.app. Fixed by checking the track count before clearing: if over 500, the entire playlist object is deleted and recreated from scratch.

### REO Speedwagon's 2,500 Listeners
Last.fm reported REO Speedwagon as having 2,500 listeners. Their actual listener count is in the millions. This exposed that Last.fm's data can be wildly inaccurate for some artists, and a pure threshold-based filter will always have blind spots. Motivated the addition of a static blocklist as a manual safety net alongside the automated threshold filter.

### The iCloud Sync Problem
After building a playlist via AppleScript, tracks sometimes appeared missing. The root cause: adding a track to the library via AppleScript doesn't guarantee it's immediately available for search — iCloud sync can introduce delays. The MediaPlayer framework approach (play the track via the system music player first) solved this by making each track locally visible to Music.app before the AppleScript search-and-add step runs.
