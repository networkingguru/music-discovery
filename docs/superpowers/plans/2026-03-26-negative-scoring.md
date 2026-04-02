# Negative Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add mild negative scoring so candidates similar to manually blocklisted artists rank lower

**Architecture:** Extend `score_artists()` to subtract a penalty for candidates that appear in blocklisted artists' similarity maps. Scrape music-map.com for blocklisted artists alongside loved artists. Use a tunable penalty factor (0.4) that is inherently milder than positive scoring since blocklisted artists have no loved_count multiplier.

**Tech Stack:** Python (math module), existing music-map scraper

---

## Step 1: Add `NEGATIVE_PENALTY` constant

**File:** `music_discovery.py`

- [ ] Add constant after line 77 (`MB_USER_AGENT`), before `ARTIST_BLOCKLIST`:

```python
# old
MB_USER_AGENT       = "MusicDiscoveryTool/1.0 (https://github.com/networkingguru/music-discovery)"

# new
MB_USER_AGENT       = "MusicDiscoveryTool/1.0 (https://github.com/networkingguru/music-discovery)"
NEGATIVE_PENALTY    = 0.4   # penalty factor for candidates near manually blocklisted artists
```

**Verification:** Constant is importable: `python -c "from music_discovery import NEGATIVE_PENALTY; assert NEGATIVE_PENALTY == 0.4"`

---

## Step 2: Update `score_artists()` signature and logic

**File:** `music_discovery.py`

- [ ] Replace the entire `score_artists` function (lines 1248-1262) with:

```python
def score_artists(cache, library_artists, blocklist_cache=None, user_blocklist=None):
    """Score non-library candidates using weighted proximity formula with negative scoring.

    Positive scoring (from loved artists):
        score(candidate) += sqrt(log(loved_count_i + 1)) * proximity(i, candidate)

    Negative scoring (from manually blocklisted artists):
        score(candidate) -= NEGATIVE_PENALTY * proximity(b, candidate)

    The penalty is inherently milder because:
    - NEGATIVE_PENALTY (0.4) is a flat constant, while positive weights are
      sqrt(log(loved_count + 1)) which ranges from ~0.83 (loved=1) to ~1.7 (loved=10+).
    - Loved artists typically have many more entries in the cache than blocklisted artists.

    Args:
        cache: {artist: {similar_artist: proximity}} from music-map scrape of loved artists.
        library_artists: {artist: loved_count} dict from parse_library().
        blocklist_cache: {artist: {similar_artist: proximity}} from music-map scrape of
                         user-blocklisted artists. None or {} to skip negative scoring.
        user_blocklist: set of lowercase artist names from blocklist.txt.
                        Used to exclude blocklisted artists themselves from results.
                        None or empty set to skip.

    Returns:
        List of (score, artist_name) sorted descending.
    """
    if blocklist_cache is None:
        blocklist_cache = {}
    if user_blocklist is None:
        user_blocklist = set()

    library_set = set(library_artists.keys())
    exclude = library_set | user_blocklist
    scores = {}

    # Positive scoring from loved artists
    for lib_artist, similar in cache.items():
        if not isinstance(similar, dict):
            continue  # skip stale flat-list entries
        weight = math.log(library_artists.get(lib_artist, 1) + 1) ** 0.5
        for candidate, proximity in similar.items():
            if candidate not in exclude:
                scores[candidate] = scores.get(candidate, 0.0) + weight * proximity

    # Negative scoring from manually blocklisted artists
    for bl_artist, similar in blocklist_cache.items():
        if not isinstance(similar, dict):
            continue  # skip stale flat-list entries
        for candidate, proximity in similar.items():
            if candidate not in exclude:
                scores[candidate] = scores.get(candidate, 0.0) - NEGATIVE_PENALTY * proximity

    return sorted(((v, k) for k, v in scores.items()), key=lambda x: x[0], reverse=True)
```

**Key design decisions:**
- `exclude = library_set | user_blocklist` -- blocklisted artists are excluded from the scored output (they are still filtered by `filter_candidates()` as well, but excluding early prevents them from appearing with negative scores)
- Candidates that ONLY appear in `blocklist_cache` (not in loved cache) can receive negative scores. This is intentional -- they are similar to disliked artists and not similar to liked artists, so they should rank at the bottom.
- The function remains backward-compatible: callers that pass only `cache` and `library_artists` get identical behavior to before.

