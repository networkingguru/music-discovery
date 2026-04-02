# Adaptive Music Discovery Engine — Design Spec

**Date:** 2026-04-02
**Status:** Draft
**Replaces:** Proximity-only ranking in `music_discovery.py`, signal wargaming fixed configs

## 1. Overview

An adaptive music discovery engine that replaces the static proximity-based ranking and manual A/B testing. Instead of fixed scoring configs, the system learns which signals predict the user's taste and propagates feedback through a similarity graph to find better candidates over time.

### Core loop

1. System scores all candidate artists and builds a playlist of the top-ranked unknowns
2. User listens
3. System collects feedback (favorites, skips, listen-no-fave) by diffing library state before/after
4. Feedback updates two things: **signal weights** (which signals to trust) and the **affinity graph** (taste propagation through similar artists)
5. Next playlist is better. Repeat.

### Bootstrap

Three existing wargaming rounds (32 favorites, ~283 non-favorites) plus the full library history (~1100 favorited artists) seed the model so it doesn't start cold.

### Signals (8 total)

| Signal | Source | Status |
|--------|--------|--------|
| favorites | Music.app (JXA) | Existing |
| playcount | Music.app (JXA) | Existing |
| playlists | Music.app (JXA) | Existing |
| ratings | Music.app (JXA) | Existing |
| heavy_rotation | Apple Music API | Existing |
| recommendations | Apple Music API | Existing |
| lastfm_similar | Last.fm `artist.getInfo` | **New** — data already returned, just unused |
| lastfm_loved | Last.fm `user.getLovedTracks` | **New** — needs username in `.env` |

## 2. Mathematical Model

Two complementary systems combine into a final score.

### Signal Weight Learning (Bayesian Logistic Regression)

Each signal gets a learned weight. The probability an artist is a hit:

```
P(favorite | artist) = sigmoid(w1*favorites + w2*playcount + w3*playlists
                              + w4*ratings + w5*heavy_rot + w6*recs
                              + w7*lfm_similar + w8*lfm_loved
                              + w_affinity*affinity_score)
```

- Weights start with weak Gaussian priors: each w ~ N(0, 1). This expresses no preference for any signal while keeping weights reasonable.
- After each round, update weight posteriors using labeled outcomes (Laplace approximation or variational inference on the logistic likelihood)
- The 3 existing wargaming rounds (32 positives, ~283 negatives) bootstrap the priors immediately
- Affinity score (from the graph) is itself a feature with a learned weight, so the model learns how much to trust graph propagation vs raw signals

### Affinity Graph (Taste Propagation)

A graph where nodes are artists and edges come from similarity data (music-map + Last.fm similar). Feedback propagates through it:

| Feedback | Injection strength | Propagation |
|----------|-------------------|-------------|
| Single favorite | +1.0 | Decays per hop (x0.5, 2-3 hops max) |
| Multi-fave artist | +1.0 * sqrt(count) — caps ~7.1 at 50 faves | Same decay |
| Skip (discovery track) | -0.7 | Same decay structure |
| Listen, no fave | -0.1 | Local only (1 hop max) |
| Multi-listen, no fave | Accumulates to -0.3 to -0.5 | Starts propagating (2 hops) |

**Recency weighting:** Exponential decay based on age: `recency_factor = exp(-lambda * days_since_event)` where lambda = ln(2)/180 (half-life of 180 days). Recent feedback (last ~2 weeks) is effectively full strength. Library data from years ago still contributes but at reduced magnitude. Discovery round feedback uses the round date; library favorites use the date added (available via JXA `dateAdded` property).

### Final Score

```
score(artist) = sigmoid(w * features)
```

where `features` includes the affinity graph score as one dimension. The weight learner handles the balance between raw signals and graph propagation automatically.

### Feature Normalization

Raw signal values have vastly different scales (favorites: 1-50+, playcount: 1-10000+, ratings: -1 to +1). All features are z-score normalized before entering the model: `normalized = (value - mean) / std` computed across the candidate pool. This prevents high-magnitude signals from dominating regardless of learned weights. Normalization statistics are recomputed each round from the current candidate pool.

