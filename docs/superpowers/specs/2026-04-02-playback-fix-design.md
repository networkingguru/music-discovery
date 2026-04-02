# Playback Fix & Playlist Robustness — Design Spec

**Date:** 2026-04-02
**Status:** Draft
**Fixes:** Issue #8 (MediaPlayer JXA playback failure)
**Improves:** Cross-round track deduplication, auto-blocklist for missing artists

## 1. Overview

Four related fixes to make the adaptive engine's playlist building reliable:

1. **Library-first playback** — bypass JXA for tracks already in the user's library
2. **JXA NSRunLoop fix** — fix async `prepareToPlay` for catalog tracks not in library
3. **Cross-round track dedup** — never offer the same track twice across rounds
4. **Auto-blocklist on search strikes** — remove artists not available on Apple Music after 3 consecutive rounds of clean misses

All changes are scoped to `signal_experiment.py:_add_track_to_named_playlist()`, `music_discovery.py:_play_store_track()`, and `adaptive_engine.py:_run_build()`. No new files except `search_strikes.json` (data).

## 2. Library-First Playback

### Current behavior

Every track goes through: iTunes Search API → JXA MediaPlayer play → poll Music.app → find in library → duplicate to playlist. ~4-8s per track, fragile.

### New behavior

1. Call `search_itunes(artist, track_name)` to get canonical track name + artist (and store ID as fallback)
2. Search Music.app library via AppleScript: exact match on name + artist
3. If found in library: duplicate directly to playlist. No playback, no JXA. ~1s.
4. If not found: fall back to JXA path (section 3)

### Why search_itunes first?

The user's library may have slightly different metadata (e.g., "The Black Keys" vs "Black Keys"). Using the iTunes API response gives us the canonical `trackName` and `artistName` that match what Music.app stores for Apple Music content.

### AppleScript for library search + add

```applescript
tell application "Music"
    set sr to search library playlist 1 for "{artist}"
    repeat with t in sr
        if name of t is "{track_name}" and artist of t is "{artist}" then
            duplicate t to user playlist "{playlist_name}"
            return "ok"
        end if
    end repeat
    return "not_in_library"
end tell
```

This is the same pattern already used in lines 496-510 of `signal_experiment.py`, just executed earlier in the flow.

## 3. JXA NSRunLoop Fix

### Root cause

`_play_store_track()` calls `player.prepareToPlay` then `player.play` and exits. `prepareToPlay` is async — it needs time to buffer the track. When osascript exits, the async preparation is cancelled. This worked historically due to timing luck; a macOS update (Darwin 25.2.0) changed the behavior.

### Confirmed fix

Keep the JXA script alive with `NSRunLoop` to let `prepareToPlay` complete:

```javascript
ObjC.import("MediaPlayer");
ObjC.import("Foundation");
var player = $.MPMusicPlayerController.systemMusicPlayer;
var ids = $.NSArray.arrayWithObject($("{store_id}"));
var descriptor = $.MPMusicPlayerStoreQueueDescriptor.alloc.initWithStoreIDs(ids);
player.setQueueWithDescriptor(descriptor);
player.prepareToPlay;

// Keep runloop alive for prepareToPlay to complete
var rl = $.NSRunLoop.currentRunLoop;
var until = $.NSDate.dateWithTimeIntervalSinceNow(3.0);
rl.runUntilDate(until);

player.play;

// Short wait for playback to register with Music.app
var until2 = $.NSDate.dateWithTimeIntervalSinceNow(1.0);
rl.runUntilDate(until2);

var state = player.playbackState;
String(state);
```

Verified: playback state transitions to `1` (playing), Music.app reports the correct current track.

### Timeout

The JXA script takes ~4s (3s prepare + 1s post-play). The existing 30s timeout in `_run_jxa()` is adequate.

## 4. Cross-Round Track Deduplication

### Problem

The build step doesn't check whether a track was offered in a prior round. As the engine converges on preferred artists, the same top tracks will resurface repeatedly.

### Data source

`feedback_history.json` stores per-round data with artist-level feedback that includes track counts but not individual track names. However, `pre_listen_snapshot.json` keys are `(artist, track_name)` tuples, and the snapshot is replaced each round.

We need a persistent record of all offered tracks. Two options:

