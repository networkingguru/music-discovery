# Dedup Hardening (#13) + Prefer Original Studio Recordings (#14)

**Date:** 2026-04-08
**Issues:** #13, #14
**Review:** 4-reviewer parallel spec review completed. 11 issues addressed in this revision.

## Problem

1. **#13 — Duplicate tracks in playlist.** "Eye in the Sky" appears twice in the playlist (consecutive entries, same round). Two other cross-round duplicates also exist (megadeth, el alfa). The offered_set dedup logic looks correct on paper — root cause is unknown. We need diagnostic logging to catch it in the act, plus a failsafe to prevent the symptom.

2. **#14 — Non-original recordings in playlist.** The playlist includes compilation album tracks, live versions, remixes, and other non-original recordings. `search_itunes()` and `fetch_artist_catalog()` currently ignore album metadata (`collectionName`, `collectionArtistName`, etc.) that could be used to prefer original studio recordings.

## Design

### Issue #13: Dedup Hardening

#### Debug Logging

Add comprehensive DEBUG-level logging to the build loop in `adaptive_engine.py` (lines ~1129-1231). Set only the named logger (`logging.getLogger("adaptive_engine")`) to DEBUG — not the root logger, to avoid urllib3/requests noise. Enabled by default until issue #13 is resolved; add a comment referencing #13 so we know to dial it back later.

Log points:
- **Per artist:** The full `all_tracks` list (track names from Last.fm + catalog after merge). Shows if Last.fm returned duplicates or unexpected variants.
- **On dedup pass-through (line ~1165):** The key, norm_key, AND the exact boolean results of `key in offered_set` and `norm_key in offered_set`. Also dump all offered_set entries where the artist component matches the current artist — shows what WAS in the set.
- **On post-resolution pass-through (line ~1183):** Same — canon_key, canon_norm, exact membership test results, and matching artist entries from offered_set.
- **On successful add:** All 6 keys added to offered_set, plus the exact return value from `_add_track_to_named_playlist` (actual_artist, actual_track).
- **On failsafe catch:** WARNING level with full context (the key that was caught, what was already in the set).
- **On `_load_offered_tracks`:** Log entry count loaded, to verify cross-round state is intact.

#### Failsafe Dedup

Expand `offered_tracks` (per-round set, line 1123) to store all 6 key variants per track — matching what `offered_set` receives. Currently it only stores `actual_key`. This makes `offered_tracks` usable as a reliable failsafe gate.

**Pre-add failsafe** (before `_add_track_to_named_playlist`, line ~1191): Check canon_key and canon_norm against `offered_tracks`. If found, log WARNING and `continue`. This prevents both the playlist add and the offered_entries append.

**Post-add failsafe** (after `_add_track_to_named_playlist` returns): Check `actual_key` and `actual_norm` against `offered_tracks`. If found, log WARNING, skip the `offered_entries.append()`, but acknowledge that the playlist add already happened — this gate only protects `offered_entries` integrity. The pre-add gate is the real prevention layer.

### Issue #14: Prefer Original Studio Recordings

#### New Helper: `_is_original_recording(result_dict) -> bool`

Location: `music_discovery.py`, near `search_itunes()`. No cross-module import needed — both callers are in the same file. `SearchResult` dataclass is unchanged; filtering happens before the return, not after.

Accepts a raw iTunes API result dict. Returns `False` if the result is likely a non-original recording. Must handle missing keys gracefully (e.g., `collectionArtistName` is absent on single-artist albums — use `.get()`, never raise KeyError). Checks in order:

1. **VA compilation:** `collectionArtistName` is present and differs from `artistName` (case-insensitive). Catches "Various Artists" compilations and DJ mixes. Note: single-artist compilations (e.g., "Greatest Hits" by Journey) will NOT be caught here — they're caught by check 3.

2. **Track name variant:** `trackName` contains parenthetical/bracket suffixes indicating a non-original version. Regex pattern (case-insensitive):
   ```
   [\(\[](Live|Remix|Re-Recorded|Acoustic|Demo|Radio Edit|
   Instrumental|Karaoke|Single Edit|Club Mix|
   Extended|Sessions|Outtakes|Take \d|Mixed|Bonus)
   ```
   **Excluded from this list:** "Remastered", "Stereo Mix", "Mono" — these are fidelity changes to the original recording, not different performances. A remastered studio track is still the original and is preferred over a compilation version.