### Signal Feature Definitions

Each signal produces a per-candidate numeric value:

| Signal | Feature value for candidate artist |
|--------|-----------------------------------|
| favorites | Count of favorited tracks by this artist in library |
| playcount | Total play count across all tracks by this artist |
| playlists | Number of distinct user playlists containing this artist |
| ratings | Average centered star rating: (stars - 3) / 2. Unrated = 0.0 |
| heavy_rotation | Binary: 1 if in Apple Music heavy rotation, 0 otherwise |
| recommendations | Binary: 1 if in Apple Music personal recommendations, 0 otherwise |
| lastfm_similar | Count of user's favorited artists that list this candidate in their Last.fm similar artists. Higher = more connections to existing taste. |
| lastfm_loved | Binary: 1 if this artist has loved tracks on user's Last.fm profile, 0 otherwise |

Note: `lastfm_similar` serves double duty. As a **signal feature**, it counts inbound similarity connections from known-good artists. As **graph edges**, the same similarity data enables affinity propagation. These are complementary uses — the feature captures "how connected is this artist to my taste" while the graph propagates specific feedback events.

## 3. Feedback Collection

### When

After each listening round, the user runs a post-listen command (same workflow as current wargaming).

### Discovery playlist tracks (primary feedback)

The system snapshots skip counts, play counts, and favorite state before building the playlist, then compares after listening:

| What changed | Interpretation | Detection |
|---|---|---|
| Track favorited | Strong positive | Favorites snapshot diff |
| Skip count increased | Strong negative | Skip count snapshot diff (JXA `skippedCount` per track) |
| Play count increased, not favorited, not skipped | Listen-no-fave (slight negative) | Play count up, no fave, no new skips |
| Play count unchanged | Never listened — excluded from scoring | No signal either way |

Tracks the user never played are excluded entirely. "Not listened" is not negative feedback.

### Library-wide signals (passive collection)

Between rounds, normal library listening is also captured:
- New favorites on any artist update the affinity graph at full strength
- Skip patterns on library tracks do NOT feed into discovery scoring

### Per-artist aggregation

For artists offered in the discovery round:
```
fave_tracks = count of newly favorited tracks from this artist
skip_tracks = count of newly skipped tracks from this artist
listen_tracks = tracks with increased play count, not faved, not skipped
```

These map to the affinity graph injection strengths defined in Section 2.

## 4. Similarity Graph Construction

### Music-map (existing)

Already scraped for ~1100+ favorited artists. Returns proximity-based similarity. Stored in the scrape cache as `{artist: {similar_artist: proximity}}`.

Characteristics: Visual/cultural clustering. Good for genre neighborhoods. Limited to artists popular enough to appear on music-map. Some artists return nothing.

### Last.fm similar (new, nearly free)

`artist.getInfo` already returns a `similar.artist` array with match scores (0.0-1.0). We call this endpoint in `fetch_filter_data()` already — we just discard the similar artists data currently.

Characteristics: Collaborative filtering based on listener overlap. Broader coverage than music-map. Match score is pre-normalized.

### Merging strategy

Both sources kept as separate edge types with learned weights:

```
affinity(artist) = w_musicmap * propagation(musicmap_edges)
                 + w_lastfm * propagation(lastfm_edges)
```

Both `w_musicmap` and `w_lastfm` are learned weights. The model learns which source is more predictive overall.

### Graph properties

- **Nodes:** Every artist in the library (~1100) plus every candidate ever scored
- **Edges:** Sparse — each artist connects to ~20-50 similar artists per source
- **Size:** Small enough to hold in memory and propagate in milliseconds. No database needed.

### Building incrementally

- Seed from existing music-map cache on first run
- Last.fm similar edges added as a side-effect of `fetch_filter_data()` calls (already happening, just need to store the data)
- New artists encountered during scoring get edges added lazily
- Persist the graph to a JSON cache file between runs

