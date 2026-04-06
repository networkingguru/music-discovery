# Seed Injection for Favorited Discovery Artists

**Date:** 2026-04-06
**Issue:** networkingguru/music-discovery#11

## Problem

When a user favorites a track from the discovery playlist, that artist should become a new seed node — scraped on music-map, similar artists added as candidates, edges injected into the affinity graph. None of this happens today:

1. Neither `--feedback` nor `--build` scrapes newly favorited discovery artists. The scrape cache is loaded but never updated after `--seed`.
2. `all_candidates` in `_run_build()` is built from the existing scrape cache only. New favorites can't expand the candidate pool.
3. Favorited discovery artists are already injected through two paths (step 10 bulk library injection + step 10b feedback replay), which is sufficient signal. The guard at line 1493 correctly prevents a third injection at step 12.

Running rounds without seed expansion means the model trains on feedback it can't act on. The candidate pool never grows and feedback data accumulates noise without signal.

## Design

### Change 1: Scrape new favorites in `_run_feedback()`

**Where:** `adaptive_engine.py:_run_feedback()`, after feedback replay (step 10b) and before `graph.save()`. Extracted into a helper function `_scrape_new_favorites()` for testability.

**New imports needed in `_run_feedback()`:** `detect_scraper`, `load_cache`, `save_cache`, `fetch_filter_data` from `music_discovery`.

**Cache paths:** Use `cache_dir / "music_map_cache.json"` and `cache_dir / "filter_cache.json"` directly (consistent with how `_run_feedback` already constructs paths).

**Logic:**

1. Identify newly favorited discovery artists:
   - Collect all offered artists: union of `artist_feedback` keys across all rounds in feedback history
   - Intersect with current library favorites (`favorites` dict, already collected at line 1392)
   - Exclude artists already a key in the scrape cache. Use case-insensitive comparison: `artist.lower() not in {k.lower() for k in scrape_cache}`
   - Cap at 10 artists per feedback run to bound runtime (~10-20 seconds of scraping)

2. For each newly favorited discovery artist:
   - Detect scraper method via `detect_scraper()` (called once, reused for all artists)
   - Scrape music-map.com for similar artists → returns `{neighbor: proximity}`
   - Add result to `scrape_cache[artist]`
   - Add edges to graph via `graph.add_edge_musicmap(artist.lower(), neighbor.lower(), weight)` for each neighbor (lowercase to match graph conventions)
   - Fetch Last.fm data via `fetch_filter_data(artist, api_key)` if API key available
   - Extract similar artists: `entry.get("similar_artists", [])`, filter to `match > 0`
   - Add Last.fm edges via `graph.add_edge_lastfm(artist.lower(), sim_name.lower(), match_score)` (mirrors `_run_seed` pattern at lines 470-481)
   - Update `filter_cache[artist]` with the fetched data
   - Rate-limit at 1 request/sec (consistent with existing scraping behavior)

3. After all artists processed:
   - Save scrape cache to disk (single batch write, not per-artist)
   - Save filter cache to disk
   - `graph.propagate()` and `graph.save()` that already follow will persist the new edges

4. **Keep the `discovery_artists` guard at line 1493.** Favorited discovery artists already receive signal through step 10 (bulk library favorites injection with `LIBRARY_HALF_LIFE_DAYS = 180`) and step 10b (feedback replay with `DISCOVERY_HALF_LIFE_DAYS = 90`). The guard prevents triple-counting. The operationally important change is persisting new edges and scrape cache — propagation during feedback is for validation/logging only; the next `--build` will propagate over the updated graph.

**User-visible logging:**
```
Detected 3 newly favorited discovery artists: deftones, caligula's horse, agent fresco
  Scraping music-map for deftones... found 24 similar artists
  Scraping music-map for caligula's horse... found 18 similar artists
  Scraping music-map for agent fresco... found 21 similar artists
  Candidate pool expanded: 312 → 375 artists
```

### Change 2: No changes to `_run_build()`

