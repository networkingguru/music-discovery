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

1. Use AppleScript to export the full library XML to a fixed path in the cache directory (`~/.cache/music_discovery/Library.xml`, overwritten each run). Use a longer timeout than the default 30s to handle large libraries.
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
5. **Identify rejected artists**: for each unique artist in the MD playlist (lowercased for comparison), check if they exist in the `library_artists` dict returned by `parse_library()`. If absent (zero loved tracks) → add to the blocklist.
6. Write rejected artists to `blocklist_cache.json` via `save_blocklist()` (the auto-detected blocklist, not the user-managed `blocklist.txt`).
7. Log the audit results: playlist size, unplayed count, number of artists blocklisted.

Blocklisted artists are filtered out during scoring/filtering by the existing `filter_candidates` mechanism.

### What Doesn't Change

- Scoring, scraping, Last.fm filtering, playlist building — all unchanged.
- `--playlist` flag behavior stays the same.
- `blocklist.txt` (user-managed) and `blocklist_cache.json` (auto-detected) continue working.
- Windows/Linux: no auto-export (no AppleScript). Playlist audit still works if the user provides an XML that contains the MD playlist.

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
- **Non-interactive mode**: if stdin is not a TTY, skip the safety prompt and default to not blocklisting (safe default).
- **Audit ordering**: the audit reads the old playlist from the XML snapshot. Later, if `--playlist` runs, `setup_playlist()` replaces it with a new one. No conflict since the XML is a point-in-time export.