## 5. System Architecture

### Candidate pool

Candidates come from the same source as today: **music-map scraping**. The existing scrape cache (~1100 seed artists, each returning ~20 similar artists) already contains thousands of candidate artists. The adaptive engine scores these candidates rather than ranking them by raw proximity. New candidates enter the pool as the similarity graph grows (Last.fm similar artists discovered during `fetch_filter_data()` calls are also added as candidates).

### Current flow (being replaced)

```
scrape music-map -> rank by proximity -> filter -> build playlist
```

### New flow

```
collect signals -> build/update similarity graph -> score all candidates ->
filter (manual blocklist/allowlist) -> build playlist ->
[user listens] -> collect feedback -> update weights + affinity graph -> repeat
```

### Module structure

| Module | Responsibility |
|--------|---------------|
| `music_discovery.py` | Library reading (JXA), scraping, AppleScript, playlist building — **unchanged** |
| `signal_collectors.py` | Signal collection (existing + new Last.fm signals) — **extended** |
| `adaptive_engine.py` | **New.** Weight learning, affinity graph, candidate scoring |
| `feedback.py` | **New.** Pre/post-listen snapshots, feedback extraction, history |
| `signal_experiment.py` | **Retired** for future rounds, kept for historical data access |

### Data flow

```
Library (JXA) -----> signal_collectors -----> features per artist
                                                    |
Music-map cache ----> similarity graph <---- Last.fm similar
                            |
Feedback history ----> affinity scores ----> adaptive_engine ----> ranked candidates
                                                    |
Prior weights -----> Bayesian update ---------------+
                                                    |
                                          filtered + playlist built
```

### Persistence (all JSON in ~/.cache/music_discovery/)

| File | Contents |
|------|----------|
| `adaptive_weights.json` | Learned signal weights + priors |
| `affinity_graph.json` | Similarity edges (both sources) + propagated scores |
| `feedback_history.json` | All rounds: per-track fave/skip/listen outcomes |
| `pre_listen_snapshot.json` | Skip counts + fave state before current round |

### Behavioral changes from current system

**Auto-block removed.** The `check_ai_artist()` metadata heuristic that auto-blocks artists based on Last.fm bio length / tag count / listener count is removed from the scoring pipeline. The adaptive model's negative feedback handles this naturally.

What stays:
- `ai_blocklist.txt` — manual blocklist, respected as a hard filter
- `ai_allowlist.txt` — manual allowlist, respected
- Both are manually curated only. No automatic additions.

**Artists can be re-offered.** The exclusion set that prevents re-offering prior artists is removed. If an artist's score rises back to the top, they get offered again. The feedback loop is the regulator — skipped artists sink, favorited artists may reappear (which is fine).

**Per-artist track cap.** Maximum 2 tracks per artist per playlist. Prevents large-catalog artists from dominating. Configurable.

## 6. Bootstrap and Migration

### Using existing data

**From wargaming experiment (3 rounds):**
- 32 favorites + ~283 non-favorites with known signal values — initial weight training
- Per-signal solo rankings — validates which signals were predictive

**From library (~1100 favorited artists):**
- Favorites counts per artist — seeds affinity graph (sqrt-scaled, recency-decayed)
- Play counts, playlist membership, ratings — pre-computed signal features
- Music-map cache — seeds similarity graph edges

**From Last.fm (new, collected on first run):**
- Similar artist edges from `artist.getInfo` responses — extends similarity graph
- Loved tracks (if username configured) — additional positive signal

### Migration path

1. **Seed mode (first run):** Collect all signals, build similarity graph from existing caches, train initial weights from wargaming data, compute affinity scores from library history. No playlist built — shows top-ranked candidates and learned weights for sanity checking.
2. **First adaptive playlist (second run):** Snapshots library state, builds playlist from adaptive ranking.
3. **First feedback loop (third run):** Collects feedback, updates weights + graph, builds next playlist. The system is now learning.

