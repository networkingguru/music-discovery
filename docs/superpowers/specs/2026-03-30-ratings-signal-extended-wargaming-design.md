# Star Ratings Signal & Extended Wargaming Design

**Date:** 2026-03-30
**Status:** Draft

## Problem

The signal wargaming experiment's first post-listen round produced only n=9 new favorites — insufficient to statistically distinguish between weight configurations. Additionally, star ratings (a rich signal available on 97.5% of library tracks across 4,454 artists) are not yet used, despite being potentially the strongest indicator of user preference.

## Goals

1. Add star ratings as a new signal in the wargaming framework
2. Extend the experiment to accumulate results across multiple listening sessions until statistical significance is reached (n>=30-50)
3. Ensure fair signal representation in evaluation playlists via stratified sampling
4. Deduplicate artists across sessions so rejected artists are not re-offered
5. Preserve all per-config data so results can inform different users' tuning

## Non-Goals

- Replacing favorites with ratings (they coexist; ablation measures overlap)
- Changing the main `music_discovery.py` script
- Building a GUI or user-facing dashboard

---

## Ratings Signal Design

### Collector: `collect_ratings_jxa()`

Lives in `signal_collectors.py`. Bulk-reads `rating()` and `artist()` from all library tracks via JXA, following the existing playcount collector pattern.

**Centering formula:** `(star - 3) / 2`

| Stars | Centered Value | Meaning |
|:-----:|:--------------:|---------|
| 5     | +1.0           | Love |
| 4     | +0.5           | Strong positive |
| 3     |  0.0           | Tolerable/neutral |
| 2     | -0.5           | Negative |
| 1     | -1.0           | Strong negative |
| 0     |  0.0           | Unrated (treated as neutral) |

**Per-artist output:** `{artist_lowercase: {"avg_centered": float, "count": int}}`

- `avg_centered`: mean of centered values across all tracks (including unrated as 0.0)
- `count`: total number of tracks for that artist (rated + unrated)

Cached to `ratings_cache.json` in the cache directory.

### Scoring Integration

In `compute_seed_weight` (`signal_scoring.py`), ratings uses:

```
rating_value = avg_centered * sqrt(log(track_count + 1))
```

This matches the existing `compute_signal_value` pattern (log-scaled confidence boost) but allows negative values. A negative seed weight causes candidates similar to that artist to be penalized in `score_candidates_multisignal`, using the same proximity-weighted mechanism that already exists.

**Signal classification:** Continuous (like favorites, playcount, playlists), not binary (like heavy_rotation, recommendations). Can produce negative values — unique among signals.

---

## Extended Wargaming Experiment

### New Phase D Configurations

Added to the existing 5 configs (which remain for data continuity):

| Config | ratings | favorites | playcount | playlists | heavy_rotation | recommendations |
|--------|:-------:|:---------:|:---------:|:---------:|:--------------:|:---------------:|
| Ratings-Heavy | 1.0 | 0.3 | 0.3 | 0.1 | 0.1 | 0.1 |
| Ratings+Favorites Blend | 0.8 | 0.8 | 0.3 | 0.2 | 0.2 | 0.2 |

### New Phase C Degraded Scenario

- `jxa_full`: favorites=1.0, playcount=1.0, playlists=1.0, ratings=1.0, API signals=0.0 — tests JXA stack at full strength including ratings

### Phase A & B

No code changes needed. These phases iterate over all signals in the dict, so ratings is automatically profiled solo (Phase A) and ablated (Phase B).

---

## Stratified Eval Playlist Builder

### Problem with Current Approach

The current builder takes the union of top-80 from each blended config. This over-represents signals that dominate multiple configs (e.g., favorites) and under-represents signals with unique contributions.

### Stratified Sampling Design

The eval playlist is built in two strata:

**Stratum 1 — Signal-fair solo slots (Phase A):**
- For each of the 6 signals, take top N unique artists from that signal's Phase A solo ranking
- N is equal across all signals (e.g., 13 each = ~78 slots)
- Artists already in library/blocklist are skipped (pull deeper)
- If a signal's pool runs dry, remaining slots go to the next signal with available artists

