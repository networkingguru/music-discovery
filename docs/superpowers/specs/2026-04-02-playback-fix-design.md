# Playback Fix & Playlist Robustness — Design Spec

**Date:** 2026-04-02
**Status:** Draft (post-review revision)
**Fixes:** Issue #8 (MediaPlayer JXA playback failure)
**Improves:** Cross-round track deduplication, auto-blocklist for missing artists

## 1. Overview

Four related fixes to make the adaptive engine's playlist building reliable:

1. **Library-first playback** — bypass JXA for tracks already in the user's library
2. **JXA NSRunLoop fix** — fix async `prepareToPlay` for catalog tracks not in library
3. **Cross-round track dedup** — never offer the same track twice across rounds
4. **Auto-blocklist on search strikes** — remove artists not available on Apple Music after 3 consecutive attempts with clean misses

All changes are scoped to `signal_experiment.py:_add_track_to_named_playlist()`, `music_discovery.py:_play_store_track()`, `music_discovery.py:search_itunes()`, and `adaptive_engine.py:_run_build()`. New data files: `offered_tracks.json`, `search_strikes.json`.

## 2. `SearchResult` Dataclass

### Problem

Multiple fixes need richer data from `search_itunes()`: the strike system needs to distinguish "not found" from "error," and the library-first path needs canonical metadata from the API response. Currently `search_itunes()` returns `str | None`, which cannot carry this information.

### Solution

A `SearchResult` dataclass returned by `search_itunes()`:

```python
@dataclasses.dataclass
class SearchResult:
    store_id: str | None        # Track store ID, or None
    searched_ok: bool           # True if API responded (200 + valid JSON), False on error/timeout
    canonical_artist: str = ""  # artistName from API response (empty if not found or error)
    canonical_track: str = ""   # trackName from API response (empty if not found or error)

    def __bool__(self) -> bool:
        return self.store_id is not None
```

**Backward compatibility:** The `__bool__` method means all existing callers that do `if not store_id:` or `if store_id:` continue to work correctly. `SearchResult(None, True)` is falsy, `SearchResult("12345", True)` is truthy.

**Callers that use `store_id` as a string** (e.g., passing to `_play_store_track(store_id)`) must be updated to access `result.store_id`. These are:

- `signal_experiment.py:_add_track_to_named_playlist()` line 436 — primary consumer, gets full update
- `music_discovery.py:add_track_to_playlist()` line 1201 — update to `result.store_id`
- All test mocks returning `"12345"` or `None` — update to return `SearchResult(...)` instances

### Where to define

In `music_discovery.py`, near the top with other data structures. Import in callers.

## 3. Library-First Playback

### Current behavior

Every track goes through: iTunes Search API → JXA MediaPlayer play → poll Music.app → find in library → duplicate to playlist. ~4-8s per track, fragile.

### New behavior

1. Call `search_itunes(artist, track_name)` — returns `SearchResult` with canonical names
2. If search succeeded (`result.searched_ok` and `result.store_id`): search Music.app library via AppleScript using canonical artist + track name
3. If found in library: duplicate directly to playlist. No playback, no JXA. ~1s.
4. If not in library: fall back to JXA path (section 4)
5. If search failed (`not result.searched_ok`): fall back to JXA path using original artist/track names

### Why search_itunes first?

The user's library may have slightly different metadata (e.g., "The Black Keys" vs "Black Keys"). Using the iTunes API response gives us the canonical `trackName` and `artistName` that match what Music.app stores for Apple Music content.

### AppleScript for library search + add

```applescript
tell application "Music"
    try
        set sr to search library playlist 1 for "{escaped_artist}"
        repeat with t in sr
            if name of t is "{escaped_track}" and artist of t is "{escaped_artist}" then
                duplicate t to user playlist "{escaped_playlist}"
                return "ok"
            end if
        end repeat
        return "not_in_library"
    on error e
        return "error: " & e
    end try
end tell
```

All interpolated values go through `_applescript_escape()`. The `try/on error` block ensures AppleScript failures fall through to the JXA path rather than crashing.

**Note:** AppleScript `is` is case-insensitive but does not handle Unicode normalization. An artist stored as "Beyoncé" may not match "Beyonce" from the API. This is acceptable — the mismatch causes a fallback to JXA, not a failure. The `search` command also does substring matching, so the exact-match `if` filter is essential.

### Control flow

