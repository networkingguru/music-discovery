# Tuning Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `tuning_experiment.py` that prefetches Apple Music similar-artist data, then scores candidates across a 4×4 matrix of Apple weight × negative penalty, outputting ranked top-12 lists and a movement report.

**Architecture:** Standalone script importing from `music_discovery.py` and `compare_similarity.py`. Phase 1 prefetches Apple data to a JSON cache. Phase 2 runs 16 scoring variants. Phase 3 generates terminal + file report. All existing caches are read-only.

**Tech Stack:** Python 3, existing music_discovery + compare_similarity imports, pytest

---

### File Structure

- **Create:** `tuning_experiment.py` — main script (prefetch, score, report)
- **Create:** `tests/test_tuning_experiment.py` — unit tests
- **No modifications** to existing files

---

### Task 1: Scoring Function With Tunable Parameters

**Files:**
- Create: `tuning_experiment.py`
- Create: `tests/test_tuning_experiment.py`

- [ ] **Step 1: Write failing test for tunable scoring**

Create `tests/test_tuning_experiment.py`:

```python
"""Tests for tuning_experiment.py."""
import pytest
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from tuning_experiment import score_artists_tunable


class TestScoreArtistsTunable:
    """Test the tunable scoring function."""

    def test_musicmap_only_baseline(self):
        """With apple_weight=0 and neg_penalty=0, matches original scoring."""
        cache = {
            "loved1": {"cand_a": 0.9, "cand_b": 0.5},
            "loved2": {"cand_a": 0.7, "cand_c": 0.3},
        }
        library = {"loved1": 2, "loved2": 1}
        result = score_artists_tunable(
            cache, library,
            apple_cache={}, blocklist_cache={}, user_blocklist=set(),
            apple_weight=0.0, neg_penalty=0.0,
        )
        names = [name for _, name in result]
        assert names[0] == "cand_a"  # highest combined proximity
        assert len(result) == 3

    def test_apple_weight_adds_bonus(self):
        """Apple matches get flat bonus per seed artist."""
        cache = {
            "loved1": {"cand_a": 0.5},
        }
        library = {"loved1": 1}
        apple_cache = {
            "loved1": ["cand_a", "cand_b"],
        }
        result = score_artists_tunable(
            cache, library,
            apple_cache=apple_cache, blocklist_cache={}, user_blocklist=set(),
            apple_weight=1.0, neg_penalty=0.0,
        )
        scores = {name: score for score, name in result}
        # cand_a gets musicmap + apple bonus, cand_b gets only apple bonus
        assert scores["cand_a"] > scores["cand_b"]
        assert "cand_b" in scores  # apple-only candidate appears

    def test_apple_add_if_absent_only(self):
        """Apple bonus only applies for candidates NOT already in musicmap for that seed."""
        cache = {
            "loved1": {"cand_a": 0.9},
        }
        library = {"loved1": 1}
        apple_cache = {
            "loved1": ["cand_a"],  # already in musicmap for loved1
        }
        # With apple_weight=1.0, cand_a should NOT get double-counted
        result_with = score_artists_tunable(
            cache, library,
            apple_cache=apple_cache, blocklist_cache={}, user_blocklist=set(),
            apple_weight=1.0, neg_penalty=0.0,
        )
        result_without = score_artists_tunable(
            cache, library,
            apple_cache={}, blocklist_cache={}, user_blocklist=set(),
            apple_weight=0.0, neg_penalty=0.0,
        )
        score_with = result_with[0][0]
        score_without = result_without[0][0]
        assert score_with == score_without  # no double-counting

    def test_negative_penalty_reduces_score(self):
        """Negative penalty reduces score for candidates near blocklisted artists."""
        cache = {
            "loved1": {"cand_a": 0.9, "cand_b": 0.5},
        }
        library = {"loved1": 2}
        blocklist_cache = {
            "bad_artist": {"cand_a": 0.8},  # cand_a is near a blocklisted artist
        }
        result_no_neg = score_artists_tunable(
            cache, library,
            apple_cache={}, blocklist_cache={}, user_blocklist={"bad_artist"},
            apple_weight=0.0, neg_penalty=0.0,
        )
        result_with_neg = score_artists_tunable(
            cache, library,
            apple_cache={}, blocklist_cache=blocklist_cache, user_blocklist={"bad_artist"},
            apple_weight=0.0, neg_penalty=0.4,
        )
        scores_no = {name: score for score, name in result_no_neg}
        scores_with = {name: score for score, name in result_with_neg}
        assert scores_with["cand_a"] < scores_no["cand_a"]
        assert scores_with["cand_b"] == scores_no["cand_b"]  # unaffected

    def test_library_artists_excluded(self):
        """Library artists never appear as candidates."""
        cache = {
            "loved1": {"loved2": 0.9, "cand_a": 0.5},
        }
        library = {"loved1": 1, "loved2": 1}
        result = score_artists_tunable(
            cache, library,
            apple_cache={}, blocklist_cache={}, user_blocklist=set(),
            apple_weight=0.0, neg_penalty=0.0,
        )
        names = [name for _, name in result]
        assert "loved2" not in names
        assert "loved1" not in names

    def test_user_blocklist_excluded(self):
        """User-blocklisted artists never appear as candidates."""
        cache = {
            "loved1": {"cand_a": 0.9, "blocked_one": 0.8},
        }
        library = {"loved1": 1}
        result = score_artists_tunable(
            cache, library,
            apple_cache={}, blocklist_cache={}, user_blocklist={"blocked_one"},
            apple_weight=0.0, neg_penalty=0.0,
        )
        names = [name for _, name in result]
        assert "blocked_one" not in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/brianhill/Scripts/Music\ Discovery && python -m pytest tests/test_tuning_experiment.py -v`
