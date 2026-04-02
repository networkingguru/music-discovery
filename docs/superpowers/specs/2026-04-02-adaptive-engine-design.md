# Adaptive Music Discovery Engine — Design Spec

**Date:** 2026-04-02
**Status:** Draft (post-review revision)
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

### Signals (9 total)

| Signal | Source | Status |
|--------|--------|--------|
| favorites | Music.app (JXA) | Existing |
| playcount | Music.app (JXA) | Existing |
| playlists | Music.app (JXA) | Existing |
| ratings | Music.app (JXA) | Existing |
| heavy_rotation | Apple Music API | Existing |
| recommendations | Apple Music API | Existing |
| lastfm_similar | Last.fm `artist.getInfo` | **New** — data already returned by API, just unused |
| lastfm_loved | Last.fm `user.getLovedTracks` | **New** — needs username in `.env`; excluded from model if unconfigured |
| ai_heuristic | Last.fm metadata | **Repurposed** — existing `check_ai_artist()` scores fed as soft signal |

If the Last.fm username is not configured, `lastfm_loved` is excluded from the feature vector entirely (not fed as zeros).

## 2. Mathematical Model

Two complementary systems that combine into a final score via a mixing parameter.

### Signal Weight Learning (L2-Regularized Logistic Regression)

Each signal gets a learned weight. The model predicts the probability an artist is a hit:

```
P(favorite | artist) = sigmoid(b + w1*x1 + w2*x2 + ... + wN*xN)
```

where `b` is a bias/intercept term (essential given the ~1:9 class imbalance — base rate ~10%).

- **Method:** L2-regularized logistic regression (scikit-learn `LogisticRegression` with `class_weight='balanced'`). Refitted from scratch each round on all accumulated labeled data. With ~300 examples and 9 features, this runs in sub-millisecond.
- **Why not incremental Bayesian:** With only ~3-5 new positives per round, incremental Bayesian updates barely move a 9-parameter posterior. Refitting from scratch on all data is fast and statistically superior at this scale.
- The 3 existing wargaming rounds (32 positives, ~283 negatives) provide the initial training set.

### Affinity Graph (Taste Propagation)

A graph where nodes are artists and edges come from similarity data (music-map + Last.fm similar). Feedback propagates through it:

| Feedback | Injection strength | Propagation |
|----------|-------------------|-------------|
| Single favorite | +1.0 | Decays per hop (x0.4, max 3 hops) |
| Multi-fave artist | +1.0 * sqrt(count) — caps ~7.1 at 50 faves | Same decay |
| Skip (discovery track) | -0.7 (attenuated: see below) | Same decay structure |
| First listen, no fave | 0.0 (neutral) | No propagation |
| 2nd+ listen, no fave | -0.1 per occurrence, accumulates to max -0.5 | Starts propagating at 2+ (2 hops) |

**Skip attenuation for small samples:** When only 1-2 tracks were offered from an artist, skip injection is scaled by `min(tracks_offered, 3) / 3`. This prevents a single bad track pick from condemning an artist and poisoning their graph neighborhood. At 3+ tracks offered, full -0.7 applies.

**Recency weighting:** Exponential decay: `recency_factor = exp(-lambda * days_since_event)`.
- **Library data:** lambda = ln(2)/180 (half-life 180 days). Old favorites still contribute but at reduced strength.
- **Discovery round feedback:** lambda = ln(2)/90 (half-life 90 days). More responsive to recent taste shifts.
- Library favorites use `dateAdded` from JXA (proxy for when the user engaged with the artist; see Known Limitations). Discovery feedback uses the round date.

### Final Score (Two-Channel Combination)

The logistic model and affinity graph are combined post-hoc, not nested:

```
final_score = alpha * sigmoid(b + w · features) + (1 - alpha) * normalized_affinity
```

where `alpha` is a single mixing parameter, initialized at 0.5 and tunable. This avoids the label leakage problem of feeding affinity as a feature into the model (since affinity is derived from the same feedback events that generate training labels).

The two affinity sources are computed separately:

```
affinity(artist) = w_mm * propagation(musicmap_edges) + w_lfm * propagation(lastfm_edges)
```

`w_mm` and `w_lfm` are exposed as two separate features in the logistic model (replacing the single `w_affinity`), OR kept as the post-hoc combination weights. Implementation will start with post-hoc (simpler) and promote to features if cross-validation shows benefit.

### Feature Normalization

Raw signal values have vastly different scales (favorites: 1-50+, playcount: 1-10000+, ratings: -1 to +1). All features are z-score normalized: `normalized = (value - mean) / std`.