The library-first path is a **complete early-return branch** inserted at the top of `_add_track_to_named_playlist()`, before the existing snapshot/poll logic (line 442). On `"ok"` it returns `True` immediately. On `"not_in_library"` or `"error"` it falls through to the existing JXA flow unchanged.

## 4. JXA NSRunLoop Fix

### Root cause

`_play_store_track()` calls `player.prepareToPlay` then `player.play` and exits. `prepareToPlay` is async — it needs time to buffer the track. When osascript exits, the async preparation is cancelled. This worked historically due to timing luck; a macOS update (Darwin 25.2.0) changed the behavior.

### Fix: poll `isPreparedToPlay` with timeout

Instead of a blind fixed wait, poll `isPreparedToPlay` within the NSRunLoop with a generous timeout:

```javascript
ObjC.import("MediaPlayer");
ObjC.import("Foundation");
var player = $.MPMusicPlayerController.systemMusicPlayer;
var ids = $.NSArray.arrayWithObject($("{store_id}"));
var descriptor = $.MPMusicPlayerStoreQueueDescriptor.alloc.initWithStoreIDs(ids);
player.setQueueWithDescriptor(descriptor);
player.prepareToPlay;

// Poll until prepared or timeout (10s)
var rl = $.NSRunLoop.currentRunLoop;
var deadline = $.NSDate.dateWithTimeIntervalSinceNow(10.0);
while (!player.isPreparedToPlay) {
    var step = $.NSDate.dateWithTimeIntervalSinceNow(0.25);
    rl.runUntilDate(step);
    if ($.NSDate.date.compare(deadline) === 2) break;  // NSOrderedDescending = past deadline
}

player.play;

// Short wait for playback to register with Music.app
var post = $.NSDate.dateWithTimeIntervalSinceNow(1.0);
rl.runUntilDate(post);

var state = player.playbackState;
String(state);
```

This exits as soon as the player is ready (typically <1s on fast connections) but allows up to 10s for slow networks. The outer 30s `_run_jxa()` timeout remains as a safety net.

**Note:** JXA is a legacy technology with no active Apple investment. The MediaPlayer bridge via osascript may need replacement with a Swift helper binary in a future macOS version. For now, it works.

## 5. Cross-Round Track Deduplication

### Problem

The build step doesn't check whether a track was offered in a prior round. As the engine converges on preferred artists, the same top tracks will resurface repeatedly. This is especially important for favorited artists, which bypass artist-level cooldown and reappear every round — track dedup is the **sole guard** against repeat tracks for these high-engagement artists.

### Persistence

A separate `offered_tracks.json` (not extending `feedback_history.json` to avoid schema coupling):

```json
{
  "version": 1,
  "tracks": [
    {"artist": "fleet foxes", "track": "white winter hymnal", "round": 1},
    {"artist": "fleet foxes", "track": "mykonos", "round": 1}
  ]
}
```

All values lowercased for consistent matching. The load function converts the list to a `set` of `(artist, track)` tuples for O(1) lookup.

### Integration point

In `adaptive_engine.py:_run_build()`, before the playlist-building loop:

1. Load `offered_tracks.json` into a set of `(artist, track)` tuples
2. When iterating tracks for each artist, skip any `(artist.lower(), track_name.lower())` already in the set
3. After successful add, append to the set
4. After the loop, save updated `offered_tracks.json` using atomic write (write to `.tmp`, then `os.replace()`)

### File handling

- **Missing file:** Return empty set, log nothing (normal for first run)
- **Corrupt JSON or wrong version:** Log warning, return empty set (do not crash)
- **Atomic write:** Write to `offered_tracks.json.tmp`, then `os.replace()` to final path. This prevents corruption if the process crashes mid-write.

### Deep track sourcing

Currently `fetch_top_tracks()` returns only 2 tracks per artist from Last.fm's `artist.getTopTracks`. This shallow pool exhausts fast for favorited artists that reappear every round, and only surfaces well-known hits — never deep cuts.

**New approach: tiered track sourcing.** For each artist, gather tracks in priority order:

1. **Last.fm top tracks** (existing `fetch_top_tracks`, increase `limit` to 50) — most popular first
2. **iTunes Search API catalog search** — `search_itunes` with just the artist name, `limit=200`, collecting all songs. This surfaces album tracks, B-sides, and deep cuts not in Last.fm's top tracks.

