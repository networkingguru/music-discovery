# How It Works — Music Discovery Technical Overview

## 1. Pipeline Overview

```
Library XML → Parse Loved Artists → Scrape music-map.com → Score Candidates
→ Fetch Last.fm/MusicBrainz Data → Auto-Blocklist → Filter → Output Results
→ (Optional) Build Playlist
```

The script reads your Apple Music library export, identifies artists whose tracks you have loved, fetches similar-artist data from music-map.com for each of them, scores and ranks the candidates, filters out noise, and optionally builds a playlist in Music.app from the results.

---

## 2. Scraping

music-map.com renders a spatial cloud of similar artists: artists displayed closer to the center of the viewport are considered more similar to the query artist.

### Plan A — requests + BeautifulSoup (lightweight)

The script first attempts a simple HTTP request and parses the HTML with BeautifulSoup. Link order in the document is used as a proximity proxy: artists listed earlier in the markup are treated as more similar. This approach requires no browser and runs quickly.

### Plan B — Playwright (headless Chromium)

If Plan A yields fewer than 3 results, the script falls back to launching a headless Chromium instance via Playwright. In this mode, pixel coordinates of each artist element are measured and Euclidean distance from the viewport center is computed. Distances are then normalized to a 0–1 proximity score (1 = closest = most similar).

### Auto-detection

On startup the scraper tests Plan A against the query `"radiohead"`. If the result set contains fewer than 3 artists it automatically switches to Plan B for the remainder of the run.

---

## 3. Scoring Algorithm

For each library artist a dictionary of `{candidate: proximity_score}` is built from the scrape results. Candidates are then aggregated across all library artists using a weighted sum:

```
score(candidate) = Σ  log(loved_count_i + 1) × proximity(i, candidate)
```

- `loved_count_i` — number of loved tracks by library artist `i`
- `proximity(i, candidate)` — normalized proximity score from music-map.com
- The sum runs over every library artist `i` that has `candidate` in its similar-artist list

Using `log(loved_count + 1)` compresses the influence of heavily-loved artists so that a single artist with 200 loved tracks does not completely dominate the ranking.

Results are returned as a list sorted by `(score, name)` descending.

---

## 4. Filtering

Three layers of filtering are applied after scoring.

### Static blocklist

A hardcoded set of names that are known to slip through despite passing other checks (e.g., genre labels, compilation keywords).

### Auto-blocklist

Any candidate that returns an empty response `{}` from Last.fm is flagged as a non-artist (e.g., a mood tag, a decade label, a failed lookup) and added to `blocklist_cache.json` so it is skipped in future runs.

### Threshold filter

Candidates must meet both of the following criteria to pass:

- **Listener count** > 50,000 on Last.fm
- **Debut year** ≤ 2006 (via MusicBrainz)

### Additional regex filters

- Decade strings matching a pattern like `"80s"`, `"1990s"`, etc. are discarded.
- Strings containing `"as made famous by"` (common in karaoke/cover compilations) are discarded.

---

## 5. Playlist Building

On macOS, building a playlist requires bridging three separate Apple APIs because no single API can both find a track and add it to a user library playlist. On Windows, the script generates an XML playlist file that can be imported into iTunes (see XML Playlist Export below).

### Layer 1 — iTunes Search API (free, no key required)

Given a track title and artist name, the iTunes Search API returns a store track ID. This is the only reliable way to locate a specific recording without a paid Apple Music API key.

### Layer 2 — MediaPlayer framework via JXA

The store track ID is passed to the MediaPlayer framework through a JXA (JavaScript for Automation) script, which plays the track and makes it visible to Music.app. This step is necessary because AppleScript alone cannot play a track that is not already in the local library.

### Layer 3 — AppleScript

Once the track is playing and visible in Music.app, an AppleScript grabs the current track object, adds it to the library, and then adds it to the target playlist.

> **Warning:** The "add to library" step (`duplicate ct to source "Library"`) may **purchase the track** if you do not have an active Apple Music subscription. When running across dozens of artists and hundreds of tracks, this could result in very significant charges (potentially $150+). An active Apple Music subscription is strongly recommended before using `--playlist`.

### Safeguards

- **Stale playback detection** — if the now-playing track does not match the expected track within a timeout window, the operation is aborted for that track.
- **Cover/dupe filtering** — tracks identified as covers or duplicates are skipped.
- **500-track safety cap** — the playlist builder stops after adding 500 tracks to prevent runaway growth.
- **Oversized playlist handling** — if the existing **Music Discovery** playlist exceeds the cap, it is deleted and recreated from scratch. This check applies only to the Music Discovery playlist — no other playlists are affected.

### XML Playlist Export (Windows)

On Windows, the AppleScript/MediaPlayer pipeline is unavailable. Instead, the script:

1. Fetches top tracks for each discovered artist via the iTunes Search API and Last.fm
2. Generates an Apple-compatible XML plist file (`Music Discovery.xml`) containing track metadata
3. The user imports this file into iTunes via **File → Library → Import Playlist**

The XML export uses Python's built-in `plistlib` module and produces a valid Apple XML plist on any platform. This is also used as a fallback on macOS when the native pipeline fails.

---

## 6. Caching

All cache files live in `~/.cache/music_discovery/` and are written per-artist to limit data loss if the script is interrupted.

| File | Contents |
|---|---|
| `music_map_cache.json` | Scrape results from music-map.com |
| `filter_cache.json` | Last.fm and MusicBrainz metadata |
| `blocklist_cache.json` | Auto-detected non-artists |
| `top_tracks_cache.json` | Last.fm top tracks per artist |

Staleness detection is performed on load to handle format migrations between script versions. If a cache entry is in an unrecognized format it is discarded and re-fetched.

---

## 7. API Key Management

Last.fm and MusicBrainz API keys are stored in a `.env` file. To avoid storing keys in plaintext, the script encrypts them using XOR with a SHA-256 hash of the machine's hardware UUID.

### Platform UUID sources

| Platform | Source |
|---|---|
| macOS | `IOPlatformUUID` (via `ioreg`) |
| Windows | `HKLM\SOFTWARE\Microsoft\Cryptography\MachineGuid` |

### Storage format

Encrypted keys are stored as `ENC:<hex>` in `.env`:

```
LASTFM_API_KEY=ENC:3a9f2c...
```

On load, `load_dotenv()` detects the `ENC:` prefix, derives the same XOR key from the hardware UUID, and decrypts the value in memory before returning it to the caller. If no `ENC:` prefix is present the value is used as plaintext, maintaining backward compatibility.

### First-run setup

On first run (or when no `.env` is found), `prompt_for_api_key()` is called from `main()`. It collects the key interactively, encrypts it, and writes the `ENC:` prefixed value to `.env`.