Expected: FAIL — `ModuleNotFoundError` or `ImportError`

- [ ] **Step 3: Implement `score_artists_tunable()`**

Create `tuning_experiment.py` with the scoring function:

```python
#!/usr/bin/env python3
"""
Tuning experiment: compare scoring variants across Apple Music weight
and negative scoring penalty dimensions.

Generates a 4×4 matrix of ranked candidate lists and a movement report.
"""

import math
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))


def score_artists_tunable(cache, library_artists, *, apple_cache,
                          blocklist_cache, user_blocklist,
                          apple_weight, neg_penalty):
    """Score candidates with tunable Apple weight and negative penalty.

    Positive (music-map):
        score(C) += sqrt(log(loved_count+1)) * musicmap_proximity(L, C)

    Positive (Apple Music, add-if-absent):
        score(C) += apple_weight   (flat, only if C NOT in musicmap for that seed)

    Negative (blocklist):
        score(C) -= neg_penalty * musicmap_proximity(B, C)

    Returns list of (score, artist_name) sorted descending.
    """
    library_set = set(library_artists.keys())
    exclude = library_set | user_blocklist
    scores = {}

    # Positive scoring from music-map
    for lib_artist, similar in cache.items():
        if not isinstance(similar, dict):
            continue
        weight = math.log(library_artists.get(lib_artist, 1) + 1) ** 0.5
        for candidate, proximity in similar.items():
            if candidate not in exclude:
                scores[candidate] = scores.get(candidate, 0.0) + weight * proximity

    # Positive scoring from Apple Music (add-if-absent)
    if apple_weight > 0:
        for lib_artist, apple_similar in apple_cache.items():
            if lib_artist not in library_artists:
                continue
            musicmap_similar = cache.get(lib_artist, {})
            for candidate in apple_similar:
                candidate_lower = candidate.lower() if candidate != candidate.lower() else candidate
                if candidate_lower not in exclude and candidate_lower not in musicmap_similar:
                    scores[candidate_lower] = scores.get(candidate_lower, 0.0) + apple_weight

    # Negative scoring from blocklisted artists
    if neg_penalty > 0:
        for bl_artist, similar in blocklist_cache.items():
            if not isinstance(similar, dict):
                continue
            for candidate, proximity in similar.items():
                if candidate not in exclude:
                    scores[candidate] = scores.get(candidate, 0.0) - neg_penalty * proximity

    return sorted(((v, k) for k, v in scores.items()),
                  key=lambda x: x[0], reverse=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/brianhill/Scripts/Music\ Discovery && python -m pytest tests/test_tuning_experiment.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tuning_experiment.py tests/test_tuning_experiment.py
git commit -m "feat: add tunable scoring function for tuning experiment"
```

