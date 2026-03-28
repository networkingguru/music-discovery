# Multi-Source Scoring Tuning Experiment

**Goal:** Generate 16 scored candidate lists using real library data and all blocklists, varying Apple Music API weight and negative scoring penalty. User listens to results and picks the best tuning.

## Architecture

Single standalone script: `tuning_experiment.py`. Does not modify the main pipeline or any caches.

### Phase 1 — Prefetch Apple Music Similar Artists

- Read library via JXA (`parse_library_jxa()`) to get seed artists with loved counts
- For each seed artist, call Apple Music API (`AppleMusicClient.search_artist()` + `get_similar_artists()`)
- Cache to `~/.cache/music_discovery/apple_music_cache.json` as `{artist: [similar_artist, ...]}`
- Apple API returns up to 10 similar artists per query, no proximity scores (flat list)
- Rate-limit: 1 req/sec
- Skip artists that fail search (log warning, continue)
- Subsequent runs reuse cache; `--refresh-apple` flag to re-fetch

### Phase 2 — Score With Variants

Load from existing caches (read-only, no modifications):
- `music_map_cache.json` — `{artist: {similar: proximity}}`
- `blocklist_scrape_cache.json` — `{artist: {similar: proximity}}`
- `blocklist_cache.json` — auto-detected non-artists
- `blocklist.txt` — manual blocklist
- `apple_music_cache.json` — prefetched Apple data

**Variant matrix:** 4 Apple weights × 4 negative penalties = 16 variants

| Parameter | Values |
|-----------|--------|
| `apple_weight` | 0.0, 0.5, 1.0, 1.5 |
| `neg_penalty` | 0.0, 0.2, 0.4, 0.8 |

**Scoring formula per variant:**

```
score(C) = Σ[loved L] sqrt(log(L.count+1)) × musicmap_proximity(L, C)
         + Σ[loved L where C in apple_similar(L)] apple_weight
         - Σ[blocked B] neg_penalty × musicmap_proximity(B, C)
```

Apple Music contributes a flat bonus (no proximity signal available) only for candidates not already scored via music-map for that seed artist. This implements the "add-if-absent" strategy from the POC results.

**Exclusions (same as main pipeline):**
- Library artists excluded from candidates
- Manual blocklist artists excluded from candidates
- `filter_candidates()` applied: auto-blocklist, decade patterns, popular+classic filter

### Phase 3 — Report

**Output:** Terminal + `tuning_results.md` in project root

**Format per variant:**
```
=== apple_weight=0.5, neg_penalty=0.4 ===
 1. artist name         (score: 3.42)
 2. artist name         (score: 3.18)
 ...
12. artist name         (score: 1.95)
```

**Movement report (appended):**
- Artists that appear in some variants but not others, with which settings surface them
- Biggest score swings: artists whose rank changes most across the matrix
- Comparison against baseline (apple=0.0, neg=0.0)

## Key Constraints

- **Read-only** on all existing caches — no side effects on the main pipeline
- **No playlist creation** — scoring and reporting only
- **No blocklist additions** — skips the interactive audit/rejection step
- **Reuses all main pipeline imports** — `parse_library_jxa`, `load_cache`, `load_blocklist`, `load_user_blocklist`, `filter_candidates`, `score_artists` (as reference, but scoring is reimplemented to accept tuning params)
- **Apple data prefetched once** — cached for fast iteration

## Dependencies

- Existing: `music_discovery.py` (imports), `compare_similarity.py` (AppleMusicClient, generate_token)
- New: none beyond what's already in requirements.txt
