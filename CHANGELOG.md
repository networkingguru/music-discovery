# Changelog

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

### The Monster Playlist
A bug in playlist clearing caused tracks to accumulate instead of being replaced. After several test runs, the playlist had 1.3 million tracks. Attempting to clear it via AppleScript caused Music.app to beachball indefinitely — AppleScript deletes tracks one at a time, and thousands of delete operations locked up the app. Required force-quitting Music.app. Fixed by checking the track count before clearing: if over 500, the entire playlist object is deleted and recreated from scratch.

### REO Speedwagon's 2,500 Listeners
Last.fm reported REO Speedwagon as having 2,500 listeners. Their actual listener count is in the millions. This exposed that Last.fm's data can be wildly inaccurate for some artists, and a pure threshold-based filter will always have blind spots. Motivated the addition of a static blocklist as a manual safety net alongside the automated threshold filter.

### The iCloud Sync Problem
After building a playlist via AppleScript, tracks sometimes appeared missing. The root cause: adding a track to the library via AppleScript doesn't guarantee it's immediately available for search — iCloud sync can introduce delays. The MediaPlayer framework approach (play the track via the system music player first) solved this by making each track locally visible to Music.app before the AppleScript search-and-add step runs.