**Stratum 2 — Blended config slots (Phase D):**
- Fill remaining slots (~25-30) from the blended configs' ranked lists
- Deduplicate against Stratum 1
- Round-robin across configs to avoid any single config dominating

**Target:** 100-105 artists successfully added to playlist (not just attempted — keep pulling from deeper in rankings until target is met per stratum).

### Manifest File: `eval_playlist_manifest.json`

```json
{
  "sessions": [
    {
      "date": "2026-03-30",
      "session_id": 1,
      "artists": [
        {"name": "artist name", "stratum": "solo:ratings", "rank": 5, "added": true},
        {"name": "artist name", "stratum": "blend:Ratings-Heavy", "rank": 12, "added": true},
        {"name": "artist name", "stratum": "solo:playcount", "rank": 8, "added": false}
      ]
    }
  ]
}
```

---

## Cross-Session Deduplication

On each `--build-playlist` run:
1. Load the manifest
2. Collect all artists from prior sessions (both successfully added and failed-to-add)
3. Exclude them from candidate pools before stratified sampling
4. This means each session draws from progressively deeper rankings
5. Later sessions test whether signals' deeper recommendations are still good

---

## Accumulative Post-Listen Scoring

### History File: `post_listen_history.json`

```json
{
  "rounds": [
    {
      "date": "2026-03-30",
      "session_id": 1,
      "new_favorites": ["artist a", "artist b"],
      "per_config_hits": {
        "Favorites-Heavy": {"hits": 3, "pool_size": 80, "matched": ["artist a"]}
      },
      "per_signal_solo_hits": {
        "ratings": {"hits": 2, "pool_size": 13, "matched": ["artist a", "artist b"]}
      }
    }
  ],
  "cumulative": {
    "total_new_favorites": 15,
    "per_config": {"Favorites-Heavy": {"hits": 5, "pool_size": 160}},
    "per_signal_solo": {"ratings": {"hits": 4, "pool_size": 26}}
  }
}
```

### Scoring Logic

Post-listen scoring evaluates each new favorite against:
1. **The manifest** — which stratum/signal originally surfaced this artist?
2. **Per-config ranked lists** — where did each config rank this artist?
3. **Per-signal solo lists** — which signal would have found this artist alone?

### Automatic Statistical Test

When cumulative `total_new_favorites >= 30`:
- Run Fisher's exact test (or chi-squared if cells are large enough) comparing hit rates across configs
- Report p-values and flag any config that is statistically distinguishable (p < 0.05)
- Also report per-signal solo hit rates for signal-level insight
- Output: "Config X is statistically the best for you (p=0.03)" or "No config is yet distinguishable (p=0.15, need more data)"

---

## File Changes Summary

| File | Change |
|------|--------|
| `signal_collectors.py` | Add `collect_ratings_jxa()` |
| `signal_scoring.py` | Handle `ratings` signal in `compute_seed_weight` (allows negative) |
| `signal_analysis.py` | Add Ratings-Heavy and Ratings+Favorites Blend configs to Phase D; add `jxa_full` scenario to Phase C |
| `signal_experiment.py` | Wire ratings into collection/caching; stratified playlist builder; manifest tracking with cross-session dedup; accumulative post-listen scoring with statistical test |
| `signal_report.py` | Add `ratings` to display name map; cumulative stats section in post-listen output |
| New: `eval_playlist_manifest.json` (in cache dir) | Tracks offered artists, source stratum, session history |
| New: `post_listen_history.json` (in cache dir) | Accumulates per-session results |

---

## Expected Session Plan

1. Run `signal_experiment.py` (full run with ratings) — generates new wargaming report + stratified eval artist list
2. Run `signal_experiment.py --build-playlist` — builds ~100 artist eval playlist with stratified sampling
3. Listen, favorite what you like
4. Run `signal_experiment.py --post-listen` — scores and appends to history
5. Repeat steps 2-4 until statistical significance reached (estimated 4-6 sessions)
6. Pick winning config for your production weights
