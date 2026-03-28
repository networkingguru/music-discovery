# Signal Wargaming Tool — Design Spec

**Date:** 2026-03-28
**Goal:** Understand how different preference signals (favorites, play count, playlist membership, heavy rotation, personal recommendations) affect discovery quality — individually, in combination, and under degraded conditions — then recommend weight configurations for the user to evaluate by listening.

## Background

The current scoring pipeline uses a single signal: favorited track count per artist, weighted as `sqrt(log(loved_count + 1))`. Play count is collected but only used as a binary played/unplayed gate during playlist audit. The Apple Music API exposes additional user-level signals (heavy rotation, recommendations) that require a Music-User-Token.

This tool extends the evaluation framework to incorporate all available signals, analyze their individual and combined effects, and produce actionable weight recommendations.

## Signal Hierarchy

Signals are ordered by strength of user intent:

1. **Favorited songs** — strongest positive (explicit action)
2. **Rejected discovery artists** — strongest negative (explicit rejection)
3. **Playlist membership / Heavy rotation / Personal recs** — moderate positive (implicit)
4. **Play count** — moderate positive (engagement depth)
5. **Library membership + dateAdded** — weak positive (implicit endorsement)

Negative scoring (rejected artists) is already tuned at `NEGATIVE_PENALTY=0.4` and is not part of this experiment.

## Data Collection

All signals are gathered once and cached. Subsequent runs use cached data.

### Local (JXA)

| Signal | Method | Output |
|--------|--------|--------|
| Favorites | `parse_library_jxa()` (existing) | `{artist: loved_count}` |
| Play count | New: `collect_all_playcounts_jxa()` — batch read `lib.tracks.artist()` + `lib.tracks.playedCount()` | `{artist: total_play_count}` |
| Playlist membership | New: `collect_user_playlists_jxa()` — read all user-created playlists and their track artists | `{artist: playlist_count}` |

### API (developer token — existing)

| Signal | Method | Output |
|--------|--------|--------|
| Music-map similarity | Existing scrape cache | `{artist: {similar: proximity}}` |
| Apple similar artists | Existing Apple cache | `{artist: [similar_artists]}` |

### API (Music-User-Token — new)

| Signal | Endpoint | Output |
|--------|----------|--------|
| Heavy rotation | `GET /v1/me/history/heavy-rotation` | `set(artists)` — binary signal |
| Personal recommendations | `GET /v1/me/recommendations` | `set(artists)` — binary signal |

### Music-User-Token Auth

Automated via Playwright:
1. Python starts a local HTTP server serving a minimal page with MusicKit JS configured with the existing developer token.
2. Playwright opens the page, clicks "Authorize", handles the Apple sign-in flow.
3. Token is captured and stored in `.env` as `APPLE_MUSIC_USER_TOKEN`.
4. Token is valid for ~6 months.
5. **Fallback:** If Playwright automation fails (Apple blocks it), the local web server stays up and the user clicks one button manually in their browser.

## Signal Weighting

Each signal produces a per-artist affinity value. Continuous signals use logarithmic scaling to prevent dominance:

| Signal | Raw Value | Formula |
|--------|-----------|---------|
| Favorites | loved_count per artist | `sqrt(log(loved_count + 1))` |
| Play Count | total plays per artist | `sqrt(log(play_count + 1))` |
| Playlist Membership | user playlists containing artist | `sqrt(log(playlist_count + 1))` |
| Heavy Rotation | binary presence | flat bonus |
| Personal Recs | binary presence | flat bonus |

Each signal has a tunable coefficient. The composite seed weight is:

```
seed_weight(artist) = fav_w * fav_signal
                    + pc_w * pc_signal
                    + pl_w * pl_signal
                    + hr_w * hr_signal
                    + rec_w * rec_signal
```

This replaces the current `sqrt(log(loved_count + 1))` in the similarity scoring formula:

```
score(candidate) += seed_weight(library_artist) * proximity(library_artist, candidate)
```

## Analysis Engine

### Phase A — Individual Signal Profiling

