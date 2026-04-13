# Artist Name Normalization

**Date:** 2026-04-13
**Issue:** #18 (favorited tracks still added to discovery playlist)

## Problem

Artist names are compared with raw string equality (after `.lower()`) throughout the system. Track names get normalized via `_normalize_for_match()`, but artist names do not. This causes three classes of bugs:

1. **Dedup bypass:** Library pre-seed adds `("mr mister", "is it love")` but the candidate arrives as `("mr. mister", "is it love")`. The keys don't match, so a favorited track gets re-offered.

2. **False auto-blocklisting:** Last.fm can't find "mister mister" (the music-map variant), returns empty, and after 3 rounds the strike system auto-blocks a valid artist. Meanwhile "mr. mister" comes through a different source and bypasses the blocklist.

3. **Non-artist candidates:** Genre tags ("80s", "classic rock"), song titles ("down under", "rocket man"), and other non-artist strings enter the candidate pool from music-map scrapes. These waste playlist slots and accumulate as noise in caches.

### Confirmed false blocklist entries (7 of 40)

| Blocked name | Library name | Normalization gap |
|---|---|---|
| `mister mister` | `mr mister` / `mr. mister` | Abbreviation — fixed by abbreviation map |
| `jimi hendrix and the experience` | `jimi hendrix` / `jimi hendrix experience` | `and the` variant |
| `bob seger and the silver bullet band` | `bob seger & the silver bullet band` | `and` vs `&` |
| `hall and oates` | `hall & oates` | `and` vs `&` |
| `cars` | `the cars` | Missing `the` prefix |
| `pretenders` | `the pretenders` | Missing `the` prefix |
| `terence trent d´arby` | `terence trent d'arby` | Unicode accent variant |

Also: `reo speed wagon` and `reo speedwagon` are both blocked — same band, two spellings, neither matching Last.fm's "REO Speedwagon". This is a **spelling variant** that normalization cannot fix. Manual blocklist cleanup only.

## Design

### Fix 1: `_normalize_artist()` function

New function in `adaptive_engine.py` (alongside `_normalize_for_match`):

```python
import unicodedata

_ABBREV_MAP = {"mister": "mr", "saint": "st", "junior": "jr", "senior": "sr"}

def _normalize_artist(name: str) -> str:
    """Normalize an artist name for comparison.

    Steps: lowercase, Unicode decomposition (NFKD) + strip combining marks,
    strip 'the ' prefix (with length guard), replace '&' with ' and ',
    strip remaining punctuation, apply abbreviation map, collapse whitespace.
    """
    s = name.lower().strip()
    if not s:
        return s

    # Unicode decomposition: Beyoncé -> Beyonce, d´arby -> d'arby variants
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))

    # Strip 'the ' prefix, but guard against "the the" -> "" or "the" -> ""
    stripped = re.sub(r'^the\s+', '', s)
    if len(stripped) >= 2:
        s = stripped

    # Replace & with ' and ' (space-insensitive to handle "hall&oates")
    s = re.sub(r'\s*&\s*', ' and ', s)

    # Strip punctuation (periods, apostrophes, etc.)
    s = re.sub(r'[^\w\s]', '', s)

    # Collapse whitespace
    s = re.sub(r'\s+', ' ', s).strip()

    # Apply abbreviation map to individual words
    words = s.split()
    words = [_ABBREV_MAP.get(w, w) for w in words]
    s = ' '.join(words)

    # Final empty guard: if normalization destroyed the name, fall back to lowered original
    if not s:
        return name.lower().strip()

    return s
```

