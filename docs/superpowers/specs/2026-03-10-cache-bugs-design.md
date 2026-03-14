# Cache Bugs Design — 2026-03-10

## Problem

Two bugs observed after the env-config refactor (commit 677466c):

1. **Double scraping** — final counter shows `[2028/1014]`, meaning each artist is scraped twice.
2. **Cache ignored between runs** — every run re-scrapes all artists despite existing cache files.

## Root Causes

### Bug 1: Double scraping (`main()` line 346)

```python
to_scrape = [a for a in library_artists if a not in cache] + stale
```

Step 3 deletes all stale keys from `cache`. Step 4 then includes those artists twice:
- once via `if a not in cache` (they're now absent)
- once again via `+ stale`

With all 1014 artists stale, `to_scrape` has 2028 entries; `total` stays 1014.

### Bug 2: Cache path changed, old files not migrated

Commit 677466c moved the default cache location from `./music_map_cache.json` (script dir)
to `~/.cache/music_discovery/music_map_cache.json`. Existing cache files were left behind.

## Fixes

### Fix 1 — Remove redundant `+ stale` (one line)

```python
to_scrape = [a for a in library_artists if a not in cache]
```

After stale entries are deleted from `cache`, the list comprehension already captures them.
No other changes needed.

### Fix 2 — Migrate cache files (one-time shell operation)

Move:
- `./music_map_cache.json` → `~/.cache/music_discovery/music_map_cache.json`
- `./filter_cache.json`    → `~/.cache/music_discovery/filter_cache.json`