3. **Compilation album name:** `collectionName` matches keywords (case-insensitive, word-boundary `\b` anchored):
   ```
   Greatest Hits|Best of|Anthology|Classics|
   \d+ Hits|DJ Mix|Lullaby|Renditions|Live at|Live from|Live in|
   Live Tour|Unplugged|MTV|Now That's
   ```
   **Excluded from this list:** "Essential", "Collection" — too generic, would false-positive on studio albums like "Essential Tremors" by Drive-By Truckers.

4. **High track count:** `trackCount` > 35. Catches large compilations while avoiding false positives on double albums (which typically max out around 30 tracks).

#### Changes to `search_itunes()`

After the existing `kind == "song"` filter, partition results into "original" and "fallback" lists using `_is_original_recording()`. Within each list, maintain existing artist-match and duration filters.

Result selection priority:
1. First exact artist match from originals
2. First fuzzy artist match from originals
3. First exact artist match from fallbacks
4. First fuzzy artist match from fallbacks

No `releaseDate` sorting — the track-level `releaseDate` in the iTunes API reflects the original recording date, not the album release date. It does not distinguish original albums from compilations. Rely on iTunes relevance ordering instead, which already tends to favor the canonical version.

#### Changes to `fetch_artist_catalog()`

Run `_is_original_recording()` **before** the `seen` set dedup. This prevents a failure mode where a compilation version arrives first, gets added to `seen`, gets filtered out, and then the original studio version is skipped by `seen` — causing the track to disappear entirely.

Order of operations per result:
1. Check `kind == "song"`, artist match, duration filter (existing)
2. Run `_is_original_recording()` — if False, skip to next result (don't add to `seen`)
3. Check `seen` set dedup — if duplicate, skip
4. Add to `seen` and `tracks` list

**Soft fallback:** If all results are filtered out by `_is_original_recording()`, return the unfiltered results instead (applying only the existing kind/artist/duration filters). This prevents artist starvation for artists who only have compilation appearances in iTunes.

#### No changes to `_add_track_to_named_playlist()`

The filtering happens upstream in the search/catalog functions. The playlist-add function continues to work with whatever it receives.

## Files Modified

1. **`adaptive_engine.py`** — Debug logging in build loop, failsafe dedup checks, expanded `offered_tracks` set
2. **`music_discovery.py`** — `_is_original_recording()` helper, changes to `search_itunes()` and `fetch_artist_catalog()`

## Testing

### Unit Tests for `_is_original_recording()`

Table of fixture dicts with expected bool results. Each fixture is a raw iTunes API result dict. Cover:

| Case | collectionArtistName | collectionName | trackName | trackCount | Expected |
|------|---------------------|----------------|-----------|------------|----------|
| Original studio album | absent | "Eye In the Sky" | "Eye in the Sky" | 10 | True |
| VA compilation | "Various Artists" | "80s 100 Hits" | "Eye in the Sky" | 100 | False |
| Greatest hits | absent | "Greatest Hits" | "Don't Stop Believin'" | 16 | False |
| Live track | absent | "Escape" | "Don't Stop Believin' (Live)" | 10 | False |
| Remastered (ALLOWED) | absent | "Escape (2022 Remaster)" | "Don't Stop Believin' (Remastered 2022)" | 10 | True |
| Remix | absent | "Rumours" | "Dreams (Gigamesh Edit) [Mixed]" | 11 | False |
| Double album (ALLOWED) | absent | "The Wall" | "Comfortably Numb" | 26 | True |
| Large compilation | absent | "Now That's What I Call Music 93" | "Dreams" | 40 | False |
| Missing collectionArtistName key | (key absent) | "Rumours" | "Dreams" | 11 | True |
| DJ mix | "Y.O.G.A." | "COW TECH MIX" | "Dreams" | 15 | False |

### Failsafe Dedup Test

Extract the failsafe logic into a testable path. Pre-seed `offered_tracks` with a known (artist, track) tuple and all 6 variants. Attempt to add the same track again. Verify: WARNING log emitted, `offered_entries` not appended, `_add_track_to_named_playlist` not called (for pre-add gate).

### Integration Verification

- Run build with DEBUG logging, verify per-artist track lists and dedup check results appear in log
- Run build, manually inspect playlist for compilation/live tracks — compare against a pre-change baseline run
- Test fallback: search for an artist whose iTunes catalog is entirely compilations — verify `search_itunes()` returns a result (from fallback list), verify `fetch_artist_catalog()` returns unfiltered results