**Option A:** Add track-level detail to `feedback_history.json` rounds (each round's `artist_feedback` already exists; add a `tracks_offered` list per artist).

**Option B:** Maintain a separate `offered_tracks.json` that accumulates `(artist, track)` pairs across all rounds.

**Chosen: Option B.** Simpler, single-purpose, no risk of breaking existing feedback schema. The file is append-only (new tracks added each round, never removed).

### Format

```json
{
  "version": 1,
  "tracks": [
    {"artist": "fleet foxes", "track": "white winter hymnal", "round": 1},
    {"artist": "fleet foxes", "track": "mykonos", "round": 1}
  ]
}
```

All values lowercased for consistent matching.

### Integration point

In `adaptive_engine.py:_run_build()`, before the playlist-building loop (line ~858):

1. Load `offered_tracks.json` into a set of `(artist, track)` tuples
2. When iterating tracks for each artist, skip any `(artist.lower(), track_name.lower())` already in the set
3. After successful add, append to the set
4. After the loop, save updated `offered_tracks.json`

### Edge case: exhausted artist

If all of an artist's top tracks have been offered before, that artist contributes zero tracks to the playlist. The artist may still appear in `top_artists` if it scores high, but the empty slot is acceptable — it does not trigger auto-blocklist (that's search-failure only), and the engine will surface other artists to fill the playlist. Over many rounds, exhausted artists naturally lose priority as fresher candidates accumulate positive feedback.

## 5. Auto-Blocklist on Search Strikes

### Problem

Some recommended artists don't exist on Apple Music. They waste playlist slots every round.

### Mechanism

A **strike counter** per artist, stored in `search_strikes.json`:

```json
{
  "version": 1,
  "strikes": {
    "artist name": {"count": 2, "last_round": 3}
  }
}
```

### Rules

1. During playlist build, if **all tracks** for an artist get a clean "not found" from `search_itunes()` (HTTP 200, zero results or no artist match), increment that artist's strike count
2. If **any track** is found (even if playback later fails), reset strikes to 0
3. At **3 consecutive rounds** of all-tracks-not-found, auto-add the artist to `ai_blocklist.txt`
4. **Do not count** as strikes: network errors, timeouts, non-200 responses from iTunes API. These return `None` from `search_itunes()` but are indistinguishable from "not found" in the current code

### Distinguishing "not found" from "error"

`search_itunes()` currently returns `None` for both "no results" and "request failed." To count strikes correctly, we must distinguish these two cases. Change the return to add a second value:

```python
# New: return (store_id, was_searched) tuple
# (None, True)  = searched successfully, not found
# (None, False) = search failed (network error, timeout, non-200)
# ("12345", True) = found
```

This is a minimal change to `search_itunes()`. All existing callers check `if store_id:` which still works since the first element is what they care about. The callers in `_add_track_to_named_playlist()` will be updated to unpack both values.

### Logging

When an artist hits 3 strikes and is auto-blocklisted:
```
WARNING: Auto-blocklisted "Some Artist" — not found on Apple Music for 3 consecutive rounds
```

## 6. Changes Summary

| File | Change |
|------|--------|
| `music_discovery.py:_play_store_track()` | Add NSRunLoop waits |
| `music_discovery.py:search_itunes()` | Return `(store_id, searched_ok)` tuple |
| `signal_experiment.py:_add_track_to_named_playlist()` | Library-first path before JXA fallback |
| `adaptive_engine.py:_run_build()` | Load/check/save offered tracks; strike counting; auto-blocklist |
| `adaptive_engine.py` (new helper) | `_load_offered_tracks()`, `_save_offered_tracks()`, `_load_search_strikes()`, `_save_search_strikes()` |
| `offered_tracks.json` (new data) | Persistent record of all tracks offered across rounds |
| `search_strikes.json` (new data) | Per-artist consecutive-round failure counts |

## 7. Testing

- **Unit tests:** Library-first path (found/not-found), JXA fallback invocation, track dedup filtering, strike counting logic (increment/reset/blocklist threshold), `search_itunes` return value change
- **Integration test:** Multi-round simulation where the same artist appears twice — verify no track overlap
- **Live verification:** Run `--build` after fix, confirm tracks are added to playlist (resolves issue #8)

## 8. What This Does NOT Change

- Affinity graph, weight learner, feedback collection — untouched
- Scoring and ranking — untouched
- Artist-level cooldown — still works as before, orthogonal to track dedup
- `--feedback` mode — untouched
- Existing `build_playlist()` in `music_discovery.py` — untouched (used by old `--playlist` mode)