**Critical:** Normalization statistics are computed across the **full accumulated training set** (all rounds combined), not recomputed per round from the current candidate pool. Raw feature values are stored in feedback history so that retraining always uses consistent normalization. This prevents learned weights from becoming non-stationary across rounds.

### Signal Feature Definitions

Candidate artists are mostly unknown to the user. Most library-based signals (favorites, playcount, playlists, ratings) will be zero for them. The features that actually differentiate candidates are:

| Signal | Feature value for candidate artist | Notes |
|--------|-----------------------------------|-------|
| favorites | Proximity-weighted sum from seed artists | Aggregate from library, not per-candidate raw count |
| playcount | Proximity-weighted sum from seed artists | Same aggregation |
| playlists | Proximity-weighted sum from seed artists | Same aggregation |
| ratings | Proximity-weighted average from seed artists | Same aggregation |
| heavy_rotation | Binary: 1 if in Apple Music heavy rotation, 0 otherwise | Direct |
| recommendations | Binary: 1 if in Apple Music recommendations, 0 otherwise | Direct |
| lastfm_similar | Count of user's favorited artists that list this candidate as similar | Direct — higher = more connections to existing taste |
| lastfm_loved | Binary: 1 if artist has loved tracks on user's Last.fm profile | Direct; excluded if no username configured |
| ai_heuristic | Soft score from existing AI detection (bio length, tag count, listeners) | Continuous 0-1; lets model learn how much to trust the heuristic |

The first four signals use proximity-weighted aggregation: for a candidate artist C, the feature value is `sum(seed_signal[S] * proximity(S, C))` across seed artists S. This preserves the current system's core insight (similar-to-loved-artists) while letting the model learn which seed signals matter most.

### Mixed Feedback Aggregation

When an artist has both favorites and skips in the same round:

```
net_injection = sqrt(fave_count) * 1.0 - skip_count * 0.7 - listen_no_fave_count * 0.1
```

If net is positive, propagate as positive through the graph. If negative, propagate as negative. The sign determines the direction; the magnitude determines the strength.

## 3. Feedback Collection

### When

After each listening round, the user runs a feedback command (see Section 5.5 for CLI interface).

### Discovery playlist tracks (primary feedback)

The system snapshots per-track data (keyed by artist+title) **for discovery playlist tracks only** before building the playlist, then compares after listening:

| What changed | Interpretation | Detection |
|---|---|---|
| Track favorited | Strong positive | Favorites snapshot diff |
| Skip count increased | Strong negative | Skip count snapshot diff (JXA `skippedCount` — verified working) |
| Play count increased, not favorited, not skipped | Listen-no-fave | Play count up, no fave, no new skips |
| Play count unchanged | Never listened — excluded from scoring | No signal either way |

Tracks the user never played are excluded entirely. "Not listened" is not negative feedback.

**First-listen neutrality:** A single listen without favoriting scores 0.0 (neutral), not negative. Only 2+ listens without favoriting on the same artist trigger the -0.1 "meh" signal. Most discovery tracks are heard once — treating that as negative would systematically penalize artists that need a second chance.

### Library-wide signals (passive collection)

Between rounds, normal library listening is also captured:
- New favorites on any artist update the affinity graph at full strength
- Skip patterns on library tracks do NOT feed into discovery scoring

### Per-artist aggregation

For artists offered in the discovery round:
```
fave_tracks = count of newly favorited tracks from this artist
skip_tracks = count of newly skipped tracks from this artist
listen_tracks = tracks with increased play count, not faved, not skipped (2+ = meh)
```

These map to the affinity graph injection strengths and mixed feedback formula defined in Section 2.

### Idempotency

Each feedback collection run is tagged with a round ID. Running feedback twice for the same round is a no-op — the system checks if the round ID already exists in `feedback_history.json` and refuses to double-count. After collecting feedback, the snapshot is replaced with current state so the next round diffs against post-feedback state.

### Known Limitations

**Multi-device sync:** If the user listens on iPhone/iPad/CarPlay, play counts sync via iCloud Music Library but not instantly (minutes to hours of lag). Running feedback before sync completes will misclassify genuinely-listened tracks as "never listened." Mitigation: wait for sync before running feedback, or use the `--rescan` flag to update a prior round's feedback if sync catches up later.

**Partial listens:** A track played for 15-30 seconds then abandoned (pause, not skip) may not increment either `playedCount` or `skippedCount`. These fall into "never listened" and are excluded. This is a known gap — the system loses weak negative signal from brief abandons. Acceptable for v1.

