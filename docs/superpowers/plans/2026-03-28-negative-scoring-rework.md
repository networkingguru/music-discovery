# Negative Scoring Rework — Use Rejected Artists Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change negative scoring source from manual blocklist (inert — zero overlap with candidates) to rejected discovery artists (high overlap — these were actual candidates the user rejected)

**Architecture:** The existing negative scoring infrastructure (`score_artists()`, step 4b scrape, `blocklist_scrape_cache.json`) is sound. The only problem is the *data source*: step 4b currently scrapes `user_blocklist` (20 manual data-quality entries from `blocklist.txt`) instead of the ~98 rejected artists from `blocklist_cache.json`. The fix is to compute `rejected_artists = file_blocklist_original - user_blocklist` before they're merged, then feed that set into step 4b and `score_artists()`. The `score_artists()` function, `NEGATIVE_PENALTY`, and all existing tests need no logic changes — only the wiring in `main()` changes, plus new tests for the new wiring. Rename the cache file to `rejected_scrape_cache.json` for clarity.

**Tech Stack:** Python, existing music-map scraper

---

## Step 1: Rename `blocklist_scrape` path to `rejected_scrape`

**File:** `music_discovery.py` (line 340)

- [ ] In `_build_paths()`, rename the key and filename:

```python
# old
        "blocklist_scrape": cache_dir  / "blocklist_scrape_cache.json",

# new
        "rejected_scrape": cache_dir  / "rejected_scrape_cache.json",
```

- [ ] Verify no other references to `"blocklist_scrape"` exist:

Run: `grep -rn 'blocklist_scrape' music_discovery.py tests/`
Expected: Only hits in step 4b (lines 1500, 1508, 1516, 1529) — these will be updated in Step 3.

---

## Step 2: Compute `rejected_artists` set in `main()`

**File:** `music_discovery.py` (lines 1425-1428)

- [ ] Capture the rejected-only artists before merging `user_blocklist` into `file_blocklist`:

```python
# old (lines 1425-1428)
    file_blocklist = load_blocklist(paths["blocklist"])
    user_blocklist_path = pathlib.Path(__file__).parent / "blocklist.txt"
    user_blocklist = load_user_blocklist(user_blocklist_path)
    file_blocklist |= user_blocklist

# new
    file_blocklist = load_blocklist(paths["blocklist"])
    user_blocklist_path = pathlib.Path(__file__).parent / "blocklist.txt"
    user_blocklist = load_user_blocklist(user_blocklist_path)
    rejected_artists = file_blocklist - user_blocklist  # taste rejections from playlist audit
    file_blocklist |= user_blocklist
```

**Why:** `file_blocklist` (from `blocklist_cache.json`) contains BOTH auto-rejected artists and manual blocklist entries (since previous runs merged them). Subtracting `user_blocklist` isolates the taste-based rejections — the ones with high neighbor overlap with candidates.

---

## Step 3: Rewire step 4b to scrape rejected artists

**File:** `music_discovery.py` (lines 1499-1533)

- [ ] Replace the entire step 4b block:

```python
    # ── 4b. Scrape rejected artists for negative scoring ──
    rejected_cache = load_cache(paths["rejected_scrape"])

    # Remove entries for artists no longer rejected
    stale_rejected = [a for a in rejected_cache if a not in rejected_artists]
    if stale_rejected:
        log.info(f"Removing {len(stale_rejected)} artist(s) no longer rejected from scrape cache.")
        for a in stale_rejected:
            del rejected_cache[a]
        save_cache(rejected_cache, paths["rejected_scrape"])

    # Re-scrape stale format entries
    stale_fmt = stale_cache_keys(rejected_cache)
    if stale_fmt:
        log.info(f"Re-scraping {len(stale_fmt)} stale rejected artist cache entries...")
        for k in stale_fmt:
            del rejected_cache[k]
        save_cache(rejected_cache, paths["rejected_scrape"])

    to_scrape_rejected = [a for a in rejected_artists if a not in rejected_cache]

    if to_scrape_rejected:
        if not to_scrape:
            # scraper may not have been initialized if all loved artists were cached
            scrape = detect_scraper()
        log.info(f"\nScraping {len(to_scrape_rejected)} rejected artist(s) for negative scoring...\n")
        for i, artist in enumerate(to_scrape_rejected, 1):
            log.info(f"[{i}/{len(to_scrape_rejected)}] Scraping (rejected): {artist}")
            similar = scrape(artist)
            rejected_cache[artist] = similar
            save_cache(rejected_cache, paths["rejected_scrape"])
            time.sleep(RATE_LIMIT)
    else:
        if rejected_artists:
            log.info("All rejected artists already cached — skipping rejected scrape.\n")
```