For each of the 5 signals, run scoring with ONLY that signal active (all others zeroed at weight=1.0 for the active signal). Output per signal:
- Top 25 artists and scores.
- Artists unique to this signal (not in any other signal's solo top 25).
- Overlap percentage with the favorites-only baseline.
- Narrative explanation: which artists move and why (e.g., "Play count surfaces X, Y — high plays but not favorited").

### Phase B — Ablation (drop one at a time)

Start from all-signals-on at equal weights (1.0 each), then zero out one signal per run. Output per ablation:
- Which artists drop out of top 25 when this signal is removed.
- Which artists rise to replace them.
- Narrative: "Removing heavy rotation loses X, Y — only surfaced by frequent listening."

This measures each signal's marginal contribution in the presence of all others.

### Phase C — Degraded Scenarios

Simulate real user situations by zeroing signal groups:

| Scenario | Favorites | Play Count | Playlists | Heavy Rotation | Recs |
|----------|-----------|------------|-----------|----------------|------|
| **Baseline (current)** | on | off | off | off | off |
| **Full signals** | on | on | on | on | on |
| **No favorites** | off | on | on | on | on |
| **Light listener** | on | capped at 5 | off | off | on |
| **API-only** | off | off | off | on | on |
| **JXA-only** | on | on | on | off | off |

Output per scenario: top 25, overlap with full-signal baseline, narrative on what shifts and why.

### Phase D — Recommendations

Synthesize findings from phases A-C into 3-5 recommended weight configurations. Each recommendation includes:
- Weight values for all 5 signals.
- Name and rationale (e.g., "Niche Discovery", "Balanced", "Engagement-Heavy").
- Which scenario it's optimized for.
- Top 25 for that config.
- Key differences from baseline: who enters, who exits, why.

Recommendations are generated programmatically by analyzing:
- Which signals contribute the most unique artists.
- Which weight ranges cause the most interesting movement.
- Which combos produce the most diverse top 25.

## Output

### Report
A single report file (`signal_wargaming_results.md`) containing all four phases with narrative analysis.

### Evaluation Playlist
A single Music Discovery playlist containing a small number of tracks (2-3) from each artist that appears in the top 10 of ANY recommended config. This is a union — one playlist covers all configs. The user listens once and favorites the songs they like.

### Post-Listen Scoring
After the user listens and favorites new songs, a follow-up command re-scores all configs against the user's actual preferences. For each recommended config, compute:
- How many of the user's new favorites appeared in that config's top 10
- Precision: what percentage of that config's top 10 did the user actually like

This identifies the optimal default weight configuration empirically — the config that best predicted what the user would actually enjoy. The winning config becomes the default for the main pipeline.

## Architecture

Single new script: `signal_experiment.py`

### Imports from existing code
- `AppleMusicClient`, `generate_apple_music_token` from `compare_similarity.py`
- `parse_library_jxa`, `load_cache`, `load_user_blocklist`, `_build_paths`, `_run_jxa` from `music_discovery.py`

### New components
- `collect_all_playcounts_jxa()` — batch JXA read of all tracks with play counts
- `collect_user_playlists_jxa()` — JXA read of all user-created playlists
- `collect_heavy_rotation(client, user_token)` — API call for heavy rotation artists
- `collect_recommendations(client, user_token)` — API call for personal recommendations
- `acquire_user_token(developer_token)` — Playwright-automated MusicKit JS auth with manual fallback
- `score_artists_multisignal(cache, signal_data, weights, ...)` — scoring function accepting per-signal weight dict
- `run_phase_a()`, `run_phase_b()`, `run_phase_c()`, `run_phase_d()` — analysis phases
- `generate_wargaming_report()` — report assembly with narratives

### Caches
- `playcount_cache.json` — `{artist: total_play_count}`
- `playlist_membership_cache.json` — `{artist: playlist_count}`
- `heavy_rotation_cache.json` — `[artist, ...]`
- `recommendations_cache.json` — `[artist, ...]`
- Existing: `scrape_cache.json`, `apple_similar_cache.json`, `rejected_scrape_cache.json`

### Testing
- Unit tests for all new JXA parsers and scoring functions using mocked data
- Integration test for the multi-signal scoring formula
- No live data mutation — all analysis is read-only