`_run_build()` already:
- Loads `scrape_cache = load_cache(paths["cache"])`
- Derives `all_candidates` from scrape cache neighbors
- Loads the affinity graph for scoring

Since feedback updates the scrape cache and graph, build automatically picks up new neighbors as candidates. No code change required.

### Change 3: `--reset` flag

A new CLI flag `--reset` on `adaptive_engine.py`, added to the existing mutually exclusive group (`--seed`, `--build`, `--feedback`, `--reset`).

**Deletes:**
- `feedback_history.json` — all round feedback data
- `model_weights.json` — trained model weights
- `affinity_graph.json` — the full graph
- `pre_listen_snapshot.json` — current snapshot
- `library_faves_snapshot.json` — library favorites baseline
- `offered_features.json` — per-round feature vectors
- `search_strikes.json` — search failure tracking
- `weight_model.json` — legacy model file
- `playlist_explanation.txt` — stale explanation from last build

**Preserves:**
- `offered_tracks.json` — cross-round dedup prevents re-serving tracks the user already evaluated
- `music_map_cache.json` — expensive to rebuild (hundreds of scrape requests)
- `filter_cache.json` — Last.fm metadata cache
- `ai_detection_log.txt` — audit trail
- Signal caches: `playcount_cache.json`, `ratings_cache.json`, `playlist_membership_cache.json`, `heavy_rotation_cache.json`, `recommendations_cache.json`
- `apple_music_cache.json` — Apple Music API cache
- `Library.xml` — library export

**Behavior:** Prints a summary of what is being deleted (number of feedback rounds, number of artists evaluated), then each deleted file, then reminds user to run `--seed`. Handles missing files gracefully (skip and continue).

## Files Modified

| File | Change |
|------|--------|
| `adaptive_engine.py:_run_feedback()` | Add call to `_scrape_new_favorites()` after feedback replay |
| `adaptive_engine.py` (new function) | `_scrape_new_favorites(cache_dir, graph, favorites, history, api_key)` — extracted helper |
| `adaptive_engine.py` (new function) | `_run_reset(cache_dir)` — reset logic |
| `adaptive_engine.py` (CLI) | Add `--reset` to mutually exclusive group |
| `adaptive_engine.py` (imports in `_run_feedback`) | Add `detect_scraper`, `load_cache`, `save_cache`, `fetch_filter_data` |
| `tests/test_adaptive_engine.py` | Tests for new favorites detection, scraping, reset logic |

No changes to `music_discovery.py` or `affinity_graph.py` — all needed functions already exist.

## Error Handling

- Scrape failures for individual artists: log warning, skip that artist, continue with others. A failed scrape is not fatal — the artist simply doesn't expand the candidate pool this round.
- `detect_scraper()` failure: log error, skip all scraping for this feedback run. Graph still gets feedback injections, just no new edges.
- Missing Last.fm API key: skip Last.fm edge injection (musicmap edges are the primary source). Log at info level.
- `--reset` with missing files: skip silently, continue deleting others.
- `--reset` followed by `--feedback` instead of `--seed`: will fail because pre-listen snapshot is gone. This is expected — the error message from the missing snapshot is sufficient.

## Testing

- Unit test: detection of newly favorited discovery artists (mock feedback history + library favorites + scrape cache)
- Unit test: case-insensitive scrape cache key check (library has "Deftones", cache has "deftones")
- Unit test: `--reset` deletes correct files, preserves correct files (including `offered_tracks.json`)
- Unit test: `--reset` with missing files — no crash
- Unit test: per-round cap of 10 artists enforced
- Integration test: after injecting a new favorite, verify scrape cache updated and graph has new musicmap + lastfm edges
- Adversarial: artist favorited but music-map returns empty → no crash, no bad state, no empty key in cache
- Adversarial: artist already in scrape cache (re-favorited from different round) → skip, no duplicate edges
- Adversarial: empty library favorites → zero candidates, no crash
- Adversarial: Last.fm returns similar artists with match score of 0 → filtered out, not added as edges
