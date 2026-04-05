# How It Works — Music Discovery Technical Overview

This project has two operating modes:

- **Classic Mode** (`music_discovery.py`) — The original v1 pipeline. One-shot: parse library, scrape similar artists, score, filter, build playlist.
- **Adaptive Engine** (`adaptive_engine.py`) — A feedback-driven discovery loop. Learns from listening behavior across rounds using logistic regression and graph propagation.

Both modes share the same underlying infrastructure (scraping, caching, playlist building, AI detection) but differ in how candidates are scored and selected.

---

# Part I — Classic Mode (`music_discovery.py`)

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

## 3. Classic Scoring Algorithm

For each library artist a dictionary of `{candidate: proximity_score}` is built from the scrape results. Candidates are then aggregated across all library artists using a weighted sum:

```
score(candidate) = Σ  sqrt(log(loved_count_i + 1)) × proximity(i, candidate)
```

- `loved_count_i` — number of loved tracks by library artist `i`
- `proximity(i, candidate)` — normalized proximity score from music-map.com
- The sum runs over every library artist `i` that has `candidate` in its similar-artist list

Using `sqrt(log(loved_count + 1))` compresses the influence of heavily-loved artists so that a single artist with 200 loved tracks does not completely dominate the ranking.

Results are returned as a list sorted by `(score, name)` descending.

---

## 4. Classic Filtering

Three layers of filtering are applied after scoring.

### Static blocklist

A hardcoded set of names that are known to slip through despite passing other checks (e.g., genre labels, compilation keywords).

### Auto-blocklist

Any candidate that returns an empty response `{}` from Last.fm is flagged as a non-artist (e.g., a mood tag, a decade label, a failed lookup) and added to `blocklist_cache.json` so it is skipped in future runs.

### Threshold filter

Candidates must meet both of the following criteria to pass:

- **Listener count** > 50,000 on Last.fm
- **Debut year** <= 2006 (via MusicBrainz)

### Additional regex filters

- Decade strings matching a pattern like `"80s"`, `"1990s"`, etc. are discarded.
- Strings containing `"as made famous by"` (common in karaoke/cover compilations) are discarded.

---

# Part II — Adaptive Engine (`adaptive_engine.py`)

## 5. Adaptive Pipeline Overview

```
--seed:      Collect signals → Build graph → Bootstrap model
--build:     Score candidates → Build stratified playlist → Save snapshot
--feedback:  Diff snapshots → Aggregate outcomes → Retrain model → Update graph
```

The engine operates in a recurring loop: **seed** (once), then **build** and **feedback** alternate. Each build round produces a playlist. The user listens. Feedback collects the results and retrains the model for the next build.

---

## 6. Signal System

The engine uses 9 signals to characterize candidate artists. These fall into two categories based on how they are computed.

### Proximity-weighted aggregate signals (4)