---

### Task 2: Apple Music Data Prefetch

**Files:**
- Modify: `tuning_experiment.py`
- Modify: `tests/test_tuning_experiment.py`

- [ ] **Step 1: Write failing test for prefetch**

Add to `tests/test_tuning_experiment.py`:

```python
from unittest.mock import MagicMock, patch
import json
import tempfile
import os

from tuning_experiment import prefetch_apple_data


class TestPrefetchAppleData:
    """Test Apple Music data prefetching and caching."""

    def test_prefetch_caches_similar_artists(self, tmp_path):
        """Prefetch stores similar artists as lowercase name lists."""
        cache_path = tmp_path / "apple_music_cache.json"
        client = MagicMock()
        client.search_artist.return_value = ("123", "Radiohead")
        client.get_similar_artists.return_value = [
            {"name": "Thom Yorke", "id": "A1"},
            {"name": "Muse", "id": "A2"},
        ]
        library = {"radiohead": 5}

        result = prefetch_apple_data(client, library, cache_path)

        assert "radiohead" in result
        assert "thom yorke" in result["radiohead"]
        assert "muse" in result["radiohead"]
        # Verify it was saved to disk
        with open(cache_path) as f:
            saved = json.load(f)
        assert saved == result

    def test_prefetch_skips_not_found(self, tmp_path):
        """Artists not found on Apple Music are skipped (not cached)."""
        cache_path = tmp_path / "apple_music_cache.json"
        client = MagicMock()
        client.search_artist.return_value = (None, None)
        library = {"unknown_artist": 1}

        result = prefetch_apple_data(client, library, cache_path)

        assert "unknown_artist" not in result

    def test_prefetch_uses_existing_cache(self, tmp_path):
        """Already-cached artists are not re-fetched."""
        cache_path = tmp_path / "apple_music_cache.json"
        existing = {"radiohead": ["thom yorke", "muse"]}
        with open(cache_path, "w") as f:
            json.dump(existing, f)
        client = MagicMock()
        library = {"radiohead": 5, "portishead": 2}
        client.search_artist.return_value = ("456", "Portishead")
        client.get_similar_artists.return_value = [
            {"name": "Massive Attack", "id": "A3"},
        ]

        result = prefetch_apple_data(client, library, cache_path)

        # radiohead was cached, portishead was fetched
        client.search_artist.assert_called_once_with("portishead")
        assert result["radiohead"] == ["thom yorke", "muse"]
        assert "massive attack" in result["portishead"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/brianhill/Scripts/Music\ Discovery && python -m pytest tests/test_tuning_experiment.py::TestPrefetchAppleData -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement `prefetch_apple_data()`**

Add to `tuning_experiment.py`:

```python
import json
import time
import logging

log = logging.getLogger("tuning")