**`dateAdded` as recency proxy:** JXA's `dateAdded` is when a track was added to the library, not when it was favorited. Bulk-imported tracks share the same date regardless of when they were individually favorited. This makes recency decay approximate for old library data. Discovery round feedback (which uses round dates) is unaffected.

## 4. Similarity Graph Construction

### Music-map (existing)

Already scraped for ~1100+ favorited artists. Returns proximity-based similarity. Stored in the scrape cache as `{artist: {similar_artist: proximity}}`.

Characteristics: Visual/cultural clustering. Good for genre neighborhoods. Limited to artists popular enough to appear on music-map. Some artists return nothing.

### Last.fm similar (new, nearly free)

`artist.getInfo` already returns a `similar.artist` array with match scores (0.0-1.0). We call this endpoint in `fetch_filter_data()` already — we just discard the similar artists data currently.

Characteristics: Collaborative filtering based on listener overlap. Broader coverage than music-map. Match score is pre-normalized.

**One-time seed cost:** To compute the `lastfm_similar` signal for candidates, we need Last.fm similar-artist data for all ~1100 library artists. This requires ~1100 API calls during seed mode (at 1/sec rate limit = ~18 minutes). Subsequent runs only need calls for new artists. This data is cached in the similarity graph.

### Merging strategy

Both sources kept as separate edge types. The model learns which source is more predictive:

```
affinity(artist) = w_mm * propagation(musicmap_edges) + w_lfm * propagation(lastfm_edges)
```

### Graph properties

- **Nodes:** Library artists (~1100) + scored candidates (grows over time)
- **Edges:** Sparse — each artist connects to ~20-50 similar artists per source
- **Size:** Small enough to hold in memory. No database needed.

### Building incrementally

- Seed from existing music-map cache + Last.fm similar data collected in seed mode
- New artists encountered during scoring get edges added lazily via `fetch_filter_data()`
- Persist topology to a JSON cache file between runs

### Graph pruning

To prevent unbounded growth: periodically prune nodes with no feedback, no library connection, and affinity score below a threshold (e.g., |affinity| < 0.01). Pruning runs at the end of each feedback round. Only topology is persisted; propagated scores are recomputed on load.

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
| `music_discovery.py` | Library reading (JXA), scraping, AppleScript, playlist building — **minor changes** (see below) |
| `signal_collectors.py` | Signal collection (existing + new Last.fm signals) — **extended** |
| `adaptive_engine.py` | **New.** Entry point, weight learning, affinity graph, candidate scoring, CLI |
| `feedback.py` | **New.** Pre/post-listen snapshots, feedback extraction, history |
| `signal_experiment.py` | **Retired** for future rounds, kept for historical data access |

**Changes to `music_discovery.py`:**
- `fetch_filter_data()`: extract and return Last.fm similar artist data from `artist.getInfo` response (currently discarded)
- `parse_library_jxa()`: optionally return `dateAdded` and `skippedCount` per track (new JXA fields)
- `check_ai_artist()`: stays as-is but is called by `adaptive_engine.py` to compute the soft `ai_heuristic` feature, not as a hard filter
- `main()`: **unchanged** — the adaptive engine has its own entry point

### Call graph

```
adaptive_engine.py  (entry point, CLI)
  ├── signal_collectors.py  (collect features)
  │     └── music_discovery.py  (JXA reads, Last.fm API)
  ├── feedback.py  (snapshot, diff, history)
  │     └── music_discovery.py  (JXA reads for skip/play counts)
  └── music_discovery.py  (playlist building, blocklist filtering)
```

No circular dependencies. `adaptive_engine.py` orchestrates; `music_discovery.py` is a leaf dependency providing library access and playlist mechanics.

### Data flow

```
Library (JXA) -----> signal_collectors -----> features per artist
                                                    |
Music-map cache ----> similarity graph <---- Last.fm similar
                            |                       |
Feedback history ----> affinity scores         model score
                            |                       |
                            +--------> final_score = alpha * model + (1-alpha) * affinity
                                              |
                                    filtered + playlist built
```

### Persistence (all JSON in ~/.cache/music_discovery/)

| File | Contents | Version |
|------|----------|---------|
| `adaptive_weights.json` | Learned signal weights, bias, alpha, training metadata | v1 |
| `affinity_graph.json` | Similarity edges (both sources), topology only | v1 |
| `feedback_history.json` | All rounds: per-track raw features + fave/skip/listen outcomes, round IDs | v1 |
| `pre_listen_snapshot.json` | Per-track skip counts + play counts + fave state for discovery playlist tracks | v1 |
| `artist_overrides.json` | Manual score pins and feedback expunges (see Section 5.4) | v1 |

