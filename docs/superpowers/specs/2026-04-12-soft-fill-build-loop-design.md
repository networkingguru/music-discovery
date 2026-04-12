# Soft-Fill Build Loop

**Date:** 2026-04-12
**Scope:** `adaptive_engine.py` `_run_build`, lines ~1071-1105 (candidate selection) and ~1155 (loop iteration source)

## Problem

The build loop pre-slices the ranked candidate list into fixed 1.5x buffers per pool (new/library). When many artists fail Apple Music searches, the buffer runs dry and the playlist comes up short (e.g., 91 of 100 target tracks). The user gets no actionable error — just a smaller playlist.

## Design

1. Split the full ranked list into two pools (`new_artists`, `lib_artists`) with no truncation.
2. The build loop maintains two independent iterators and alternates to approximate the 60/40 new/library ratio.
3. When one pool exhausts, the other fills all remaining slots (pure soft fill, no floor).
4. Loop terminates when `slots_filled == target` OR both pools are exhausted.
5. If both pools exhaust before target: `sys.exit("ERROR: Only filled {X} of {Y} target tracks -- exhausted all {N} new and {M} library candidates.")`.
6. The "Top N candidates" log moves to after the build loop and shows what was actually used.

## What stays the same

- Per-artist search logic (Last.fm + iTunes tiered sourcing, dedup, auto-blocklist, strike tracking, rate limiting)
- The 60/40 ratio target (just no longer a hard pre-slice)
- All downstream steps (snapshot, offered features, explanation report)

## Alternation strategy

Track `new_tracks_added` and `lib_tracks_added`. At each iteration, pick the pool that is furthest below its ratio target. Specifically: pick new if `new_tracks_added / max(slots_filled, 1) < 0.6` and new pool has candidates, else pick library. If the chosen pool is exhausted, pick the other.