def prefetch_apple_data(client, library_artists, cache_path):
    """Fetch similar artists from Apple Music API for all library artists.

    Loads existing cache, fetches missing artists, saves updated cache.
    Returns {artist: [similar_artist_lowercase, ...]} dict.
    """
    # Load existing cache
    if cache_path.exists():
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)
    else:
        cache = {}

    to_fetch = [a for a in library_artists if a not in cache]
    if to_fetch:
        log.info(f"Fetching Apple Music data for {len(to_fetch)} artists "
                 f"({len(cache)} already cached)...")

    for i, artist in enumerate(to_fetch, 1):
        artist_id, matched_name = client.search_artist(artist)
        if artist_id is None:
            log.warning(f"  [{i}/{len(to_fetch)}] {artist} — not found on Apple Music")
            continue
        similar = client.get_similar_artists(artist_id)
        cache[artist] = [s["name"].lower() for s in similar]
        log.info(f"  [{i}/{len(to_fetch)}] {artist} → {len(similar)} similar artists")
        if i < len(to_fetch):
            time.sleep(1)  # rate limit

    # Save updated cache
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)

    return cache
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/brianhill/Scripts/Music\ Discovery && python -m pytest tests/test_tuning_experiment.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tuning_experiment.py tests/test_tuning_experiment.py
git commit -m "feat: add Apple Music prefetch with caching for tuning experiment"
```

---

### Task 3: Report Generation

**Files:**
- Modify: `tuning_experiment.py`
- Modify: `tests/test_tuning_experiment.py`

- [ ] **Step 1: Write failing test for report generation**

Add to `tests/test_tuning_experiment.py`:

```python
from tuning_experiment import generate_report, APPLE_WEIGHTS, NEG_PENALTIES


class TestGenerateReport:
    """Test report generation."""

    def test_report_contains_all_variants(self):
        """Report includes a section for every variant in the matrix."""
        # Build fake variant results
        variants = {}
        for aw in APPLE_WEIGHTS:
            for np_ in NEG_PENALTIES:
                key = (aw, np_)
                variants[key] = [
                    (3.0, "artist_a"),
                    (2.0, "artist_b"),
                    (1.0, "artist_c"),
                ]
        report = generate_report(variants, top_n=3, library_count=10)
        for aw in APPLE_WEIGHTS:
            for np_ in NEG_PENALTIES:
                assert f"apple={aw}" in report
                assert f"neg={np_}" in report

    def test_report_contains_movement_section(self):
        """Report includes a movement analysis section."""
        variants = {}
        for aw in APPLE_WEIGHTS:
            for np_ in NEG_PENALTIES:
                key = (aw, np_)
                if aw == 0.0 and np_ == 0.0:
                    variants[key] = [(3.0, "artist_a"), (2.0, "artist_b")]
                else:
                    variants[key] = [(3.0, "artist_c"), (2.0, "artist_d")]
        report = generate_report(variants, top_n=2, library_count=10)
        assert "Movement" in report or "movement" in report

    def test_report_limits_to_top_n(self):
        """Each variant section shows at most top_n artists."""
        variants = {
            (0.0, 0.0): [(i, f"artist_{i}") for i in range(20, 0, -1)],
        }
        # Fill remaining variants
        for aw in APPLE_WEIGHTS:
            for np_ in NEG_PENALTIES:
                if (aw, np_) not in variants:
                    variants[(aw, np_)] = [(1.0, "x")]
        report = generate_report(variants, top_n=5, library_count=10)
        # The baseline section should have exactly 5 numbered entries
        lines = report.split("\n")
        baseline_entries = [l for l in lines if l.strip().startswith("5.")]
        assert len(baseline_entries) >= 1  # at least one variant has a #5
        rank_6 = [l for l in lines if l.strip().startswith("6.")]
        # No #6 entries in variant sections (movement section may mention artists)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/brianhill/Scripts/Music\ Discovery && python -m pytest tests/test_tuning_experiment.py::TestGenerateReport -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement report generation**

Add to `tuning_experiment.py`:

