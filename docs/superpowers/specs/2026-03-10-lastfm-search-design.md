# Last.fm Name Matching Fix — 2026-03-10

## Problem

`fetch_filter_data` calls `artist.getInfo` directly with the raw lowercased name
scraped from music-map.com (e.g. `"the eagles"`, `"hall and oates"`). Last.fm returns
a low-quality or mismatched result, so listener counts are wrong (e.g. Eagles → 454K
instead of ~5M), and classic popular artists slip past the 2M-listener filter.

## Fix

Add an `artist.search` call before `artist.getInfo` to resolve the canonical name and
listener count. The search API is much more forgiving of case/punctuation differences.

### API call sequence

1. `artist.search?artist=<raw_name>` → take top result's `name` and `listeners`
2. `artist.getInfo?artist=<canonical_name>` → get `mbid`
3. MusicBrainz `/ws/2/artist/<mbid>` → get `debut_year`

If step 1 returns no results, fall back to the existing behavior (use raw name directly
in `artist.getInfo`).

### filter_cache migration

Existing `filter_cache.json` entries were fetched with the old (broken) logic and have
incorrect listener counts. Clear the file so all ~4500 candidates are re-fetched with
the corrected lookup on the next run.

## Scope

- Modify `fetch_filter_data` in `music_discovery.py`
- Delete `~/.cache/music_discovery/filter_cache.json`
- Add/update tests covering the new search-then-getInfo flow