Tracks from tier 1 are offered first (highest likelihood of being good). Tier 2 fills in after tier 1 is exhausted across rounds. Both tiers are subject to the cross-round dedup check.

**New helper:** `fetch_artist_catalog(artist)` — calls the iTunes Search API with just the artist name, returns a list of `{"name": str, "artist": str}` for all songs. Deduplicates against the Last.fm list (by lowercased track name). This is a free API call (no key required), same as `search_itunes`.

**Track selection per round:** Still offer `tracks_per_artist` (default 2) tracks per artist per round. But the pool to draw from is now 50+ instead of 2. The build loop iterates the combined list, skipping previously-offered tracks, until it has added `tracks_per_artist` or exhausted the pool.

### Exhausted artist overflow

If all of an artist's tracks (from both tiers) have been previously offered, that artist contributes zero tracks. To prevent empty playlists as the engine converges, the build loop uses **overflow iteration** rather than a fixed slice of `top_artists`:

```python
artist_idx = 0
slots_filled = 0
while slots_filled < target_artist_count and artist_idx < len(ranked):
    score, artist = ranked[artist_idx]
    artist_idx += 1
    added_count = try_add_tracks(artist, ...)  # skips already-offered tracks
    if added_count > 0:
        slots_filled += 1
```

This continues past exhausted artists to fill the playlist from lower-ranked candidates. The exhausted artist is not blocklisted (that's search-failure only) and can still contribute if new tracks appear in their catalog. With the deep catalog sourcing, true exhaustion is rare — most artists have dozens of tracks available.

## 6. Auto-Blocklist on Search Strikes

### Problem

Some recommended artists don't exist on Apple Music. They waste playlist slots every round.

### Mechanism

A **strike counter** per artist, stored in `search_strikes.json`:

```json
{
  "version": 1,
  "strikes": {
    "artist name": {"count": 2, "last_round": 3, "last_recheck": 0}
  }
}
```

### Rules

1. During playlist build, track per-artist search outcomes using `SearchResult.searched_ok`. After the track loop for each artist, evaluate: if **at least one track was successfully searched** (`searched_ok=True`) and **none were found** (`store_id` is None for all), increment that artist's strike count and set `last_round` to current round.
2. If **any track is found** (even if playback later fails), reset strikes to 0.
3. If **all searches errored** (`searched_ok=False` for every track), do **not** count as a strike. Leave the counter unchanged.
4. "Consecutive" means consecutive attempts, not consecutive round numbers. If an artist falls out of `top_artists` for rounds 3-10 and reappears in round 11, a prior strike count of 2 from round 2 does **not** auto-blocklist on round 11's failure. Instead, if `last_round < current_round - 1`, reset the counter to 0 before evaluating. This prevents stale strikes from accumulating across long gaps.
5. At **3 consecutive attempts** with all-tracks-not-found, auto-add the artist to `ai_blocklist.txt`.

### Data flow for strike counting

`_add_track_to_named_playlist()` currently returns `bool`. To communicate search status to the strike logic in `_run_build()`, change the call structure:

1. Call `search_itunes()` **in `_run_build()`** before calling `_add_track_to_named_playlist()`
2. Pass the `SearchResult` to `_add_track_to_named_playlist()` (which no longer calls `search_itunes` itself)
3. `_run_build()` accumulates per-artist search outcomes and evaluates strikes after each artist's track loop

This keeps strike logic in `_run_build()` where it belongs, with clean data flow.

### Auto-blocklist write format

- `ai_blocklist.txt` is one artist per line, case-insensitive (existing convention)
- Before appending, check if the artist is already present (dedup)
- If the file doesn't exist, create it
- Prefix auto-added entries with a comment: `# auto-blocklisted round N: ` on the line above
- This makes auto-blocklisted artists distinguishable from manually blocklisted ones

### Recovery path

Auto-blocklisted artists can be manually removed from `ai_blocklist.txt`. For automatic recovery, use **on-demand re-checks with cooldown:**

- During candidate filtering in `_run_build()`, when an auto-blocklisted artist scores high enough to be a candidate, check whether it's time to re-test.
- `search_strikes.json` gains a `last_recheck` field per artist (default 0).
- Only re-test if `current_round - last_recheck >= 10`. This prevents repeatedly hitting the API for persistently dead artists.
- If the re-check finds the artist (`search_itunes` returns a result), remove from `ai_blocklist.txt` and log a notice. The artist re-enters the candidate pool immediately.
- If the re-check still fails, update `last_recheck` to `current_round` and keep the artist blocklisted.

**Cost:** At most one API call per blocklisted artist per 10 rounds, and only for artists the engine actually wants to use. Dead artists that fall out of the ranking cost nothing.

### File handling

Same as `offered_tracks.json`: missing → empty defaults, corrupt → log warning + empty defaults, atomic writes.

### Logging

```
WARNING: Auto-blocklisted "Some Artist" — not found on Apple Music for 3 consecutive rounds
INFO: Re-checked "Some Artist" — now available on Apple Music, removed from auto-blocklist
```

## 7. Changes Summary

| File | Change |
|------|--------|
| `music_discovery.py` | Add `SearchResult` dataclass |
| `music_discovery.py:search_itunes()` | Return `SearchResult` with canonical metadata |
| `music_discovery.py:_play_store_track()` | Poll `isPreparedToPlay` via NSRunLoop |
| `music_discovery.py:add_track_to_playlist()` | Update to use `result.store_id` |
| `signal_experiment.py:_add_track_to_named_playlist()` | Accept `SearchResult` param; library-first early-return path; error-handled AppleScript |
| `music_discovery.py` (new helper) | `fetch_artist_catalog(artist)` — iTunes Search API catalog lookup for deep tracks |
| `adaptive_engine.py:_run_build()` | Tiered track sourcing; call `search_itunes` before `_add_track_to_named_playlist`; overflow iteration; load/check/save offered tracks; strike counting; auto-blocklist; on-demand re-check with cooldown |
| `adaptive_engine.py` (new helpers) | `_load_offered_tracks()`, `_save_offered_tracks()`, `_load_search_strikes()`, `_save_search_strikes()` |
| `offered_tracks.json` (new data) | Persistent record of all tracks offered across rounds |
| `search_strikes.json` (new data) | Per-artist consecutive-attempt failure counts |
| Test files | Update all `search_itunes` mocks to return `SearchResult` instances |

## 8. Testing

### Unit tests

- **`SearchResult`:** `__bool__` returns False when `store_id` is None, True otherwise; backward compat with `if not result:` pattern
- **Library-first path:** Mock `_run_applescript` returning `"ok"` → returns True without calling JXA; returning `"not_in_library"` → falls through to JXA; returning `"error: ..."` → falls through to JXA
- **JXA script template:** Verify store ID is correctly interpolated into the script string
- **Track dedup:** Load set from file, verify known track is skipped, verify unknown track passes
- **Strike counting:**
  - All tracks not found (searched_ok=True, store_id=None) → increment
  - Any track found → reset to 0
  - All searches errored (searched_ok=False) → counter unchanged
  - Gap between attempts (`last_round < current_round - 1`) → counter resets
  - Hit threshold 3 → artist appended to blocklist
  - Mixed results (some found, some error) → reset due to found track
- **Deep track sourcing:** `fetch_artist_catalog` returns catalog tracks; combined list deduplicates against Last.fm top tracks; tier 1 offered before tier 2
- **Overflow iteration:** When first N artists are exhausted, playlist fills from lower-ranked candidates
- **On-demand re-check:** Blocklisted artist with `last_recheck` 10+ rounds ago triggers re-check; success removes from blocklist; failure updates `last_recheck`; recent recheck skips API call
- **File handling:** Missing file → empty defaults; corrupt JSON → log + empty defaults; atomic write verifiable via temp file existence

### Integration tests

- Multi-round simulation: same artist in rounds 1 and 2 → zero track overlap
- Artist with 3 consecutive strike rounds → appears in blocklist
- Artist with 2 strikes then found → counter resets, not blocklisted

### Live verification

- Run `--build` after fix, confirm tracks are added to playlist (resolves issue #8)
- Verify library-first path works for a known library track (no JXA invocation in logs)

## 9. What This Does NOT Change

- Affinity graph, weight learner, feedback collection — untouched
- Scoring and ranking — untouched
- Artist-level cooldown — still works as before, orthogonal to track dedup
- `--feedback` mode — untouched
- Existing `build_playlist()` in `music_discovery.py` — untouched (used by old `--playlist` mode)
- `_applescript_escape()` — pre-existing limitation with exotic Unicode inputs acknowledged but not changed in this spec (fallback to JXA path handles mismatches)