```python
APPLE_WEIGHTS = [0.0, 0.5, 1.0, 1.5]
NEG_PENALTIES = [0.0, 0.2, 0.4, 0.8]
TOP_N = 12


def generate_report(variants, top_n=TOP_N, library_count=0):
    """Generate a formatted report comparing all scoring variants.

    Args:
        variants: {(apple_weight, neg_penalty): [(score, name), ...]}
        top_n: number of artists to show per variant
        library_count: number of library artists (for header)

    Returns:
        Formatted report string.
    """
    lines = []
    lines.append("=" * 70)
    lines.append("TUNING EXPERIMENT — Scoring Variant Comparison")
    lines.append(f"Library artists: {library_count}")
    lines.append(f"Matrix: {len(APPLE_WEIGHTS)} Apple weights × {len(NEG_PENALTIES)} negative penalties = {len(variants)} variants")
    lines.append(f"Showing top {top_n} per variant")
    lines.append("=" * 70)

    # Individual variant sections
    for aw in APPLE_WEIGHTS:
        for np_ in NEG_PENALTIES:
            key = (aw, np_)
            ranked = variants.get(key, [])
            lines.append("")
            label = f"apple={aw}, neg={np_}"
            if aw == 0.0 and np_ == 0.0:
                label += "  [BASELINE]"
            lines.append(f"--- {label} ---")
            for i, (score, name) in enumerate(ranked[:top_n], 1):
                lines.append(f"  {i:>2}. {name:<35s} ({score:.2f})")
            if not ranked:
                lines.append("  (no candidates)")

    # Movement analysis vs baseline
    baseline_key = (0.0, 0.0)
    baseline_names = [name for _, name in variants.get(baseline_key, [])[:top_n]]

    lines.append("")
    lines.append("=" * 70)
    lines.append("MOVEMENT ANALYSIS vs baseline (apple=0.0, neg=0.0)")
    lines.append("=" * 70)

    for aw in APPLE_WEIGHTS:
        for np_ in NEG_PENALTIES:
            if aw == 0.0 and np_ == 0.0:
                continue
            key = (aw, np_)
            variant_names = [name for _, name in variants.get(key, [])[:top_n]]
            entered = [n for n in variant_names if n not in baseline_names]
            exited = [n for n in baseline_names if n not in variant_names]
            if not entered and not exited:
                continue
            lines.append(f"\n  apple={aw}, neg={np_}:")
            lines.append(f"    {len(entered)} entered, {len(exited)} dropped")
            if entered:
                lines.append(f"    New:     {', '.join(entered)}")
            if exited:
                lines.append(f"    Dropped: {', '.join(exited)}")

    # Biggest movers: artists whose rank varies most across variants
    lines.append("")
    lines.append("=" * 70)
    lines.append("BIGGEST MOVERS — artists with largest rank swings")
    lines.append("=" * 70)

    all_artists = set()
    for ranked in variants.values():
        for _, name in ranked[:top_n]:
            all_artists.add(name)

    rank_ranges = {}
    for artist in all_artists:
        ranks = []
        for key, ranked in variants.items():
            names = [name for _, name in ranked[:top_n]]
            if artist in names:
                ranks.append(names.index(artist) + 1)
        if len(ranks) >= 2:
            rank_ranges[artist] = (min(ranks), max(ranks), len(ranks))

    movers = sorted(rank_ranges.items(), key=lambda x: x[1][1] - x[1][0], reverse=True)
    for artist, (lo, hi, appearances) in movers[:10]:
        lines.append(f"  {artist:<35s} rank {lo}-{hi} (in {appearances}/{len(variants)} variants)")

    lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/brianhill/Scripts/Music\ Discovery && python -m pytest tests/test_tuning_experiment.py -v`
Expected: All 12 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tuning_experiment.py tests/test_tuning_experiment.py
git commit -m "feat: add report generation for tuning experiment"
```

---

### Task 4: Main Function — Wire It All Together

**Files:**
- Modify: `tuning_experiment.py`

- [ ] **Step 1: Implement `main()`**

Add to `tuning_experiment.py`:

```python
import os
import argparse

from music_discovery import (
    _build_paths, load_dotenv, load_cache,
    load_blocklist, load_user_blocklist,
    filter_candidates, parse_library_jxa,
)
from compare_similarity import (
    generate_apple_music_token, AppleMusicClient,
)