All files include a `"schema_version": 1` field. On load, version mismatch triggers a migration or warning.

### 5.4 Manual Overrides

The user can course-correct when the model makes mistakes:

**`artist_overrides.json`:**
```json
{
  "pins": {
    "artist name": +1.0  // force to top (or -1.0 to suppress)
  },
  "expunged_feedback": [
    {"round_id": "2026-04-05", "artist": "artist name", "reason": "bad track picks"}
  ]
}
```

- **Pins** override the final score for specific artists. A positive pin forces the artist into the next playlist; a negative pin suppresses them without blocklisting their neighbors.
- **Expunged feedback** removes a specific artist's feedback from a specific round and triggers affinity graph recomputation. This undoes a bad skip event that has poisoned a graph neighborhood.

Both are manually edited text files, consistent with the blocklist/allowlist pattern.

### 5.5 CLI Interface

Two commands per round, plus a one-time seed:

```bash
# One-time setup: collect data, build graph, train initial model, show sanity check
python adaptive_engine.py --seed

# Each round: snapshot + score + build playlist
python adaptive_engine.py --build

# After listening: collect feedback + update model
python adaptive_engine.py --feedback

# Re-scan a prior round if iCloud sync was slow
python adaptive_engine.py --feedback --rescan <round_id>
```

### Behavioral changes from current system

**Auto-block repurposed as soft signal.** The `check_ai_artist()` heuristic is no longer a hard filter. Instead, its score feeds into the model as the `ai_heuristic` feature. The model learns how much to trust it. Manual blocklist/allowlist remain as hard filters.

**Artists can be re-offered, with cooldown.** The permanent exclusion set is removed. However, artists that were offered and received neutral-to-negative feedback (not favorited) enter a cooldown: not re-offered for 3 rounds or 30 days, whichever is shorter. Favorited artists can reappear immediately (with different tracks). Artists that rise above their cooldown via strong graph affinity can break out early.

**Per-artist track cap.** Maximum 2 tracks per artist per playlist. Prevents large-catalog artists from dominating. This is a playlist-building concern, not a scoring concern — the model scores artists, the playlist builder enforces the cap.

**Default playlist size.** 50 artists per round (up to 100 tracks at 2 per artist). Smaller than wargaming's 105 to accelerate the feedback loop in early rounds. Configurable.

### Per-Round Explanation Output

Every `--build` run emits a companion report alongside the playlist:

```
~/.cache/music_discovery/playlist_explanation.txt
```