**Verification:** All existing `test_score_artists_*` tests must still pass unchanged (since they don't pass `blocklist_cache`).

---

## Step 3: Add a separate blocklist scrape cache path

**File:** `music_discovery.py`

- [ ] In `_build_paths()` (line 323), add a new path entry for the blocklist scrape cache:

```python
# old
    return {
        "cache":        cache_dir  / "music_map_cache.json",
        "filter_cache": cache_dir  / "filter_cache.json",
        "blocklist":    cache_dir  / "blocklist_cache.json",
        "top_tracks":   cache_dir  / "top_tracks_cache.json",
        "output":       output_dir / "music_discovery_results.txt",
        "playlist_xml": output_dir / "Music Discovery.xml",
    }

# new
    return {
        "cache":            cache_dir  / "music_map_cache.json",
        "filter_cache":     cache_dir  / "filter_cache.json",
        "blocklist":        cache_dir  / "blocklist_cache.json",
        "blocklist_scrape": cache_dir  / "blocklist_scrape_cache.json",
        "top_tracks":       cache_dir  / "top_tracks_cache.json",
        "output":           output_dir / "music_discovery_results.txt",
        "playlist_xml":     output_dir / "Music Discovery.xml",
    }
```

**Why a separate cache?** The main `music_map_cache.json` contains scrapes keyed by loved artists. Blocklist scrapes serve a different purpose (negative scoring) and should not pollute the main cache. This also avoids ambiguity -- an artist in the main cache is assumed to be a loved library artist.

---

## Step 4: Scrape music-map for blocklisted artists in `main()`

**File:** `music_discovery.py`

- [ ] After the existing scraping block (step 4, around line 1388), add a new block to scrape blocklisted artists. Insert between the existing scrape block and the scoring block:

```python
    # ── 4b. Scrape blocklisted artists for negative scoring ──
    bl_cache = load_cache(paths["blocklist_scrape"])
    bl_to_scrape = [a for a in user_blocklist if a not in bl_cache]

    if bl_to_scrape:
        if not to_scrape:
            # scraper may not have been initialized if all loved artists were cached
            scrape = detect_scraper()
        log.info(f"\nScraping {len(bl_to_scrape)} blocklisted artist(s) for negative scoring...\n")
        for i, artist in enumerate(bl_to_scrape, 1):
            log.info(f"[{i}/{len(bl_to_scrape)}] Scraping (blocklist): {artist}")
            similar = scrape(artist)
            bl_cache[artist] = similar
            save_cache(bl_cache, paths["blocklist_scrape"])
            time.sleep(RATE_LIMIT)
    else:
        if user_blocklist:
            log.info("All blocklisted artists already cached — skipping blocklist scrape.\n")
```

**Important:** The variable `scrape` (the scraper function) is only defined inside the `if to_scrape:` block for loved artists. If all loved artists were cached but there are new blocklist entries, we need to call `detect_scraper()` here. The `if not to_scrape:` guard avoids redundant detection when the scraper was already initialized.

- [ ] Also handle the case where `scrape` needs to be defined. Add a check: if `to_scrape` was empty, `scrape` is undefined. The code above handles this with `if not to_scrape: scrape = detect_scraper()`.

**Edge case:** If `user_blocklist` is empty, `bl_to_scrape` is empty, and the entire block is skipped. No wasted work.

---

## Step 5: Pass blocklist data to `score_artists()` call in `main()`

**File:** `music_discovery.py`

- [ ] Update the scoring call (around line 1394):

```python
    # old
    log.info("\nScoring candidates...")
    scored = score_artists(cache, library_artists)

    # new
    log.info("\nScoring candidates...")
    scored = score_artists(cache, library_artists,
                           blocklist_cache=bl_cache, user_blocklist=user_blocklist)
```

**Note:** `user_blocklist` is already defined earlier in `main()` (line 1326). `bl_cache` is defined in Step 4 above. If `user_blocklist` is empty, `bl_cache` will be `{}`, and `score_artists` will skip negative scoring entirely.

- [ ] Also ensure `bl_cache` is initialized even if step 4b is skipped entirely. The block in Step 4 always loads `bl_cache = load_cache(paths["blocklist_scrape"])`, so it will be `{}` if the file doesn't exist. This is safe.

---

## Step 6: Remove user_blocklist from the merged file_blocklist

**File:** `music_discovery.py`

- [ ] Currently `main()` merges user_blocklist into file_blocklist (line 1327):

```python
    # old (lines 1324-1327)
    file_blocklist = load_blocklist(paths["blocklist"])
    user_blocklist_path = pathlib.Path(__file__).parent / "blocklist.txt"
    user_blocklist = load_user_blocklist(user_blocklist_path)
    file_blocklist |= user_blocklist
```

This merge must stay. User-blocklisted artists should still be excluded from final results by `filter_candidates()`. The negative scoring in `score_artists()` affects their **neighbors**, not the blocklisted artists themselves (which are excluded by the `exclude` set inside `score_artists`).

No change needed here -- the existing merge ensures `filter_candidates()` excludes blocklisted artists from the final ranked output. The `user_blocklist` set is kept separate (line 1326) for passing to `score_artists()`.

---

## Step 7: Clean up stale blocklist scrape entries

**File:** `music_discovery.py`

- [ ] After the stale-cache cleanup block for the main cache (step 3, around line 1372), add a similar block for the blocklist scrape cache. Insert in step 4b, before scraping:

```python
    # ── 4b. Scrape blocklisted artists for negative scoring ──
    bl_cache = load_cache(paths["blocklist_scrape"])

    # Remove entries for artists no longer in user_blocklist
    stale_bl = [a for a in bl_cache if a not in user_blocklist]
    if stale_bl:
        log.info(f"Removing {len(stale_bl)} artist(s) no longer in blocklist from scrape cache.")
        for a in stale_bl:
            del bl_cache[a]
        save_cache(bl_cache, paths["blocklist_scrape"])

    # Re-scrape stale format entries
    stale_bl_format = stale_cache_keys(bl_cache)
    if stale_bl_format:
        log.info(f"Re-scraping {len(stale_bl_format)} stale blocklist cache entries...")
        for k in stale_bl_format:
            del bl_cache[k]
        save_cache(bl_cache, paths["blocklist_scrape"])

    bl_to_scrape = [a for a in user_blocklist if a not in bl_cache]
    # ... rest of step 4b as in Step 4 above
```

---

## Step 8: Add tests for negative scoring

**File:** `tests/test_music_discovery.py`

- [ ] Add the following tests after the existing `test_score_artists_skips_stale_entries` test (line 253):

### Test 8a: Negative scoring reduces candidate score

```python
def test_score_artists_negative_scoring():
    """Blocklisted artist neighbors receive a score penalty."""
    cache = {
        "loved1": {"cand_a": 0.8, "cand_b": 0.6},
    }
    library = {"loved1": 5}
    blocklist_cache = {
        "hated1": {"cand_a": 0.9, "cand_c": 0.7},
    }
    user_blocklist = {"hated1"}

    # Without negative scoring
    baseline = md.score_artists(cache, library)
    baseline_scores = {name: s for s, name in baseline}

    # With negative scoring
    result = md.score_artists(cache, library, blocklist_cache, user_blocklist)
    result_scores = {name: s for s, name in result}

    # cand_a appears in both loved and blocklisted neighborhoods
    # Its score should be reduced
    assert result_scores["cand_a"] < baseline_scores["cand_a"]

    # cand_b only appears in loved neighborhood -- score unchanged
    assert result_scores["cand_b"] == pytest.approx(baseline_scores["cand_b"], abs=1e-9)

    # cand_c only appears in blocklisted neighborhood -- negative score
    assert result_scores["cand_c"] < 0
```

### Test 8b: Exact negative scoring formula

```python
def test_score_artists_negative_formula():
    """Verify exact negative scoring formula:
    positive = sqrt(log(loved+1)) * proximity
    negative = NEGATIVE_PENALTY * proximity
    """
    cache = {
        "loved1": {"cand_x": 0.5},
    }
    library = {"loved1": 3}
    blocklist_cache = {
        "hated1": {"cand_x": 0.7},
    }
    user_blocklist = {"hated1"}

    result = md.score_artists(cache, library, blocklist_cache, user_blocklist)
    result_scores = {name: s for s, name in result}

    positive = math.log(3 + 1) ** 0.5 * 0.5   # sqrt(log(4)) * 0.5 = 1.1774 * 0.5 = 0.5887
    negative = md.NEGATIVE_PENALTY * 0.7        # 0.4 * 0.7 = 0.28
    expected = positive - negative               # 0.5887 - 0.28 = 0.3087

    assert result_scores["cand_x"] == pytest.approx(expected, abs=1e-9)
```

### Test 8c: Blocklisted artists excluded from results

```python
def test_score_artists_excludes_blocklisted_artists():
    """Blocklisted artists themselves never appear in scored output."""
    cache = {
        "loved1": {"hated1": 0.9, "cand_a": 0.5},
    }
    library = {"loved1": 2}
    blocklist_cache = {
        "hated1": {"cand_a": 0.3},
    }
    user_blocklist = {"hated1"}

    result = md.score_artists(cache, library, blocklist_cache, user_blocklist)
    names = [name for _, name in result]

    assert "hated1" not in names
    assert "cand_a" in names
```

### Test 8d: Backward compatibility (no blocklist args)

```python
def test_score_artists_backward_compatible():
    """Calling without blocklist args produces identical results to old behavior."""
    cache = {
        "loved1": {"cand_a": 0.8, "cand_b": 0.4},
        "loved2": {"cand_a": 0.6},
    }
    library = {"loved1": 5, "loved2": 3}

    result_old_style = md.score_artists(cache, library)
    result_new_style = md.score_artists(cache, library, blocklist_cache=None, user_blocklist=None)

    assert result_old_style == result_new_style
```

### Test 8e: Negative scoring with stale entries in blocklist cache

```python
def test_score_artists_negative_skips_stale():
    """Stale flat-list entries in blocklist_cache are silently skipped."""
    cache = {
        "loved1": {"cand_a": 0.8},
    }
    library = {"loved1": 2}
    blocklist_cache = {
        "hated1": ["cand_a", "cand_b"],      # stale list format -- skip
        "hated2": {"cand_a": 0.6},            # fresh dict -- apply penalty
    }
    user_blocklist = {"hated1", "hated2"}

    result = md.score_artists(cache, library, blocklist_cache, user_blocklist)
    result_scores = {name: s for s, name in result}

    # Only hated2's penalty should apply (hated1 is stale)
    positive = math.log(2 + 1) ** 0.5 * 0.8
    negative = md.NEGATIVE_PENALTY * 0.6
    expected = positive - negative

    assert result_scores["cand_a"] == pytest.approx(expected, abs=1e-9)
```

### Test 8f: Penalty is milder than positive scoring

```python
def test_negative_penalty_milder_than_positive():
    """Verify that NEGATIVE_PENALTY < smallest possible positive weight.
    Smallest positive weight = sqrt(log(1+1)) = sqrt(log(2)) = 0.832.
    This ensures a single loved artist always outweighs a single blocklist entry
    at equal proximity."""
    min_positive_weight = math.log(1 + 1) ** 0.5  # loved_count=1 -> sqrt(log(2)) ~ 0.832
    assert md.NEGATIVE_PENALTY < min_positive_weight
```

---

## Step 9: Update existing formula test

**File:** `tests/test_music_discovery.py`

- [ ] The existing `test_score_artists_formula` test (line 232) does NOT need changes -- it calls `score_artists(cache, library)` with two args, which still works due to default parameters. Verify it passes unchanged.

---

## Summary of changes

| File | Change | Lines affected |
|------|--------|----------------|
| `music_discovery.py` | Add `NEGATIVE_PENALTY = 0.4` constant | ~line 78 |
| `music_discovery.py` | Add `"blocklist_scrape"` to `_build_paths()` | ~line 334 |
| `music_discovery.py` | Rewrite `score_artists()` with negative scoring | lines 1248-1262 |
| `music_discovery.py` | Add step 4b in `main()`: scrape blocklisted artists | after line 1388 |
| `music_discovery.py` | Update `score_artists()` call in `main()` | line 1394 |
| `tests/test_music_discovery.py` | Add 6 new tests (8a-8f) | after line 253 |

**Total:** ~70 lines added/modified in production code, ~90 lines of new tests.

**Risk assessment:** Low. The function signature change is backward-compatible (new params have defaults). The only behavioral change is that candidates near manually blocklisted artists score slightly lower. Existing tests are unaffected.