def main():
    parser = argparse.ArgumentParser(
        description="Tuning experiment: compare scoring variants"
    )
    parser.add_argument("--refresh-apple", action="store_true",
                        help="Re-fetch all Apple Music data (ignore cache)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    load_dotenv()
    paths = _build_paths()

    # 1. Parse library
    print("Reading library via JXA...")
    library_artists = parse_library_jxa()
    print(f"Found {len(library_artists)} artists with loved/favorited tracks.")

    # 2. Load existing caches (read-only)
    cache = load_cache(paths["cache"])
    filter_cache_data = load_cache(paths["filter_cache"])
    file_blocklist = load_blocklist(paths["blocklist"])
    user_blocklist_path = pathlib.Path(__file__).parent / "blocklist.txt"
    user_blocklist = load_user_blocklist(user_blocklist_path)
    file_blocklist |= user_blocklist
    bl_cache = load_cache(paths["blocklist_scrape"])

    # 3. Prefetch Apple Music data
    apple_cache_path = paths["cache"].parent / "apple_music_cache.json"
    if args.refresh_apple and apple_cache_path.exists():
        apple_cache_path.unlink()

    key_id = os.environ.get("APPLE_MUSIC_KEY_ID", "")
    team_id = os.environ.get("APPLE_MUSIC_TEAM_ID", "")
    key_path = os.environ.get("APPLE_MUSIC_KEY_PATH", "")

    if key_id and team_id and key_path:
        print("\nGenerating Apple Music API token...")
        token = generate_apple_music_token(key_id, team_id, key_path)
        client = AppleMusicClient(token)
        print("Prefetching Apple Music similar artists...")
        apple_cache = prefetch_apple_data(client, library_artists, apple_cache_path)
        print(f"Apple Music cache: {len(apple_cache)} artists.")
    else:
        print("\nApple Music API credentials not configured. "
              "Apple weight variants will use empty data.")
        apple_cache = {}

    # 4. Run all scoring variants
    print(f"\nRunning {len(APPLE_WEIGHTS) * len(NEG_PENALTIES)} scoring variants...")
    variants = {}
    for aw in APPLE_WEIGHTS:
        for np_ in NEG_PENALTIES:
            scored = score_artists_tunable(
                cache, library_artists,
                apple_cache=apple_cache,
                blocklist_cache=bl_cache,
                user_blocklist=user_blocklist,
                apple_weight=aw,
                neg_penalty=np_,
            )
            ranked = filter_candidates(scored, filter_cache_data, file_blocklist)
            variants[(aw, np_)] = ranked

    # 5. Generate and output report
    report = generate_report(variants, top_n=TOP_N,
                             library_count=len(library_artists))
    print(report)

    # Save to file
    out_path = pathlib.Path(__file__).parent / "tuning_results.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("```\n")
        f.write(report)
        f.write("\n```\n")
    print(f"\nSaved to: {out_path}")


if __name__ == "__main__":
    main()
```

Note: Move the existing imports (`math`, `sys`, `pathlib`) to the top and add the new ones (`json`, `time`, `logging`, `os`, `argparse`, and the `music_discovery`/`compare_similarity` imports). The final file should have all imports at the top.

- [ ] **Step 2: Run unit tests to verify nothing broke**

Run: `cd /Users/brianhill/Scripts/Music\ Discovery && python -m pytest tests/test_tuning_experiment.py -v`
Expected: All 12 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tuning_experiment.py
git commit -m "feat: add main() to wire up tuning experiment end-to-end"
```

---

### Task 5: Integration Test — Run Against Live Data

- [ ] **Step 1: Run the full experiment**

Run: `cd /Users/brianhill/Scripts/Music\ Discovery && python tuning_experiment.py`

Expected:
- Reads library via JXA
- Prefetches Apple Music data (or uses cache)
- Runs 16 scoring variants
- Prints report with top 12 per variant + movement analysis
- Saves to `tuning_results.md`

- [ ] **Step 2: Verify output quality**

Check that:
- All 16 variants have results
- Baseline (apple=0.0, neg=0.0) matches what the main pipeline would produce
- Apple-weighted variants surface different artists
- Negative penalty variants demote expected artists
- Movement report shows meaningful differences

- [ ] **Step 3: Commit results and final state**

```bash
git add tuning_experiment.py tests/test_tuning_experiment.py tuning_results.md
git commit -m "feat: complete tuning experiment with live results"
```