For each artist in the playlist:
- Final score and rank
- Top 3 contributing signals with weights
- Affinity source (which favorited artist's neighborhood brought them in)
- Strongest graph path (e.g., "Dream Theater → Symphony X → this artist")

This is the user's window into why the model made each recommendation. Available every round, not just seed mode.

## 6. Bootstrap and Migration

### Using existing data

**From wargaming experiment (3 rounds):**
- 32 favorites + ~283 non-favorites provide labeled artist names
- Feature vectors must be **reconstructed** from existing signal caches (playcount_cache.json, etc.) — the wargaming data does not store per-artist feature vectors directly
- The two new signals (`lastfm_similar`, `ai_heuristic`) are set to 0.0 for all bootstrap examples (they were not available during wargaming). `lastfm_loved` is excluded if no username configured.
- This reconstruction introduces minor look-ahead bias (current signal values vs. values at wargaming time). Acceptable for initialization — live feedback corrects within a few rounds.

**From library (~1100 favorited artists):**
- Favorites counts per artist — seeds affinity graph (sqrt-scaled, recency-decayed)
- Play counts, playlist membership, ratings — pre-computed signal features for proximity-weighted aggregation
- Music-map cache — seeds similarity graph edges

**From Last.fm (collected in seed mode):**
- Similar artist edges for all library artists (~1100 API calls, ~18 minutes one-time)
- Loved tracks (if username configured) — additional positive signal

### Migration path

1. **Seed mode (`--seed`):** Collect all signals, collect Last.fm similar data for library artists, build similarity graph, reconstruct bootstrap feature vectors, train initial model, compute affinity scores from library history. Outputs top 50 candidates + learned weights + hottest neighborhoods for sanity checking. No playlist built.
2. **First adaptive playlist (`--build`):** Snapshots library state (per-track for discovery tracks), scores candidates, builds playlist.
3. **First feedback loop (`--feedback` then `--build`):** Collects feedback, updates model + graph, builds next playlist. The system is now learning.

### Existing code

- `music_discovery.py` proximity-only ranking mode stays available via the existing `main()`. No code deleted.
- `signal_experiment.py` kept for historical data access. `post_listen_history.json` and `eval_manifest.json` are read during bootstrap.

## 7. Testing and Validation

### Unit tests

**Weight learning:**
- L2 logistic regression with known outcomes produces expected weight direction
- Balanced class weights handle the 1:9 imbalance correctly
- Bootstrap data (32 positives, 283 negatives) produces non-trivial weights (not all near zero)
- Single dominant signal — that weight rises, others fall
- Bias term is negative (reflecting ~10% base rate)

**Affinity graph:**
- Single favorite propagates correct strength through 1, 2, 3 hops with x0.4 decay
- Sqrt scaling: 1 fave = 1.0, 10 faves = 3.2, 50 faves = 7.1
- Skip propagates negative at 0.7x strength, attenuated by sample size
- First listen-no-fave is neutral (0.0); 2nd+ is -0.1
- Mixed feedback aggregation: net injection formula produces correct sign and magnitude
- Recency decay: separate half-lives for library (180d) vs discovery (90d)
- Two similarity sources maintain separate edge weights
- Graph pruning removes cold nodes correctly

**Feedback collection:**
- Snapshot diff correctly identifies new favorites, new skips, listens-no-fave
- Tracks with no play count change excluded from scoring
- Per-artist aggregation: multi-fave and multi-skip computed correctly
- Library-wide favorites outside discovery playlist update affinity graph only
- Idempotency: running feedback twice for same round is a no-op
- Snapshot is scoped to discovery playlist tracks only

**Scoring:**
- Per-artist track cap enforced (2 max) at playlist-building layer, not scoring layer
- Manual blocklist/allowlist respected as hard filters
- Cooldown enforced for non-favorited offered artists (3 rounds / 30 days)
- Artist overrides (pins) respected
- Expunged feedback triggers graph recomputation
- Final score = alpha * model + (1-alpha) * affinity, not nested
- Missing Last.fm username excludes lastfm_loved signal entirely

### Integration test

Simulated multi-round test with synthetic data:
- Round 1: Offer 20 artists with known signal profiles, simulate 3 favorites from a "metal" cluster
- Round 2: Verify metal-adjacent artists rose in ranking, non-metal fell
- Round 3: Simulate 2 favorites from a "jazz" cluster, verify model adapts to second taste dimension
- Verify weights shift toward signals that predicted the favorites
- Verify affinity graph shows hot zones around favorited neighborhoods
- Verify cooldown prevents re-offering round 1 non-favorites in round 2
- Verify explanation output correctly attributes recommendations

### Live sanity check (seed mode)

Before building the first real playlist, the seed run outputs:
- Top 50 ranked candidates with scores and contributing signals
- Learned weights from bootstrap data
- Hottest affinity graph neighborhoods
- User eyeballs it: "do these look like artists I'd actually want to hear?"

## 8. Scope

### v1 (this implementation)

- Adaptive scoring engine with L2-regularized logistic regression (9 signals)
- Affinity graph with dual similarity sources (music-map + Last.fm)
- Two-channel scoring: model score + affinity score combined post-hoc
- Feedback collection: favorites, skips, listen-no-fave from discovery playlists
- Sqrt scaling for multi-fave, separate recency decay for library vs discovery
- Per-artist track cap (2 per playlist), default 50 artists per round
- Manual blocklist/allowlist as hard filters, AI heuristic as soft signal
- Artists can be re-offered after cooldown (3 rounds / 30 days)
- Manual overrides: artist pins and feedback expunge
- Per-round explanation output
- Bootstrap from wargaming data + library history
- Seed mode for sanity checking before first real playlist
- Last.fm username in `.env` for loved tracks signal (graceful exclusion if missing)
- Schema versioning on all cache files

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
| Promoting affinity sources to model features | Start post-hoc, promote if cross-validation shows benefit |

### Retired from current system

| What | Status |
|------|--------|
| Signal wargaming fixed configs | Replaced by adaptive weights |
| Manual A/B testing rounds | Replaced by feedback loop |
| `check_ai_artist()` as hard filter | Repurposed as soft `ai_heuristic` signal |
| "Never re-offer" exclusion rule | Replaced by cooldown mechanism |
| Proximity-only ranking | Kept but unused, new adaptive path is default |