Key design decisions:
- **Empty-string guard:** If normalization produces an empty string (e.g., `"!!!"` -> `""`), falls back to `name.lower().strip()`. Prevents universal collision key.
- **Length guard on "the" stripping:** `"the the"` (a real band) stays as `"the the"`, not `"the"` or `""`.
- **Space-insensitive `&` replacement:** `re.sub(r'\s*&\s*', ' and ', s)` handles `"hall&oates"`, `"hall & oates"`, `"hall &oates"` uniformly.
- **Unicode decomposition:** `NFKD` + strip combining characters handles `Beyoncé`/`Beyonce`, `d´arby`/`d'arby`.
- **Abbreviation map:** Small, targeted map for common music industry abbreviations. `"mister mister"` -> `"mr mr"` matches `"mr. mister"` -> `"mr mister"` (wait — `"mr mr"` != `"mr mister"`). Actually: `"mister mister"` -> words `["mister", "mister"]` -> `["mr", "mr"]` -> `"mr mr"`. And `"mr. mister"` -> strip punct -> `"mr mister"` -> words `["mr", "mister"]` -> `["mr", "mr"]` -> `"mr mr"`. Both normalize to `"mr mr"`. Correct.
- **Known limitation:** `[^\w\s]` strips all punctuation, which changes names like `"p!nk"` -> `"pnk"`, `"m.i.a."` -> `"mia"`, `"ac/dc"` -> `"acdc"`. This is acceptable — these are used as dedup/match keys alongside the raw key, not as display names. A collision between `"mia"` (the name) and `"m.i.a."` (the artist) at the normalization layer is correct — if both exist, they should match for dedup purposes.

**Applied at these comparison points:**

Grouped by strategy:

**A. Normalize-on-load (build normalized keys into sets/dicts at load time):**

0. **`_load_offered_tracks`:** When loading historical entries, add `(_normalize_artist(artist), track)` and `(_normalize_artist(artist), _normalize_for_match(track))` variants to the returned set alongside raw keys. This ensures cross-round dedup works for old data.
1. **Library pre-seed (build loop):** Add a third key variant using `(_normalize_artist(artist), _normalize_for_match(track))`.
2. **Blocklist loading:** All blocklist loaders (`load_user_blocklist`, `load_blocklist`, `load_ai_blocklist`, and the `full_blocklist` union) store normalized keys. `_auto_blocklist_artist` and `_remove_from_blocklist` also normalize when writing/removing.
3. **Strike loading:** When `search_strikes.json` is loaded, build a normalized-key index. When looking up or storing strikes, use `_normalize_artist(artist)` as the key.
4. **Cooldown / feedback history:** When `check_cooldown` scans `history_rounds`, build a normalized lookup over `artist_fb` keys. Use `_normalize_artist(artist)` for the lookup.

**B. Normalize-at-comparison (add normalized variant to checks):**

5. **Cross-round dedup (build loop):** Add `(_normalize_artist(artist), track.lower())` and `(_normalize_artist(artist), _normalize_for_match(track))` to the key variants checked.
6. **Post-resolution dedup (build loop):** Add normalized-artist variant of canon_key/canon_norm.
7. **Pre-add failsafe (build loop):** Add normalized-artist variant.
8. **Post-add bookkeeping (build loop):** Include normalized-artist keys in the key expansion (grows from 6 to ~9 variants).

**C. Additional comparison points identified by review:**

9. **Affinity graph node insertion:** When adding nodes/edges to the affinity graph, normalize artist keys so `"the cars"` and `"cars"` don't become separate nodes.
10. **`library_artists` set construction and `all_candidates -= library_artists`:** Normalize keys in both sets so the subtraction correctly removes library artists under variant names.
11. **`rank_candidates` blocklist check:** Uses `full_blocklist` (already normalized per point 2).
12. **`apply_overrides`:** Normalize override keys and lookup keys.

### Fix 2: Non-artist term filter

Static set of known non-artist terms, checked **before normalization** during candidate generation (when music-map neighbors are added to the candidate pool). Checked against the raw lowercased name to avoid false positives from normalization collapsing `"The Punk"` -> `"punk"`.

```python
_NON_ARTIST_TERMS = frozenset({
    "80s", "90s", "70s", "60s",
    "classic rock", "new wave", "post punk", "synth pop",
    "down under", "rocket man",
})
```

Removed from original list: `"alternative"`, `"grunge"`, `"metal"`, `"punk"`, `"indie"` — these are single generic words that could collide with real artist names. The retained terms are either decade labels (unambiguous) or multi-word genre/song terms that are extremely unlikely to be artist names.

Filter point: in the candidate generation loop where `all_candidates.update(...)` is called. Candidates whose lowercased name is in this set get skipped and logged at INFO level.

**Build summary line:** At the end of the build, log a summary: `"Filtered N non-artist candidates: 80s, classic rock, ..."` to make the filter visible without requiring log grep.