### Existing code

- `music_discovery.py` proximity-only ranking mode stays available but is no longer the default path. No code deleted.
- `signal_experiment.py` kept for historical data access. `post_listen_history.json` and `eval_manifest.json` are read during bootstrap.

## 7. Testing and Validation

### Unit tests

**Weight learning:**
- Bayesian update with known outcomes produces expected weight shifts
- Uniform priors + bootstrap data (32 positives, 283 negatives) converge to reasonable values
- All signals predicting the same thing — weights stay equal
- Single dominant signal — that weight rises, others fall

**Affinity graph:**
- Single favorite propagates correct strength through 1, 2, 3 hops with decay
- Sqrt scaling: 1 fave = 1.0, 10 faves = 3.2, 50 faves = 7.1
- Skip propagates negative at 0.7x strength
- Listen-no-fave stays local (-0.1, 1 hop max)
- Recency decay: old library favorites contribute less than recent ones
- Two similarity sources maintain separate edge weights

**Feedback collection:**
- Snapshot diff correctly identifies new favorites, new skips, listens-no-fave
- Tracks with no play count change excluded from scoring
- Per-artist aggregation: multi-fave and multi-skip computed correctly
- Library-wide favorites outside discovery playlist update affinity graph only

**Scoring:**
- Per-artist track cap enforced (2 max)
- Manual blocklist/allowlist respected as hard filters
- Artists can appear in multiple rounds (no exclusion set)
- Score combines weight-learned signal score + affinity graph score

### Integration test

Simulated multi-round test with synthetic data:
- Round 1: Offer 20 artists with known signal profiles, simulate 3 favorites from a "metal" cluster
- Round 2: Verify metal-adjacent artists rose in ranking, non-metal fell
- Round 3: Simulate 2 favorites from a "jazz" cluster, verify model adapts to second taste dimension
- Verify weights shift toward signals that predicted the favorites
- Verify affinity graph shows hot zones around favorited neighborhoods

### Live sanity check (seed mode)

Before building the first real playlist, the seed run outputs:
- Top 50 ranked candidates with scores and contributing signals
- Learned weights from bootstrap data
- Hottest affinity graph neighborhoods
- User eyeballs it: "do these look like artists I'd actually want to hear?"

## 8. Scope

### v1 (this implementation)

- Adaptive scoring engine with Bayesian weight learning (8 signals)
- Affinity graph with dual similarity sources (music-map + Last.fm)
- Feedback collection: favorites, skips, listen-no-fave from discovery playlists
- Sqrt scaling for multi-fave, recency decay for old library data
- Per-artist track cap (2 per playlist)
- Manual blocklist/allowlist only (no auto-block)
- Artists can be re-offered
- Bootstrap from wargaming data + library history
- Seed mode for sanity checking before first real playlist
- Last.fm username in `.env` for loved tracks signal

### Explicitly deferred

| Feature | Reason |
|---------|--------|
| Per-genre similarity source weighting | Global weights first, see if sufficient |
| Play-through rate as a signal | Let weight learner handle playcount noise for now |
| Active learning (offer uncertain artists) | Optimization on top of working system |
| Class S star ratings redesign | Extended ratings formula parked pre-wargaming, still parked |
| GUI / web interface | CLI-first, works fine for the workflow |
| Multi-user support | Single-user system |
| Real-time feedback (skip detection during playback) | Post-listen batch is simpler and sufficient |
| Automatic playlist size tuning | Fixed size, user adjusts manually |

### Retired from current system

| What | Status |
|------|--------|
| Signal wargaming fixed configs | Replaced by adaptive weights |
| Manual A/B testing rounds | Replaced by feedback loop |
| `check_ai_artist()` auto-block | Removed from pipeline, manual lists stay |
| "Never re-offer" exclusion rule | Removed, feedback regulates instead |
| Proximity-only ranking | Kept but unused, new adaptive path is default |
