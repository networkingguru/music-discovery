# Auto-Import & Playlist Audit Design

**Date:** 2026-03-19
**Status:** Approved

## Problem

The tool currently requires a manually exported XML file that can go stale. Users must re-export after favoriting new tracks. Additionally, artists recommended by the tool but rejected by the user (not favorited after appearing in the Music Discovery playlist) continue to appear in future results.

## Solution

Two changes:

1. **Auto-export**: On macOS, automatically export a fresh Music Library XML via AppleScript before parsing. Eliminates stale data.
2. **Playlist audit**: Before scoring, inspect the previous Music Discovery playlist in the XML. Blocklist any artist whose tracks appear in the playlist but who has zero favorited tracks in the full library — they were recommended and rejected.

## Design

### Auto-Export (macOS)

On macOS, before any parsing:

1. Use AppleScript to export the full library XML to a temp location in the cache directory.
2. Use that fresh export as the library source.
3. The `--library` CLI flag still works as a manual override — if provided, skip auto-export.
4. On Windows/Linux, fall back to current behavior (auto-detect path or `--library` flag).

AppleScript command: `tell application "Music" to export library playlist 1 to POSIX file "<path>"`

### Playlist Audit

After parsing the fresh XML, before scoring:

1. **Find the "Music Discovery" playlist** in the XML's Playlists section.
2. If it doesn't exist or is empty, skip the audit — proceed with normal discovery.
3. **Calculate unplayed percentage**: count tracks with `Play Count == 0` (or absent), divide by total playlist tracks.
4. **Safety check**: if >25% of tracks are unplayed, prompt the user:
   - `"Over 25% of your Music Discovery playlist is unplayed. Blocklist unheard artists anyway? (y/n)"`
   - `y` → proceed with blocklisting.
   - `n` → skip blocklisting, continue with discovery normally.
5. **Identify rejected artists**: for each unique artist in the MD playlist, check if they have *any* favorited/loved tracks anywhere in the full library. If zero → add to the blocklist.
6. Write updated blocklist file, then continue with the normal discovery pipeline.

Blocklisted artists are filtered out during scoring/filtering by the existing `filter_candidates` mechanism.

### What Doesn't Change

- Scoring, scraping, Last.fm filtering, playlist building — all unchanged.
- `--playlist` flag behavior stays the same.
- `blocklist.txt` (user-managed) and `blocklist_cache.json` (auto-detected) continue working.
- Windows falls back to current XML behavior (no auto-export, no playlist audit).

## Data Flow

```
macOS run:
  AppleScript export → fresh XML in cache dir
  ↓
  Parse XML → loved artists + MD playlist tracks + play counts
  ↓
  Playlist audit:
    MD playlist exists? → calculate unplayed %
    >25% unplayed? → prompt user (y/n)
    For each MD playlist artist: any loved tracks in library?
    No → add to blocklist
  ↓
  Normal pipeline (scrape → score → filter → output → optional playlist)
```

## Edge Cases

- **No MD playlist**: first run or deleted — audit is skipped entirely.
- **Empty MD playlist**: treated same as no playlist.
- **User says "n" to safety check**: blocklist step is skipped, everything else runs normally.
- **Artist favorited after playlist was built**: they now have loved tracks → not blocklisted. Working as intended.
- **Auto-export fails**: log error, fall back to existing XML at default path (same as current behavior).