### Fix 3: Blocklist + strike cleanup

**Blocklist cleanup:** Remove 7 confirmed false-positive entries from `blocklist_cache.json`:

- `mister mister`
- `jimi hendrix and the experience`
- `bob seger and the silver bullet band`
- `hall and oates`
- `cars`
- `pretenders`
- `terence trent d´arby`

Also remove `reo speed wagon` and `reo speedwagon` — same band under two misspellings. This is a spelling variant that normalization cannot prevent from recurring; it's a manual data fix only.

**Strike cleanup:** Remove corresponding entries from `search_strikes.json` for all 9 artists above. Without this, removing blocklist entries is a no-op — the old strike counters would trigger immediate re-blocking on the next build.

This is a one-time data fix. With Fix 1 in place, the normalized blocklist/strike comparison will prevent recurrence for the 7 normalization-fixable cases.

## What this does NOT fix

- **Spelling variants** (e.g., `"reo speed wagon"` vs `"reo speedwagon"`). These are word-boundary differences, not punctuation/prefix issues. Requires manual cleanup when discovered.
- **Full alias mapping** (e.g., `"cat stevens"` <-> `"yusuf islam"`). These are different names for the same person, not normalizable. Requires a manual alias table if needed in the future.
- **Band-member solo projects** (e.g., `"james hetfield"`, `"mike portnoy"`). These are legitimately different entities from their bands.
- **The 60/40 library/new split.** The 47% favorites overlap is by design (`NEW_RATIO = 0.6`). Library artists get deep-cut tracks they don't already have.
- **Names where punctuation IS the identity** (e.g., `"p!nk"` -> `"pnk"`, `"m.i.a."` -> `"mia"`). The normalization layer uses these as match keys alongside raw keys. If a collision occurs (e.g., artist "Mia" and "M.I.A."), the dedup is correct — they would share playlist slots, which is the conservative choice.

## Testing

1. **Unit tests for `_normalize_artist()`:**
   - Basic: `"the cars"` -> `"cars"`, `"hall & oates"` -> `"hall and oates"`, `"mr. mister"` -> `"mr mr"`, plain names unchanged.
   - Unicode: `"terence trent d´arby"` -> `"terence trent darby"`, `"beyoncé"` -> `"beyonce"`.
   - Abbreviations: `"mister mister"` -> `"mr mr"`, `"saint etienne"` -> `"st etienne"`.
   - Edge cases: empty string -> `""`, `"!!!"` -> `"!!!"` (fallback), `"the the"` -> `"the the"` (length guard), `"the"` -> `"the"` (length guard).
   - Punctuation-heavy: `"ac/dc"` -> `"acdc"`, `"m.i.a."` -> `"mia"`, `"p!nk"` -> `"pnk"`.
   - Space-insensitive &: `"hall&oates"` -> `"hall and oates"`, `"hall &oates"` -> `"hall and oates"`.
2. **Dedup integration test:** Pre-seed library with `("mr mister", "is it love")`, offer candidate as `("mr. mister", "is it love")`, verify it's skipped.
3. **Blocklist integration tests:**
   - Block `"the cars"`, verify candidate `"cars"` is filtered.
   - Block `"cars"`, verify candidate `"the cars"` is filtered (reverse direction).
   - Block `"hall & oates"`, verify candidate `"hall and oates"` is filtered.
4. **Non-artist filter tests:**
   - Verify `"80s"` and `"classic rock"` are rejected during candidate generation.
   - Verify `"metal church"` is NOT rejected (exact match only, not substring).
   - Verify filter runs pre-normalization: `"The Punk"` is NOT rejected (raw lowered = `"the punk"`, not in set).
5. **Cross-round migration test:** Load an `offered_tracks.json` with pre-normalization entries (raw artist names from old rounds), verify normalized-artist keys are added to the dedup set on load.
6. **Cooldown normalization test:** History has `"the cars"`, candidate is `"cars"`, verify cooldown fires.
7. **Strike normalization test:** Strikes accumulated under `"mr. mister"`, verify lookup for `"mr mister"` finds them.
8. **Regression:** All existing test suites pass unchanged.
9. **Normalization-match logging test:** Verify DEBUG log fires when a normalized match catches something raw would have missed.
