# Playlist Generation Design

## Goal

Add a `--playlist` flag that creates an Apple Music playlist of the top 10 songs
for each of the top 50 discovered artists (or fewer if the filtered list is
shorter than 50; skip playlist generation entirely if the list is empty).

## CLI

Add `argparse` to `music_discovery.py`. One new flag:

- `--playlist` — after discovery completes, fetch top tracks and build the
  playlist in Music.app.

When `--playlist` is passed the full discovery pipeline runs first (scrape,
score, filter). The existing terminal summary and results file are still
produced before the playlist step begins.

## Data flow

```
Top min(50, len(ranked)) artists (from scored/filtered results)
  │
  ▼
Last.fm artist.getTopTracks (limit=10 per artist)
  │  cached in top_tracks_cache.json
  ▼
AppleScript: search Apple Music catalog for each track
  │  duplicate results directly into playlist (no ID collection)
  ▼
AppleScript: create/update "Music Discovery" playlist
  │  if this step fails ──▶ export XML plist with track references
  ▼
Done
```

## Top tracks fetching

- API: `artist.getTopTracks` with `limit=10`, using existing `LASTFM_API_KEY`.
- Cache: new file `top_tracks_cache.json` in CACHE_DIR (added to `_build_paths()`).
  Format: `{"artist name": [{"name": "Song", "artist": "Artist"}, ...]}`.
- Cache entries never expire. Delete the file manually to force a refresh.
- When an artist is added to the blacklist, their entry is automatically removed
  from `top_tracks_cache.json` (if present) to prevent cache bloat.
- Rate limited at 1 req/sec (existing `RATE_LIMIT` constant).
- Tracks with no name are skipped.
- Duplicate tracks across artists (e.g., collaborations) are kept — the playlist
  reflects each artist's top tracks independently.

## Apple Music integration (AppleScript via osascript)

### Important: catalog tracks vs library tracks

Apple Music catalog tracks do not expose a `persistent ID` property the way
local library tracks do. Instead of collecting IDs in one pass and adding them
in a second pass, the implementation must `duplicate` each search result
directly into the target playlist within a single AppleScript invocation (or
per-track invocation). This avoids the ID mismatch problem entirely.

### Stage 1 — playlist setup

- Check if playlist "Music Discovery" exists in Music.app.
- If it exists, clear all its tracks.
- If it does not exist, create it.
- If this step fails, fall back to XML plist export (see below).

### Stage 2 — search and add (must succeed)

- Use `osascript` with AppleScript to search Apple Music for each track.
- Search query: `"artist name song title"` per track.
- Sanitize artist/track names for AppleScript: escape quotes, backslashes,
  and strip characters that break AppleScript string literals.
- `duplicate` the first matching result into the "Music Discovery" playlist.
- If a track search returns no match, skip it and log to stdout.
- If `osascript` itself fails (Music.app not running, no subscription,
  permissions denied), raise an error and stop.
- Print progress every artist: `[3/50] Adding tracks for: artist name`
- Small delay (~0.5s) between osascript calls to avoid overwhelming Music.app
  (up to 500 calls total for 50 artists x 10 tracks).
- On success, print count of tracks added vs attempted (e.g.,
  `"Playlist 'Music Discovery' created with 423/500 tracks."`).

### Fallback: importable XML plist

If stage 2 fails (playlist manipulation error but search works), write an
Apple XML plist playlist file that Music.app can import.

- Output path: `OUTPUT_DIR/Music Discovery.xml` (added to `_build_paths()`).
- Format: Apple-compatible XML plist with the required structure:
  - Top-level dict with `Tracks` dict (Track ID → {Name, Artist, ...})
  - `Playlists` array with one entry containing `Playlist Items` array
  - Track entries include whatever metadata we retrieved from the search
- Import via: File → Library → Import Playlist.
- Print: `"Could not create playlist automatically — import {path} in
  Music.app via File → Library → Import Playlist."`

## Update behavior

When `--playlist` is run again:

- Top tracks cache is reused (only artists not in cache are fetched).
- Playlist rebuild is handled by stage 1 (clear) + stage 2 (repopulate),
  so the playlist always reflects the latest discovery results.

## Error handling

| Failure | Behavior |
|---|---|
| Fewer than 50 artists in results | Use however many there are |
| Zero artists in results | Skip playlist generation, print message |
| Last.fm API error for one artist | Skip that artist, continue with remaining |
| No tracks found for an artist | Skip, log, continue |
| AppleScript search finds no match | Skip track, log, continue |
| AppleScript search fails entirely | Error message, stop |
| Playlist creation/update fails | Fall back to XML plist export |

## Files changed

- `music_discovery.py` — add argparse, `_build_paths()` update, top-tracks
  fetch function, AppleScript search/add function, playlist management
  function, XML fallback writer.

## New runtime files

- `top_tracks_cache.json` in CACHE_DIR
- `Music Discovery.xml` in OUTPUT_DIR (only on fallback)

## No new dependencies

All functionality uses stdlib (`subprocess`, `plistlib`, `argparse`) plus the
existing `requests` library.