These signals are properties of **seed artists** (artists in the user's library). For each candidate, the signal value is a weighted sum across all seed artists, where the weight is the similarity proximity between the seed and the candidate:

```
feature[signal] = Σ seed_signals[signal][seed] × proximity[seed][candidate]
```

Raw values are compressed with `log1p()` before aggregation to prevent numerical overflow (e.g., a play count of 10,000+).

| Signal | Source | What it measures |
|---|---|---|
| `favorites` | JXA (Music.app) | Number of favorited tracks per artist |
| `playcount` | JXA (Music.app) | Total play count per artist |
| `playlists` | JXA (Music.app) | Number of distinct user playlists the artist appears in |
| `ratings` | JXA (Music.app) | Centered star ratings: `(stars - 3) / 2`, so 5-star = +1.0, 1-star = -1.0 |

### Direct per-candidate signals (5)

These are binary or continuous values looked up directly for each candidate artist:

| Signal | Source | What it measures |
|---|---|---|
| `heavy_rotation` | Apple Music API | 1.0 if the artist appears in the user's heavy rotation, else 0.0 |
| `recommendations` | Apple Music API | 1.0 if Apple Music recommends this artist, else 0.0 |
| `lastfm_similar` | Last.fm API | Similarity score from Last.fm (reserved, currently 0.0) |
| `lastfm_loved` | Last.fm API | 1.0 if the user has loved tracks by this artist on Last.fm, else 0.0 |
| `ai_heuristic` | Last.fm listener count | Confidence the artist is a real human artist, scaled logarithmically from 0 (100 listeners) to 1.0 (100k+ listeners) |

Optional API signals (`heavy_rotation`, `recommendations`, `lastfm_loved`) degrade gracefully — if tokens or usernames are not configured, they default to 0.0.

---

## 7. Logistic Regression Model (`weight_learner.py`)

### Architecture

An L2-regularized logistic regression trained via scikit-learn. The model learns which combination of signals predicts whether the user will favorite a discovered artist.

- **Training**: Z-score normalization (mean/std computed from training set), then `LogisticRegression` with balanced class weights and LBFGS solver.
- **Inference**: Direct sigmoid computation from stored weights and bias — no sklearn dependency at prediction time.

```
p(favorite) = 1 / (1 + exp(-(bias + Σ w[i] × normalized_x[i])))
```

### Persistence

The model saves to JSON: signal names, weights, bias, and normalization statistics (mean/std per signal). This allows prediction without reconstructing the sklearn model object.

### Bootstrap

On first `--seed`, training data comes from wargaming experiment results (previously offered artists and their favorite/non-favorite outcomes). On subsequent `--feedback` runs, the model is refit on all accumulated feedback history.

---

## 8. Affinity Graph (`affinity_graph.py`)

### Structure

A graph where nodes are artists and edges represent similarity. Two independent edge stores are maintained:

- **music-map edges** — from music-map.com scrape data (proximity scores)
- **Last.fm edges** — from Last.fm similar-artist API (match scores)

All edges are undirected. The two stores are propagated independently so callers can apply different weights to each source.

### Feedback injection

User feedback is injected as signal at artist nodes. The injection formula:

```
positive       = sqrt(fave_count)
negative_skip  = skip_count × 0.7 × attenuation
negative_listen = min((listen_count - 1) × 0.1, 0.5)
net            = positive - negative_skip - negative_listen
injection      = net × recency_factor(days_ago, half_life)
```

- `attenuation` = `min(tracks_offered, 3) / 3.0` — dampens skip penalty when few tracks were offered
- The first listen contributes zero negative signal (only subsequent listens penalize)
- `recency_factor` = exponential decay with configurable half-life (180 days for library data, 90 days for discovery data)

### Propagation

Injected signal propagates outward via BFS through the graph:

- Each hop decays the signal by `0.4 × edge_weight`
- Maximum 3 hops (configurable)
- First-path-wins: a visited set prevents double-counting the same source via multiple paths
- Scores accumulate across multiple injection sources

### Pruning

Edges below a minimum weight threshold (default 0.1) are removed. Orphan nodes are cleaned up from both edge stores.

---

## 9. Two-Channel Scoring

Each candidate receives a final score that blends the model prediction with the affinity graph:

```
final_score = alpha × model_score + (1 - alpha) × affinity_score
```

- `alpha` defaults to 0.5 (configurable via `--alpha`)
- `affinity_score` combines music-map and Last.fm propagated scores, normalized to [-1, 1] and mapped to [0, 1] before blending
- Normalization is symmetric (preserves negative scores from skip feedback)

### Filtering pipeline

After scoring, candidates pass through:

1. **Blocklist filter** — union of user blocklist, auto-blocklist, and AI blocklist
2. **Override application** — manual pin overrides from `artist_overrides.json` (positive pin forces a score, negative pin suppresses to 0.0)
3. **Cooldown filter** — artists offered in recent rounds (within `cooldown_rounds`, default 3) that were not favorited are skipped
4. **AI artist detection** — three-layer check (see Section 13)

---

## 10. Feedback Loop

The feedback cycle detects what the user did with the playlist between `--build` and `--feedback`.

### Pre-listen snapshot

At the end of `--build`, a snapshot is taken of all offered tracks: play count, skip count, and favorited status, read from Music.app via JXA.

### Post-listen diff

When `--feedback` runs, it collects a fresh snapshot and diffs against the pre-listen state. Each track receives one outcome (in priority order):

| Outcome | Condition |
|---|---|
| `favorite` | Newly favorited (trumps all other signals) |
| `skip` | Skip count increased |
| `listen` | Play count increased (not faved, not skipped) |
| `presumed_skip` | No change detected — Apple Music does not reliably track play/skip counts for streaming-only playlist tracks, so silence is treated as a skip |

### Per-artist aggregation

Track-level outcomes are aggregated per artist: `fave_tracks`, `skip_tracks`, `listen_tracks`, `presumed_skip_tracks`, and `tracks_offered`. Presumed skips count as half-weight confirmed skips when injected into the affinity graph.

### Model retraining

After feedback, the model is refit on **all** accumulated feedback rounds (not just the latest). Training labels: `1` if the artist had any favorited tracks, `0` otherwise. Expunged feedback entries (from `artist_overrides.json`) are excluded.

### Graph update

The affinity graph is rebuilt from scratch each feedback round: library favorites are injected, then all historical feedback rounds are replayed with recency decay. The graph is then propagated and pruned.

---

## 11. Stratified Playlist

Each `--build` round produces a playlist targeting 100 tracks with a stratified mix:

| Slot type | Artists | Tracks per artist | Total tracks |
|---|---|---|---|
| New artists | 30 | 2 | 60 |
| Library deep cuts | 40 | 1 | 40 |

Library artists are included as candidates for deep-cut discovery. Their `playlists` signal is zeroed out during scoring to prevent the model's negative weight on that signal from unfairly penalizing them.

### Track sourcing

For each selected artist, tracks are sourced in a tiered order:

1. **Last.fm top tracks** (up to 50) — provides popularity-ranked track lists
2. **iTunes catalog** (Apple Music search API) — fills in tracks not found on Last.fm

Catalog tracks are deduplicated against the Last.fm set by lowercased track name.

---

## 12. Cross-Round Deduplication

Tracks are deduplicated across rounds to avoid offering the same track twice.

### Offered tracks persistence

`offered_tracks.json` stores every `(artist, track)` tuple ever added to a playlist, tagged with the round number. Before adding a track, both the raw name and a normalized form are checked against this set.

### Normalization

Track names are normalized (lowercased, stripped of parenthetical suffixes like "(Live from ...)", "(Remastered)") so alternate versions of the same song are caught by the dedup check.

### Library pre-seeding

At build time, all tracks currently in the user's library are added to the dedup set (in memory only, not persisted). This ensures the playlist only offers tracks the user does not already have, while library artists can still appear with different tracks.

### Search strikes

Artists that consistently fail iTunes search (no tracks found for 3 consecutive rounds) are auto-blocklisted. A cooldown-based re-check system (every 10 rounds) allows recovery if the artist later becomes available.

---

## 13. AI Artist Detection

A three-layer system prevents AI-generated or non-artist entries from polluting recommendations. Evaluation short-circuits at the first decisive result.

| Layer | Source | Logic |
|---|---|---|
| 1. Allowlist/Blocklist | `ai_allowlist.txt`, `ai_blocklist.txt` | Allowlist passes immediately; blocklist blocks immediately |
| 2. MusicBrainz type | MusicBrainz API | If the entity is typed as Person, Group, Orchestra, or Choir with releases, it passes |
| 3. Last.fm heuristic | Last.fm API | No bio + no tags + fewer than 1,000 listeners = blocked |

API failures default to pass (benefit of the doubt). Results are cached in `filter_cache.json` with a staleness date.

The adaptive engine also computes an `ai_heuristic` signal: a continuous score from 0.0 to 1.0 based on log-scaled listener count, which the model can learn to weight appropriately.

---

# Part III — Shared Infrastructure

## 14. Playlist Building

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
3. The user imports this file into iTunes via **File > Library > Import Playlist**

The XML export uses Python's built-in `plistlib` module and produces a valid Apple XML plist on any platform. This is also used as a fallback on macOS when the native pipeline fails.

---

## 15. Library Matching

Track names returned by the iTunes Search API often differ from what Music.app reports (e.g., `"Little Lion Man"` vs `"Little Lion Man (Live from ...)"` or `"Song (Remastered 2024)"`). A fuzzy normalized matching system handles this:

- Track names are lowercased and stripped of parenthetical suffixes
- Both raw and normalized forms are checked during dedup
- The actual artist and track names returned by Music.app after adding are recorded, so future dedup uses the canonical names

---

## 16. Caching

All cache files live in `~/.cache/music_discovery/` and are written per-artist to limit data loss if the script is interrupted.

| File | Contents |
|---|---|
| `music_map_cache.json` | Scrape results from music-map.com |
| `filter_cache.json` | Last.fm and MusicBrainz metadata |
| `blocklist_cache.json` | Auto-detected non-artists |
| `top_tracks_cache.json` | Last.fm top tracks per artist |
| `affinity_graph.json` | Similarity graph topology (adaptive engine) |
| `weight_model.json` | Logistic regression model weights (adaptive engine) |
| `feedback_history.json` | All feedback rounds with per-artist outcomes (adaptive engine) |
| `offered_tracks.json` | Cross-round track dedup state (adaptive engine) |
| `offered_features.json` | Feature vectors for the current round's offered artists (adaptive engine) |
| `pre_listen_snapshot.json` | Track state before listening session (adaptive engine) |
| `search_strikes.json` | Per-artist iTunes search failure counters (adaptive engine) |
| `artist_overrides.json` | Manual pin overrides and expunged feedback entries (adaptive engine) |
| `playlist_explanation.txt` | Human-readable scoring explanation for the current playlist (adaptive engine) |

Staleness detection is performed on load to handle format migrations between script versions. If a cache entry is in an unrecognized format it is discarded and re-fetched.

---

## 17. API Key Management

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