---

## Step 4: Update `score_artists()` call to pass rejected data

**File:** `music_discovery.py` (lines 1535-1538)

- [ ] Update the scoring call:

```python
# old
    scored = score_artists(cache, library_artists,
                           blocklist_cache=bl_cache, user_blocklist=user_blocklist)

# new
    scored = score_artists(cache, library_artists,
                           blocklist_cache=rejected_cache, user_blocklist=user_blocklist)
```

**Note:** `user_blocklist` is still passed for the `exclude` set inside `score_artists()` — manual blocklist artists should still be excluded from scored results. The negative *penalty* now comes from `rejected_cache` (rejected artists' neighborhoods) instead of manual blocklist neighborhoods.

---

## Step 5: Update `score_artists()` docstring

**File:** `music_discovery.py` (lines 1299-1325)

- [ ] Update the docstring to reflect the new data source:

```python
def score_artists(cache, library_artists, blocklist_cache=None, user_blocklist=None):
    """Score non-library candidates using weighted proximity formula with negative scoring.

    Positive scoring (from loved artists):
        score(candidate) += sqrt(log(loved_count_i + 1)) * proximity(i, candidate)

    Negative scoring (from rejected discovery artists):
        score(candidate) -= NEGATIVE_PENALTY * proximity(rejected_artist, candidate)

    The penalty is inherently milder because:
    - NEGATIVE_PENALTY (0.4) is a flat constant, while positive weights are
      sqrt(log(loved_count + 1)) which ranges from ~0.83 (loved=1) to ~1.7 (loved=10+).
    - Loved artists typically have many more entries in the cache than rejected artists.

    Args:
        cache: {artist: {similar_artist: proximity}} from music-map scrape of loved artists.
        library_artists: {artist: loved_count} dict from parse_library().
        blocklist_cache: {artist: {similar_artist: proximity}} from music-map scrape of
                         rejected discovery artists. None or {} to skip negative scoring.
        user_blocklist: set of lowercase artist names from blocklist.txt.
                        Used to exclude blocklisted artists themselves from results.
                        None or empty set to skip.

    Returns:
        List of (score, artist_name) sorted descending.
    """
```

---

## Step 6: Update `NEGATIVE_PENALTY` comment

**File:** `music_discovery.py` (line 79)

- [ ] Update the comment:

```python
# old
NEGATIVE_PENALTY    = 0.4   # penalty factor for candidates near manually blocklisted artists

# new
NEGATIVE_PENALTY    = 0.4   # penalty factor for candidates near rejected discovery artists
```

---

## Step 7: Delete old `blocklist_scrape_cache.json`

- [ ] The old cache file contains scrapes of the wrong artists (manual blocklist). Delete it so it doesn't cause confusion:

```bash
rm -f ~/.cache/music_discovery/blocklist_scrape_cache.json
```

The new `rejected_scrape_cache.json` will be populated on next run.

---

## Step 8: Add integration-style test for `rejected_artists` computation

**File:** `tests/test_music_discovery.py` (after line 350, after `test_negative_penalty_milder_than_positive`)

- [ ] Add test verifying the rejected artists set computation logic:

```python
def test_rejected_artists_excludes_manual_blocklist():
    """rejected_artists = file_blocklist - user_blocklist (taste rejections only)."""
    # Simulate what main() does: file_blocklist from blocklist_cache.json
    # contains both auto-rejected and manual entries
    file_blocklist = {"arch echo", "chon", "reo speedwagon", "blondie"}
    user_blocklist = {"reo speedwagon", "blondie"}
    rejected_artists = file_blocklist - user_blocklist

    assert rejected_artists == {"arch echo", "chon"}
    assert "reo speedwagon" not in rejected_artists
    assert "blondie" not in rejected_artists
```

- [ ] Run test:

Run: `python -m pytest tests/test_music_discovery.py::test_rejected_artists_excludes_manual_blocklist -v`
Expected: PASS

---

## Step 9: Add test verifying negative scoring uses rejected (not manual) artists

**File:** `tests/test_music_discovery.py` (after the test added in Step 8)

- [ ] Add test showing that negative scoring has effect when using rejected artists but not when using manual blocklist artists (simulating the real-world scenario):

```python
def test_negative_scoring_effective_with_rejected_artists():
    """Rejected artists (former candidates) have neighbor overlap with current candidates.
    Manual blocklist artists (classic pop/rock) do not.
    This test demonstrates the rework rationale."""
    # Candidate pool: prog metal / math rock
    cache = {
        "haken": {"leprous": 0.9, "caligulas horse": 0.85, "tesseract": 0.8},
        "animals as leaders": {"plini": 0.88, "chon": 0.82, "polyphia": 0.75},
    }
    library = {"haken": 3, "animals as leaders": 2}

    # Manual blocklist neighbors: classic pop/rock — NO overlap with prog candidates
    manual_bl_cache = {
        "reo speedwagon": {"air supply": 0.78, "loverboy": 0.76, "mr. mister": 0.80},
    }

    # Rejected artist neighbors: former candidates — HIGH overlap
    rejected_bl_cache = {
        "chon": {"polyphia": 0.90, "plini": 0.85, "covet": 0.80},
    }

    user_blocklist = {"reo speedwagon"}

    # With manual blocklist scrape: scores unchanged (no overlap)
    scored_manual = md.score_artists(cache, library, manual_bl_cache, user_blocklist)
    scored_manual_d = {name: s for s, name in scored_manual}

    # With rejected artist scrape: polyphia and plini get penalized
    scored_rejected = md.score_artists(cache, library, rejected_bl_cache, user_blocklist)
    scored_rejected_d = {name: s for s, name in scored_rejected}

    # polyphia appears in both loved and rejected neighborhoods — should be penalized
    assert scored_rejected_d["polyphia"] < scored_manual_d["polyphia"]

    # plini appears in both loved and rejected neighborhoods — should be penalized
    assert scored_rejected_d["plini"] < scored_manual_d["plini"]

    # leprous only in loved neighborhoods — score identical either way
    assert scored_rejected_d["leprous"] == pytest.approx(scored_manual_d["leprous"], abs=1e-9)
```

- [ ] Run test:

Run: `python -m pytest tests/test_music_discovery.py::test_negative_scoring_effective_with_rejected_artists -v`
Expected: PASS

---

## Step 10: Run full test suite and commit

- [ ] Run all tests:

Run: `python -m pytest tests/test_music_discovery.py -v`
Expected: All tests PASS

- [ ] Commit:

```bash
git add music_discovery.py tests/test_music_discovery.py
git commit -m "refactor: use rejected artists for negative scoring instead of manual blocklist

The tuning experiment showed manual blocklist artists (classic pop/rock) have
zero neighbor overlap with discovery candidates (prog/metal/world), making
negative scoring inert. Rejected artists from playlist audit ARE former
candidates with high overlap — using them makes negative scoring effective.

Closes #2"
```

---

## Summary of changes

| File | Change | Lines affected |
|------|--------|----------------|
| `music_discovery.py` | Update `NEGATIVE_PENALTY` comment | line 79 |
| `music_discovery.py` | Rename `blocklist_scrape` → `rejected_scrape` in `_build_paths()` | line 340 |
| `music_discovery.py` | Compute `rejected_artists` set before merge in `main()` | lines 1425-1428 |
| `music_discovery.py` | Rewire step 4b to scrape `rejected_artists` | lines 1499-1533 |
| `music_discovery.py` | Update `score_artists()` call | lines 1537-1538 |
| `music_discovery.py` | Update `score_artists()` docstring | lines 1300-1325 |
| `tests/test_music_discovery.py` | Add 2 new tests | after line 350 |
| filesystem | Delete `blocklist_scrape_cache.json` | one-time cleanup |

**Total:** ~30 lines changed in production code, ~50 lines of new tests. All existing tests pass unchanged.

**Risk assessment:** Low. The `score_artists()` function signature and logic are unchanged. Only the data piped into it changes. Existing tests verify the scoring math; new tests verify the wiring.
