# Star Ratings Signal & Extended Wargaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add star ratings as a 6th signal in the wargaming framework, build a stratified eval playlist builder with cross-session deduplication, and accumulate post-listen results with automatic statistical testing.

**Architecture:** Ratings collector follows the existing JXA pattern. Scoring handles ratings as a special continuous signal that allows negative values. The eval playlist builder uses stratified sampling from Phase A solo runs for signal fairness, plus Phase D blended configs. A manifest tracks offered artists across sessions for deduplication, and post-listen history accumulates for statistical power.

**Tech Stack:** Python 3, JXA (osascript), scipy.stats (Fisher's exact test), existing signal_* module infrastructure.

**Spec:** `docs/superpowers/specs/2026-03-30-ratings-signal-extended-wargaming-design.md`

---

### Task 1: Add `collect_ratings_jxa()` to signal_collectors.py

**Files:**
- Modify: `signal_collectors.py` (after line 61, following `collect_playcounts_jxa`)
- Test: `tests/test_signal_collectors.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_signal_collectors.py`:

```python
def test_collect_ratings_averages_centered_by_artist():
    """Ratings should center on 3-star and average per artist."""
    from signal_collectors import collect_ratings_jxa
    fake_output = json.dumps([
        {"artist": "Haken", "rating": 100},   # 5-star -> +1.0
        {"artist": "Haken", "rating": 80},    # 4-star -> +0.5
        {"artist": "Tool", "rating": 40},     # 2-star -> -0.5
        {"artist": "tool", "rating": 20},     # 1-star -> -1.0
    ])
    with patch("signal_collectors._run_jxa", return_value=(fake_output, 0)):
        result = collect_ratings_jxa()
    assert "haken" in result
    assert abs(result["haken"]["avg_centered"] - 0.75) < 0.001  # (1.0 + 0.5) / 2
    assert result["haken"]["count"] == 2
    assert "tool" in result
    assert abs(result["tool"]["avg_centered"] - (-0.75)) < 0.001  # (-0.5 + -1.0) / 2
    assert result["tool"]["count"] == 2


def test_collect_ratings_unrated_treated_as_neutral():
    """Unrated tracks (rating=0) should count as 3-star (centered=0.0)."""
    from signal_collectors import collect_ratings_jxa
    fake_output = json.dumps([
        {"artist": "Haken", "rating": 100},   # 5-star -> +1.0
        {"artist": "Haken", "rating": 0},     # unrated -> 0.0
    ])
    with patch("signal_collectors._run_jxa", return_value=(fake_output, 0)):
        result = collect_ratings_jxa()
    assert abs(result["haken"]["avg_centered"] - 0.5) < 0.001  # (1.0 + 0.0) / 2
    assert result["haken"]["count"] == 2


def test_collect_ratings_skips_empty_artist():
    """Tracks with empty/missing artist should be skipped."""
    from signal_collectors import collect_ratings_jxa
    fake_output = json.dumps([
        {"artist": "", "rating": 100},
        {"artist": "Haken", "rating": 80},
    ])
    with patch("signal_collectors._run_jxa", return_value=(fake_output, 0)):
        result = collect_ratings_jxa()
    assert "" not in result
    assert "haken" in result


def test_collect_ratings_jxa_failure():
    """Should raise RuntimeError on JXA failure."""
    from signal_collectors import collect_ratings_jxa
    with patch("signal_collectors._run_jxa", return_value=("error", 1)):
        with pytest.raises(RuntimeError, match="JXA ratings read failed"):
            collect_ratings_jxa()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_signal_collectors.py -k "ratings" -v`
Expected: FAIL with ImportError (collect_ratings_jxa doesn't exist yet)

- [ ] **Step 3: Implement `collect_ratings_jxa()`**

Add to `signal_collectors.py` after line 61 (after `collect_playcounts_jxa`):

```python
def collect_ratings_jxa():
    """Read star ratings for ALL library tracks via JXA.

    Returns {artist_lowercase: {"avg_centered": float, "count": int}}.
    Centering: (star - 3) / 2 → 5★=+1.0, 4★=+0.5, 3★=0.0, 2★=-0.5, 1★=-1.0.
    Unrated tracks (rating=0) are treated as neutral (centered=0.0).
    Raises RuntimeError on JXA failure.
    """
    script = '''
var music = Application("Music");
var lib = music.libraryPlaylists[0];
var tracks = lib.tracks;
var count = tracks.length;
var result = [];
if (count > 0) {
    var artists = tracks.artist();
    var ratings = tracks.rating();
    for (var i = 0; i < count; i++) {
        result.push({artist: artists[i] || "", rating: ratings[i] || 0});
    }
}
JSON.stringify(result);
'''
    stdout, code = _run_jxa(script)
    if code != 0:
        raise RuntimeError(f"JXA ratings read failed (exit {code}): {stdout}")
    try:
        tracks = json.loads(stdout)
    except (json.JSONDecodeError, TypeError) as e:
        raise RuntimeError(f"Failed to parse JXA ratings output: {e}")

    # Accumulate per-artist: list of centered values
    artist_data = {}
    for t in tracks:
        artist = t.get("artist", "")
        if not isinstance(artist, str):
            continue
        artist = artist.strip().lower()
        if not artist:
            continue
        raw_rating = t.get("rating", 0) or 0
        stars = round(raw_rating / 20)
        centered = (stars - 3) / 2
        if artist not in artist_data:
            artist_data[artist] = {"total": 0.0, "count": 0}
        artist_data[artist]["total"] += centered
        artist_data[artist]["count"] += 1

    return {
        a: {"avg_centered": d["total"] / d["count"], "count": d["count"]}
        for a, d in artist_data.items()
        if d["count"] > 0
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_signal_collectors.py -k "ratings" -v`
Expected: All 4 ratings tests PASS

- [ ] **Step 5: Run full collector test suite**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_signal_collectors.py -v`
Expected: All tests PASS (no regressions)

- [ ] **Step 6: Commit**

```bash
git add signal_collectors.py tests/test_signal_collectors.py
git commit -m "feat: add collect_ratings_jxa() for star ratings signal"
```

---

### Task 2: Integrate ratings into signal_scoring.py

**Files:**
- Modify: `signal_scoring.py:14-17` (signal constants) and `signal_scoring.py:32-49` (compute_seed_weight)
- Test: `tests/test_signal_scoring.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_signal_scoring.py`:

```python
def test_compute_seed_weight_ratings_positive():
    """Ratings signal should produce positive weight for liked artists."""
    from signal_scoring import compute_seed_weight
    weights = {"favorites": 0.0, "playcount": 0.0, "playlists": 0.0,
               "heavy_rotation": 0.0, "recommendations": 0.0, "ratings": 1.0}
    signals = {
        "favorites": {}, "playcount": {}, "playlists": {},
        "heavy_rotation": set(), "recommendations": set(),
        "ratings": {"haken": {"avg_centered": 0.75, "count": 20}},
    }
    result = compute_seed_weight("haken", signals, weights)
    assert result > 0
    # Expected: 1.0 * 0.75 * sqrt(log(21))
    expected = 1.0 * 0.75 * math.sqrt(math.log(21))
    assert abs(result - expected) < 0.001


def test_compute_seed_weight_ratings_negative():
    """Ratings signal should produce negative weight for disliked artists."""
    from signal_scoring import compute_seed_weight
    weights = {"favorites": 0.0, "playcount": 0.0, "playlists": 0.0,
               "heavy_rotation": 0.0, "recommendations": 0.0, "ratings": 1.0}
    signals = {
        "favorites": {}, "playcount": {}, "playlists": {},
        "heavy_rotation": set(), "recommendations": set(),
        "ratings": {"nickelback": {"avg_centered": -0.5, "count": 10}},
    }
    result = compute_seed_weight("nickelback", signals, weights)
    assert result < 0
    expected = 1.0 * (-0.5) * math.sqrt(math.log(11))
    assert abs(result - expected) < 0.001


def test_compute_seed_weight_ratings_zero_for_missing():
    """Artists not in ratings dict should get 0 from ratings signal."""
    from signal_scoring import compute_seed_weight
    weights = {"favorites": 0.0, "playcount": 0.0, "playlists": 0.0,
               "heavy_rotation": 0.0, "recommendations": 0.0, "ratings": 1.0}
    signals = {
        "favorites": {}, "playcount": {}, "playlists": {},
        "heavy_rotation": set(), "recommendations": set(),
        "ratings": {"haken": {"avg_centered": 0.75, "count": 20}},
    }
    result = compute_seed_weight("unknown", signals, weights)
    assert result == 0.0


def test_score_candidates_negative_seed_weight_penalizes():
    """An artist with negative seed weight should penalize similar candidates."""
    from signal_scoring import score_candidates_multisignal
    cache = {
        "liked": {"candidate_a": 0.9},
        "disliked": {"candidate_a": 0.8, "candidate_b": 0.9},
    }
    signals = {
        "favorites": {"liked": 5}, "playcount": {}, "playlists": {},
        "heavy_rotation": set(), "recommendations": set(),
        "ratings": {
            "liked": {"avg_centered": 0.75, "count": 20},
            "disliked": {"avg_centered": -0.75, "count": 20},
        },
    }
    weights = {"favorites": 1.0, "playcount": 0.0, "playlists": 0.0,
               "heavy_rotation": 0.0, "recommendations": 0.0, "ratings": 1.0}
    ranked = score_candidates_multisignal(cache, signals, weights)
    scores = {name: score for score, name in ranked}
    # candidate_a gets positive from liked but negative from disliked
    # candidate_b only gets negative from disliked
    assert scores.get("candidate_b", 0) < 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_signal_scoring.py -k "ratings" -v`
Expected: FAIL (ratings not in ALL_SIGNALS, compute_seed_weight doesn't handle it)

- [ ] **Step 3: Update signal constants**

In `signal_scoring.py`, replace lines 14-17:

```python
CONTINUOUS_SIGNALS = ("favorites", "playcount", "playlists")
BINARY_SIGNALS = ("heavy_rotation", "recommendations")
ALL_SIGNALS = CONTINUOUS_SIGNALS + BINARY_SIGNALS
DEFAULT_WEIGHTS = {s: 0.0 for s in ALL_SIGNALS}
```

with:

```python
CONTINUOUS_SIGNALS = ("favorites", "playcount", "playlists")
RATINGS_SIGNAL = "ratings"
BINARY_SIGNALS = ("heavy_rotation", "recommendations")
ALL_SIGNALS = CONTINUOUS_SIGNALS + (RATINGS_SIGNAL,) + BINARY_SIGNALS
DEFAULT_WEIGHTS = {s: 0.0 for s in ALL_SIGNALS}
```

- [ ] **Step 4: Update `compute_seed_weight` to handle ratings**

In `signal_scoring.py`, replace the `compute_seed_weight` function (lines 32-49):

```python
def compute_seed_weight(artist, signals, weights, caps=None):
    """Compute composite seed weight for a library artist."""
    if caps is None:
        caps = {}
    total = 0.0
    for sig in CONTINUOUS_SIGNALS:
        w = weights.get(sig, 0.0)
        if w == 0.0:
            continue
        raw = signals.get(sig, {}).get(artist, 0)
        total += w * compute_signal_value(raw, cap=caps.get(sig))
    # Ratings: special continuous signal that allows negative values
    w = weights.get(RATINGS_SIGNAL, 0.0)
    if w != 0.0:
        rating_data = signals.get(RATINGS_SIGNAL, {}).get(artist)
        if rating_data is not None:
            avg = rating_data["avg_centered"]
            count = rating_data["count"]
            total += w * avg * math.sqrt(math.log(count + 1))
    for sig in BINARY_SIGNALS:
        w = weights.get(sig, 0.0)
        if w == 0.0:
            continue
        if artist in signals.get(sig, set()):
            total += w
    return total
```

- [ ] **Step 5: Update `score_candidates_multisignal` to allow negative seed weights**

In `signal_scoring.py`, replace the positive scoring music-map loop (lines 82-90):

```python
    # Positive scoring from music-map
    for lib_artist, similar in cache.items():
        if not isinstance(similar, dict):
            continue
        weight = compute_seed_weight(lib_artist, signals, weights, caps=caps)
        if weight <= 0:
            continue
        for candidate, proximity in similar.items():
            if candidate not in exclude:
                scores[candidate] = scores.get(candidate, 0.0) + weight * proximity
```

with:

```python
    # Scoring from music-map (positive and negative seed weights)
    for lib_artist, similar in cache.items():
        if not isinstance(similar, dict):
            continue
        weight = compute_seed_weight(lib_artist, signals, weights, caps=caps)
        if weight == 0:
            continue
        for candidate, proximity in similar.items():
            if candidate not in exclude:
                scores[candidate] = scores.get(candidate, 0.0) + weight * proximity
```

Also update the Apple Music section similarly — replace `if weight <= 0:` (line 98) with `if weight <= 0:` (keep as-is — Apple Music add-if-absent should only fire for positive seeds; negative-rated artists shouldn't add Apple similar artists).

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_signal_scoring.py -v`
Expected: All tests PASS including new ratings tests

- [ ] **Step 7: Run full test suite to check for regressions**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/ -v`
Expected: Some tests in test_signal_analysis.py may fail because ALL_SIGNALS changed. That's expected — we fix those in Task 3.

- [ ] **Step 8: Commit**

```bash
git add signal_scoring.py tests/test_signal_scoring.py
git commit -m "feat: integrate ratings signal into scoring with negative seed weights"
```

---

### Task 3: Update signal_analysis.py for ratings

**Files:**
- Modify: `signal_analysis.py:110-142` (SCENARIOS dict) and `signal_analysis.py:168-244` (Phase D recommendations)
- Test: `tests/test_signal_analysis.py`

- [ ] **Step 1: Update test fixtures to include ratings**

In `tests/test_signal_analysis.py`, update `_make_test_data()` (lines 6-26):

```python
def _make_test_data():
    """Shared test fixtures for analysis tests."""
    cache = {
        "haken": {"umpfel": 0.9, "native construct": 0.8, "pop artist": 0.3},
        "tool": {"umpfel": 0.7, "meshuggah": 0.6, "pop artist": 0.5},
        "adele": {"pop artist": 0.9, "ed sheeran": 0.8},
        "quiet_fan": {"niche act": 0.95, "deep cut": 0.85},
    }
    signals = {
        "favorites": {"haken": 5, "tool": 2, "quiet_fan": 10},
        "playcount": {"haken": 100, "tool": 50, "adele": 200},
        "playlists": {"haken": 3, "adele": 5},
        "heavy_rotation": {"adele", "tool"},
        "recommendations": {"haken", "meshuggah"},
        "ratings": {
            "haken": {"avg_centered": 0.75, "count": 20},
            "tool": {"avg_centered": 0.5, "count": 15},
            "adele": {"avg_centered": -0.25, "count": 50},
            "quiet_fan": {"avg_centered": 0.6, "count": 5},
        },
    }
    return cache, signals
```

- [ ] **Step 2: Update test assertions for new signal count**

In `tests/test_signal_analysis.py`, update `test_phase_a_produces_per_signal_results` (line 33-34):

```python
    assert set(results.keys()) == {"favorites", "playcount", "playlists",
                                    "heavy_rotation", "recommendations", "ratings"}
```

Update `test_phase_b_produces_per_signal_ablation` (line 65-66):

```python
    assert set(results.keys()) == {"favorites", "playcount", "playlists",
                                    "heavy_rotation", "recommendations", "ratings"}
```

- [ ] **Step 3: Add test for new Phase C scenario and Phase D configs**

Add to `tests/test_signal_analysis.py`:

```python
def test_phase_c_jxa_full_includes_ratings():
    from signal_analysis import run_phase_c
    cache, signals = _make_test_data()
    results = run_phase_c(cache, signals, top_n=10)
    assert "jxa_full" in results
    w = results["jxa_full"]["weights"]
    assert w["ratings"] == 1.0
    assert w["favorites"] == 1.0
    assert w["heavy_rotation"] == 0.0


def test_phase_d_includes_ratings_configs():
    from signal_analysis import run_phase_d
    cache, signals = _make_test_data()
    recs = run_phase_d(cache, signals, top_n=10)
    names = [r["name"] for r in recs]
    assert "Ratings-Heavy" in names
    assert "Ratings+Favorites Blend" in names
```

- [ ] **Step 4: Run tests to verify failures**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_signal_analysis.py -v`
Expected: FAIL (ratings not in SCENARIOS, jxa_full missing, Phase D configs missing)

- [ ] **Step 5: Add `jxa_full` scenario to SCENARIOS dict**

In `signal_analysis.py`, add after the `jxa_only` entry (after line 141):

```python
    "jxa_full": {
        "desc": "All local JXA signals including ratings, no API",
        "weights": {"favorites": 1.0, "playcount": 1.0, "playlists": 1.0,
                    "ratings": 1.0,
                    "heavy_rotation": 0.0, "recommendations": 0.0},
    },
```

Also update all existing SCENARIOS entries to include `"ratings": 0.0` in their weights dicts. Specifically:

- `baseline`: add `"ratings": 0.0`
- `full_signals`: add `"ratings": 1.0`
- `no_favorites`: add `"ratings": 1.0`
- `light_listener`: add `"ratings": 1.0`
- `api_only`: add `"ratings": 0.0`
- `jxa_only`: add `"ratings": 0.0` (original jxa_only stays without ratings for comparison)

- [ ] **Step 6: Add ratings-focused configs to Phase D**

In `signal_analysis.py`, add to the `recommendations` list in `run_phase_d` (after the Discovery-Maximizer entry, before line 219):

```python
        {
            "name": "Ratings-Heavy",
            "rationale": "Star ratings as primary signal, with favorites as secondary. "
                         "Best for users who consistently rate their music.",
            "weights": {"favorites": 0.3, "playcount": 0.3, "playlists": 0.1,
                        "ratings": 1.0,
                        "heavy_rotation": 0.1, "recommendations": 0.1},
        },
        {
            "name": "Ratings+Favorites Blend",
            "rationale": "Ratings and favorites weighted equally as co-primary signals. "
                         "Tests whether they reinforce or duplicate each other.",
            "weights": {"favorites": 0.8, "playcount": 0.3, "playlists": 0.2,
                        "ratings": 0.8,
                        "heavy_rotation": 0.2, "recommendations": 0.2},
        },
```

Also add `"ratings": 0.0` to the weights of all existing 5 configs (Favorites-Heavy, Engagement-Balanced, Engagement-Heavy, No-Favorites Fallback, Discovery-Maximizer) so they don't pick up ratings by default. Update Discovery-Maximizer to `"ratings": 1.0` since it uses all signals equally.

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_signal_analysis.py -v`
Expected: All tests PASS

- [ ] **Step 8: Run full test suite**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 9: Commit**

```bash
git add signal_analysis.py tests/test_signal_analysis.py
git commit -m "feat: add ratings to analysis phases, jxa_full scenario, ratings configs"
```

---

### Task 4: Update signal_report.py for ratings display

**Files:**
- Modify: `signal_report.py:10-16` (SIGNAL_DISPLAY dict)
- Test: `tests/test_signal_report.py`

- [ ] **Step 1: Add ratings to SIGNAL_DISPLAY**

In `signal_report.py`, replace lines 10-16:

```python
SIGNAL_DISPLAY = {
    "favorites": "Favorites",
    "playcount": "Play Count",
    "playlists": "Playlist Membership",
    "heavy_rotation": "Heavy Rotation",
    "recommendations": "Personal Recs",
}
```

with:

```python
SIGNAL_DISPLAY = {
    "favorites": "Favorites",
    "playcount": "Play Count",
    "playlists": "Playlist Membership",
    "ratings": "Star Ratings",
    "heavy_rotation": "Heavy Rotation",
    "recommendations": "Personal Recs",
}
```

- [ ] **Step 2: Run report tests**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_signal_report.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add signal_report.py
git commit -m "feat: add Star Ratings to report display names"
```

---

### Task 5: Wire ratings into signal_experiment.py collection and caching

**Files:**
- Modify: `signal_experiment.py:25-33` (imports), `signal_experiment.py:44-104` (collect_all_signals)
- Test: `tests/test_signal_experiment.py`

- [ ] **Step 1: Write failing tests for ratings collection and caching**

Add to `tests/test_signal_experiment.py`:

```python
def test_collect_all_signals_includes_ratings(tmp_path):
    """Ratings should be collected and cached."""
    from signal_experiment import collect_all_signals
    mock_favorites = {"haken": 5}
    mock_playcounts = {"haken": 100}
    mock_playlists = {"haken": 3}
    mock_ratings = {"haken": {"avg_centered": 0.75, "count": 20}}
    mock_hr = {"haken"}
    mock_recs = {"meshuggah"}

    with patch("signal_experiment.parse_library_jxa", return_value=mock_favorites), \
         patch("signal_experiment.collect_playcounts_jxa", return_value=mock_playcounts), \
         patch("signal_experiment.collect_user_playlists_jxa", return_value=mock_playlists), \
         patch("signal_experiment.collect_ratings_jxa", return_value=mock_ratings), \
         patch("signal_experiment.collect_heavy_rotation", return_value=mock_hr), \
         patch("signal_experiment.collect_recommendations", return_value=mock_recs):
        signals = collect_all_signals(cache_dir=tmp_path, api_session=MagicMock())

    assert signals["ratings"] == mock_ratings
    assert (tmp_path / "ratings_cache.json").exists()


def test_collect_all_signals_loads_ratings_from_cache(tmp_path):
    """Should load ratings from cache when file exists."""
    from signal_experiment import collect_all_signals
    cached = {"haken": {"avg_centered": 0.75, "count": 20}}
    (tmp_path / "ratings_cache.json").write_text(json.dumps(cached))
    (tmp_path / "playcount_cache.json").write_text(json.dumps({"haken": 100}))
    (tmp_path / "playlist_membership_cache.json").write_text(json.dumps({"haken": 3}))
    (tmp_path / "heavy_rotation_cache.json").write_text(json.dumps(["haken"]))
    (tmp_path / "recommendations_cache.json").write_text(json.dumps(["meshuggah"]))

    with patch("signal_experiment.parse_library_jxa", return_value={"haken": 5}), \
         patch("signal_experiment.collect_ratings_jxa") as mock_rat:
        signals = collect_all_signals(cache_dir=tmp_path, api_session=MagicMock())

    mock_rat.assert_not_called()
    assert signals["ratings"] == cached
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_signal_experiment.py -k "ratings" -v`
Expected: FAIL (collect_ratings_jxa not imported, not called)

- [ ] **Step 3: Add import**

In `signal_experiment.py`, update the import from `signal_collectors` (line 30) to include `collect_ratings_jxa`:

```python
from signal_collectors import (
    collect_playcounts_jxa, collect_user_playlists_jxa,
    collect_heavy_rotation, collect_recommendations, _make_user_session,
    collect_ratings_jxa,
)
```

- [ ] **Step 4: Add ratings collection to `collect_all_signals`**

In `signal_experiment.py`, add after the playlist collection block (after line 70) and before the heavy_rotation block:

```python
    rat_cache = cache_dir / "ratings_cache.json"
    if rat_cache.exists() and not refresh:
        log.info("Loading ratings from cache...")
        ratings = json.loads(rat_cache.read_text())
    else:
        log.info("Reading star ratings from Music.app...")
        ratings = collect_ratings_jxa()
        rat_cache.write_text(json.dumps(ratings, indent=2))
        log.info(f"  {len(ratings)} artists with ratings.")
```

Update the return dict (around line 98) to include ratings:

```python
    return {
        "favorites": favorites,
        "playcount": playcount,
        "playlists": playlists,
        "ratings": ratings,
        "heavy_rotation": heavy_rotation,
        "recommendations": recommendations,
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_signal_experiment.py -k "ratings" -v`
Expected: PASS

- [ ] **Step 6: Update existing collect tests to mock ratings**

The existing tests `test_collect_all_signals_caches_results`, `test_collect_all_signals_loads_from_cache`, and `test_collect_all_signals_skips_api_without_session` need to be updated to mock `collect_ratings_jxa`. Add `patch("signal_experiment.collect_ratings_jxa", return_value={"haken": {"avg_centered": 0.5, "count": 10}})` to each, and add a ratings cache file in the loads_from_cache test.

- [ ] **Step 7: Update integration test**

In `tests/test_signal_experiment.py`, update `test_full_experiment_produces_report` to include ratings in signals — add `mock_ratings` and the corresponding patch, and add `"ratings"` to the signals dict.

- [ ] **Step 8: Run full test suite**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 9: Commit**

```bash
git add signal_experiment.py tests/test_signal_experiment.py
git commit -m "feat: wire ratings into signal collection and caching"
```

---

### Task 6: Stratified eval playlist builder

**Files:**
- Modify: `signal_experiment.py` (replace `get_evaluation_artists` and `--build-playlist` handler)
- Test: `tests/test_signal_experiment.py`

- [ ] **Step 1: Write failing tests for stratified sampling**

Add to `tests/test_signal_experiment.py`:

```python
def test_build_stratified_artist_list_equal_per_signal():
    """Each signal should get equal representation in stratum 1."""
    from signal_experiment import build_stratified_artist_list

    phase_a = {
        "favorites": {"ranked": [(1.0, f"fav_{i}") for i in range(50)]},
        "playcount": {"ranked": [(1.0, f"pc_{i}") for i in range(50)]},
        "playlists": {"ranked": [(1.0, f"pl_{i}") for i in range(50)]},
        "ratings": {"ranked": [(1.0, f"rat_{i}") for i in range(50)]},
        "heavy_rotation": {"ranked": [(1.0, f"hr_{i}") for i in range(50)]},
        "recommendations": {"ranked": [(1.0, f"rec_{i}") for i in range(50)]},
    }
    phase_d = [
        {"name": "Config A", "ranked": [(1.0, f"blend_{i}") for i in range(50)]},
    ]
    result = build_stratified_artist_list(
        phase_a, phase_d, target_total=100, exclude=set(), prior_artists=set())

    # Check stratum 1 has roughly equal per-signal counts
    signal_counts = {}
    for entry in result:
        if entry["stratum"].startswith("solo:"):
            sig = entry["stratum"].split(":", 1)[1]
            signal_counts[sig] = signal_counts.get(sig, 0) + 1
    # 6 signals, ~78 slots for stratum 1 → ~13 each
    for sig, count in signal_counts.items():
        assert count >= 10, f"Signal {sig} only got {count} slots"


def test_build_stratified_artist_list_deduplicates():
    """Artists should not appear in multiple strata."""
    from signal_experiment import build_stratified_artist_list

    # Make signals share some artists
    shared = [(1.0, f"shared_{i}") for i in range(5)]
    phase_a = {
        "favorites": {"ranked": shared + [(1.0, f"fav_{i}") for i in range(45)]},
        "playcount": {"ranked": shared + [(1.0, f"pc_{i}") for i in range(45)]},
        "playlists": {"ranked": [(1.0, f"pl_{i}") for i in range(50)]},
        "ratings": {"ranked": [(1.0, f"rat_{i}") for i in range(50)]},
        "heavy_rotation": {"ranked": [(1.0, f"hr_{i}") for i in range(50)]},
        "recommendations": {"ranked": [(1.0, f"rec_{i}") for i in range(50)]},
    }
    phase_d = [
        {"name": "Config A", "ranked": [(1.0, f"blend_{i}") for i in range(50)]},
    ]
    result = build_stratified_artist_list(
        phase_a, phase_d, target_total=100, exclude=set(), prior_artists=set())

    names = [e["name"] for e in result]
    assert len(names) == len(set(names)), "Duplicate artists in result"


def test_build_stratified_artist_list_excludes_prior():
    """Artists from prior sessions should be excluded."""
    from signal_experiment import build_stratified_artist_list

    phase_a = {
        "favorites": {"ranked": [(1.0, "prior_artist"), (0.9, "new_artist")]},
        "playcount": {"ranked": [(1.0, f"pc_{i}") for i in range(50)]},
        "playlists": {"ranked": [(1.0, f"pl_{i}") for i in range(50)]},
        "ratings": {"ranked": [(1.0, f"rat_{i}") for i in range(50)]},
        "heavy_rotation": {"ranked": [(1.0, f"hr_{i}") for i in range(50)]},
        "recommendations": {"ranked": [(1.0, f"rec_{i}") for i in range(50)]},
    }
    phase_d = [
        {"name": "Config A", "ranked": [(1.0, f"blend_{i}") for i in range(50)]},
    ]
    result = build_stratified_artist_list(
        phase_a, phase_d, target_total=100,
        exclude=set(), prior_artists={"prior_artist"})

    names = [e["name"] for e in result]
    assert "prior_artist" not in names
    assert "new_artist" in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_signal_experiment.py -k "stratified" -v`
Expected: FAIL (build_stratified_artist_list doesn't exist)

- [ ] **Step 3: Implement `build_stratified_artist_list`**

Add to `signal_experiment.py` (replacing or alongside `get_evaluation_artists`):

```python
def build_stratified_artist_list(phase_a, phase_d, target_total=105,
                                  exclude=None, prior_artists=None):
    """Build a stratified artist list for the eval playlist.

    Stratum 1: Equal slots per signal from Phase A solo rankings.
    Stratum 2: Remaining slots from Phase D blended configs (round-robin).

    Args:
        phase_a: dict of {signal: {"ranked": [(score, name), ...]}}
        phase_d: list of config dicts with "ranked" lists
        target_total: target number of artists
        exclude: set of artist names to skip (library, blocklists)
        prior_artists: set of artists offered in prior sessions

    Returns:
        list of {"name": str, "stratum": str, "rank": int}
    """
    if exclude is None:
        exclude = set()
    if prior_artists is None:
        prior_artists = set()
    skip = exclude | prior_artists
    used = set()
    result = []

    # Stratum 1: signal-fair solo slots
    signals = list(phase_a.keys())
    n_signals = len(signals)
    stratum1_total = int(target_total * 0.75)  # ~75% for signal fairness
    per_signal = stratum1_total // n_signals

    # Round-robin across signals to fill stratum 1
    signal_iters = {}
    for sig in signals:
        ranked = phase_a[sig].get("ranked", [])
        signal_iters[sig] = iter(
            (rank, name) for rank, (_, name) in enumerate(ranked, 1)
            if name not in skip
        )

    signal_counts = {sig: 0 for sig in signals}
    filled = True
    while filled:
        filled = False
        for sig in signals:
            if signal_counts[sig] >= per_signal:
                continue
            for rank, name in signal_iters[sig]:
                if name not in used:
                    result.append({"name": name, "stratum": f"solo:{sig}", "rank": rank})
                    used.add(name)
                    signal_counts[sig] += 1
                    filled = True
                    break

    # Stratum 2: blended config slots (round-robin)
    stratum2_target = target_total - len(result)
    if phase_d and stratum2_target > 0:
        config_iters = []
        for rec in phase_d:
            config_iters.append((
                rec["name"],
                iter(
                    (rank, name) for rank, (_, name) in enumerate(rec["ranked"], 1)
                    if name not in skip
                ),
            ))
        added = True
        while len(result) < target_total and added:
            added = False
            for config_name, it in config_iters:
                if len(result) >= target_total:
                    break
                for rank, name in it:
                    if name not in used:
                        result.append({
                            "name": name,
                            "stratum": f"blend:{config_name}",
                            "rank": rank,
                        })
                        used.add(name)
                        added = True
                        break

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_signal_experiment.py -k "stratified" -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add signal_experiment.py tests/test_signal_experiment.py
git commit -m "feat: stratified eval playlist builder with signal-fair sampling"
```

---

### Task 7: Manifest tracking and cross-session dedup in `--build-playlist`

**Files:**
- Modify: `signal_experiment.py` (the `--build-playlist` handler in `main()` and related manifest functions)
- Test: `tests/test_signal_experiment.py`

- [ ] **Step 1: Write failing tests for manifest load/save and dedup**

Add to `tests/test_signal_experiment.py`:

```python
def test_load_manifest_empty(tmp_path):
    """Should return empty structure when no manifest exists."""
    from signal_experiment import load_manifest
    manifest = load_manifest(tmp_path / "manifest.json")
    assert manifest == {"sessions": []}


def test_load_manifest_existing(tmp_path):
    """Should load existing manifest."""
    from signal_experiment import load_manifest
    data = {"sessions": [{"session_id": 1, "artists": [{"name": "haken"}]}]}
    (tmp_path / "manifest.json").write_text(json.dumps(data))
    manifest = load_manifest(tmp_path / "manifest.json")
    assert len(manifest["sessions"]) == 1


def test_get_prior_artists_from_manifest():
    """Should extract all artist names from prior sessions."""
    from signal_experiment import get_prior_artists
    manifest = {"sessions": [
        {"session_id": 1, "artists": [
            {"name": "haken", "stratum": "solo:favorites", "added": True},
            {"name": "tool", "stratum": "solo:playcount", "added": False},
        ]},
        {"session_id": 2, "artists": [
            {"name": "meshuggah", "stratum": "blend:Config A", "added": True},
        ]},
    ]}
    prior = get_prior_artists(manifest)
    assert prior == {"haken", "tool", "meshuggah"}


def test_save_manifest_appends_session(tmp_path):
    """Should append a new session to the manifest."""
    from signal_experiment import load_manifest, save_manifest_session
    manifest_path = tmp_path / "manifest.json"
    manifest = load_manifest(manifest_path)
    artists = [{"name": "haken", "stratum": "solo:favorites", "rank": 1, "added": True}]
    save_manifest_session(manifest_path, manifest, artists)
    reloaded = load_manifest(manifest_path)
    assert len(reloaded["sessions"]) == 1
    assert reloaded["sessions"][0]["artists"][0]["name"] == "haken"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_signal_experiment.py -k "manifest" -v`
Expected: FAIL (functions don't exist)

- [ ] **Step 3: Implement manifest functions**

Add to `signal_experiment.py`:

```python
def load_manifest(path):
    """Load the eval playlist manifest, or return empty structure."""
    path = pathlib.Path(path)
    if path.exists():
        return json.loads(path.read_text())
    return {"sessions": []}


def get_prior_artists(manifest):
    """Extract all artist names from prior manifest sessions."""
    artists = set()
    for session in manifest.get("sessions", []):
        for entry in session.get("artists", []):
            artists.add(entry["name"])
    return artists


def save_manifest_session(path, manifest, artists):
    """Append a new session to the manifest and write to disk."""
    import datetime
    session_id = len(manifest.get("sessions", [])) + 1
    manifest["sessions"].append({
        "date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "session_id": session_id,
        "artists": artists,
    })
    pathlib.Path(path).write_text(json.dumps(manifest, indent=2))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_signal_experiment.py -k "manifest" -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Update `--build-playlist` handler to use manifest and stratified builder**

In `signal_experiment.py`, rewrite the `--build-playlist` block in `main()`. The new version should:
1. Load saved recs (phase_d) AND phase_a results (save phase_a in the full run too)
2. Load manifest, get prior artists
3. Call `build_stratified_artist_list(phase_a, phase_d, target_total=105, exclude=eval_exclude, prior_artists=prior)`
4. Build the playlist, tracking which artists were successfully added
5. Save manifest session with added/not-added status

The full run (`run_experiment`) also needs to save phase_a results alongside phase_d. Add this after the existing `recs_path.write_text(...)`:

```python
    phase_a_path = cache_dir / "signal_wargaming_phase_a.json"
    serializable_a = {}
    for sig, data in phase_a.items():
        serializable_a[sig] = {"ranked": data["ranked"]}
    phase_a_path.write_text(json.dumps(serializable_a, indent=2))
```

Note: This means `run_experiment` needs to return `phase_a` too. Update its return to `return report, phase_a, phase_d` and update the caller in `main()`.

- [ ] **Step 6: Run full test suite**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add signal_experiment.py tests/test_signal_experiment.py
git commit -m "feat: manifest tracking and cross-session dedup for eval playlist"
```

---

### Task 8: Accumulative post-listen scoring with statistical test

**Files:**
- Modify: `signal_experiment.py` (`--post-listen` handler)
- Test: `tests/test_signal_experiment.py`

- [ ] **Step 1: Write failing tests for accumulative scoring**

Add to `tests/test_signal_experiment.py`:

```python
def test_load_post_listen_history_empty(tmp_path):
    """Should return empty structure when no history exists."""
    from signal_experiment import load_post_listen_history
    history = load_post_listen_history(tmp_path / "history.json")
    assert history == {"rounds": [], "cumulative": {}}


def test_accumulate_post_listen_round():
    """Should accumulate results across rounds."""
    from signal_experiment import accumulate_post_listen_round
    history = {"rounds": [], "cumulative": {
        "total_new_favorites": 5,
        "per_config": {
            "Config A": {"hits": 3, "pool_size": 80},
        },
        "per_signal_solo": {
            "favorites": {"hits": 2, "pool_size": 13},
        },
    }}
    round_data = {
        "new_favorites": ["artist_x", "artist_y"],
        "per_config_hits": {
            "Config A": {"hits": 1, "pool_size": 80, "matched": ["artist_x"]},
        },
        "per_signal_solo_hits": {
            "favorites": {"hits": 1, "pool_size": 13, "matched": ["artist_x"]},
        },
    }
    updated = accumulate_post_listen_round(history, round_data)
    assert updated["cumulative"]["total_new_favorites"] == 7
    assert updated["cumulative"]["per_config"]["Config A"]["hits"] == 4
    assert updated["cumulative"]["per_signal_solo"]["favorites"]["hits"] == 3


def test_run_statistical_test_insufficient_data():
    """Should return None when not enough data for significance."""
    from signal_experiment import run_statistical_test
    cumulative = {
        "total_new_favorites": 10,
        "per_config": {
            "A": {"hits": 5, "pool_size": 80},
            "B": {"hits": 3, "pool_size": 80},
        },
    }
    result = run_statistical_test(cumulative)
    assert result is None  # n < 30


def test_run_statistical_test_with_enough_data():
    """Should return test results when n >= 30."""
    from signal_experiment import run_statistical_test
    cumulative = {
        "total_new_favorites": 35,
        "per_config": {
            "A": {"hits": 20, "pool_size": 200},
            "B": {"hits": 8, "pool_size": 200},
        },
    }
    result = run_statistical_test(cumulative)
    assert result is not None
    assert "best_config" in result
    assert "p_value" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_signal_experiment.py -k "post_listen_history or accumulate or statistical" -v`
Expected: FAIL (functions don't exist)

- [ ] **Step 3: Implement accumulation and statistical test functions**

Add to `signal_experiment.py`:

```python
def load_post_listen_history(path):
    """Load post-listen history, or return empty structure."""
    path = pathlib.Path(path)
    if path.exists():
        return json.loads(path.read_text())
    return {"rounds": [], "cumulative": {}}


def accumulate_post_listen_round(history, round_data):
    """Add a round's results to the cumulative history."""
    import datetime
    round_entry = {
        "date": datetime.datetime.now().strftime("%Y-%m-%d"),
        **round_data,
    }
    history["rounds"].append(round_entry)

    cum = history.get("cumulative", {})
    cum["total_new_favorites"] = cum.get("total_new_favorites", 0) + len(round_data["new_favorites"])

    # Accumulate per-config
    cum_config = cum.get("per_config", {})
    for config_name, data in round_data.get("per_config_hits", {}).items():
        if config_name not in cum_config:
            cum_config[config_name] = {"hits": 0, "pool_size": 0}
        cum_config[config_name]["hits"] += data["hits"]
        cum_config[config_name]["pool_size"] += data["pool_size"]
    cum["per_config"] = cum_config

    # Accumulate per-signal solo
    cum_solo = cum.get("per_signal_solo", {})
    for sig, data in round_data.get("per_signal_solo_hits", {}).items():
        if sig not in cum_solo:
            cum_solo[sig] = {"hits": 0, "pool_size": 0}
        cum_solo[sig]["hits"] += data["hits"]
        cum_solo[sig]["pool_size"] += data["pool_size"]
    cum["per_signal_solo"] = cum_solo

    history["cumulative"] = cum
    return history


def run_statistical_test(cumulative, min_n=30):
    """Run Fisher's exact test on cumulative config hit rates.

    Returns None if total_new_favorites < min_n.
    Returns {"best_config": str, "p_value": float, "significant": bool} otherwise.
    """
    if cumulative.get("total_new_favorites", 0) < min_n:
        return None

    from scipy.stats import fisher_exact

    configs = cumulative.get("per_config", {})
    if len(configs) < 2:
        return None

    # Find best config by hit rate
    best_name = None
    best_rate = -1
    for name, data in configs.items():
        rate = data["hits"] / data["pool_size"] if data["pool_size"] > 0 else 0
        if rate > best_rate:
            best_rate = rate
            best_name = name

    # Test best vs second-best
    sorted_configs = sorted(configs.items(),
                            key=lambda x: x[1]["hits"] / x[1]["pool_size"] if x[1]["pool_size"] > 0 else 0,
                            reverse=True)
    if len(sorted_configs) < 2:
        return None

    best = sorted_configs[0][1]
    second = sorted_configs[1][1]
    # 2x2 contingency: [hits, misses] for each config
    table = [
        [best["hits"], best["pool_size"] - best["hits"]],
        [second["hits"], second["pool_size"] - second["hits"]],
    ]
    _, p_value = fisher_exact(table)

    return {
        "best_config": best_name,
        "p_value": p_value,
        "significant": p_value < 0.05,
        "all_rates": {
            name: {"rate": data["hits"] / data["pool_size"] * 100 if data["pool_size"] > 0 else 0,
                   "hits": data["hits"], "pool_size": data["pool_size"]}
            for name, data in configs.items()
        },
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_signal_experiment.py -k "post_listen_history or accumulate or statistical" -v`
Expected: All PASS

- [ ] **Step 5: Rewrite `--post-listen` handler in `main()`**

The new `--post-listen` handler should:
1. Get new favorites (as before)
2. Load saved recs AND phase_a results AND manifest
3. Score against per-config ranked lists (using manifest's actual offered artists, not fixed top-N)
4. Score against per-signal solo lists from phase_a
5. Build round_data, accumulate into history
6. Save history
7. Run statistical test if n >= 30
8. Print current round + cumulative results

```python
    if args.post_listen:
        new_favorites = parse_library_jxa()
        fav_snapshot_path = cache_dir / "favorites_snapshot.json"
        if not fav_snapshot_path.exists():
            log.error("No favorites snapshot found. Run the experiment first.")
            sys.exit(1)
        old_favorites = json.loads(fav_snapshot_path.read_text())
        new_fav_artists = set(new_favorites.keys()) - set(old_favorites.keys())
        log.info(f"\nNew favorites since last run: {len(new_fav_artists)} artists")
        if new_fav_artists:
            log.info(f"  {', '.join(sorted(new_fav_artists))}")

        recs_path = cache_dir / "signal_wargaming_recs.json"
        if not recs_path.exists():
            log.error("No saved recommendations found. Run the experiment first.")
            sys.exit(1)
        saved_recs = json.loads(recs_path.read_text())

        phase_a_path = cache_dir / "signal_wargaming_phase_a.json"
        saved_phase_a = json.loads(phase_a_path.read_text()) if phase_a_path.exists() else {}

        manifest_path = cache_dir / "eval_playlist_manifest.json"
        manifest = load_manifest(manifest_path)

        # Get offered artists from most recent session
        offered = set()
        if manifest["sessions"]:
            latest = manifest["sessions"][-1]
            offered = {e["name"] for e in latest["artists"] if e.get("added", False)}

        # Score per-config
        per_config_hits = {}
        for rec in saved_recs:
            top_names = [name for _, name in rec["ranked"]]
            offered_from_config = [n for n in top_names if n in offered]
            hits = [n for n in offered_from_config if n in new_fav_artists]
            pool = len(offered) if offered else len(top_names[:80])
            per_config_hits[rec["name"]] = {
                "hits": len(hits),
                "pool_size": pool,
                "matched": hits,
            }

        # Score per-signal solo
        per_signal_solo_hits = {}
        for sig, data in saved_phase_a.items():
            solo_names = [name for _, name in data.get("ranked", [])]
            offered_from_sig = [n for n in solo_names if n in offered]
            hits = [n for n in offered_from_sig if n in new_fav_artists]
            per_signal_solo_hits[sig] = {
                "hits": len(hits),
                "pool_size": len(offered_from_sig),
                "matched": hits,
            }

        # Print current round
        log.info("\n=== Post-Listen Scoring (This Round) ===\n")
        for name, data in per_config_hits.items():
            log.info(f"{name}: {data['hits']} hits")
            if data["matched"]:
                log.info(f"  Matched: {', '.join(data['matched'])}")

        log.info("\n--- Per-Signal Solo ---")
        for sig, data in per_signal_solo_hits.items():
            log.info(f"{sig}: {data['hits']} hits")
            if data["matched"]:
                log.info(f"  Matched: {', '.join(data['matched'])}")

        # Accumulate
        history_path = cache_dir / "post_listen_history.json"
        history = load_post_listen_history(history_path)
        round_data = {
            "new_favorites": sorted(new_fav_artists),
            "per_config_hits": per_config_hits,
            "per_signal_solo_hits": per_signal_solo_hits,
        }
        history = accumulate_post_listen_round(history, round_data)
        pathlib.Path(history_path).write_text(json.dumps(history, indent=2))

        # Cumulative summary
        cum = history["cumulative"]
        log.info(f"\n=== Cumulative ({cum['total_new_favorites']} total favorites) ===\n")
        for name, data in cum.get("per_config", {}).items():
            rate = data["hits"] / data["pool_size"] * 100 if data["pool_size"] > 0 else 0
            log.info(f"{name}: {data['hits']} hits / {data['pool_size']} offered ({rate:.1f}%)")

        # Statistical test
        stat_result = run_statistical_test(cum)
        if stat_result is None:
            remaining = 30 - cum["total_new_favorites"]
            log.info(f"\nNeed ~{remaining} more favorites for statistical significance.")
        elif stat_result["significant"]:
            log.info(f"\n*** {stat_result['best_config']} is statistically best (p={stat_result['p_value']:.4f}) ***")
        else:
            log.info(f"\nNo config statistically distinguishable yet (p={stat_result['p_value']:.4f})")

        # Update favorites snapshot for next round
        fav_snapshot_path.write_text(json.dumps(new_favorites, indent=2))
        return
```

- [ ] **Step 6: Run full test suite**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add signal_experiment.py tests/test_signal_experiment.py
git commit -m "feat: accumulative post-listen scoring with Fisher's exact test"
```

---

### Task 9: Update full experiment run to save phase_a and use new flow

**Files:**
- Modify: `signal_experiment.py` (the default run path in `main()`)

- [ ] **Step 1: Update `run_experiment` to return phase_a**

In `signal_experiment.py`, modify `run_experiment` to also return `phase_a`:

```python
def run_experiment(signals, scrape_cache, apple_cache, rejected_cache,
                   user_blocklist, top_n=TOP_N,
                   filter_cache=None, file_blocklist=frozenset()):
    """Run all four analysis phases and generate the report."""
    scoring_kwargs = {
        "apple_cache": apple_cache,
        "apple_weight": 0.2,
        "blocklist_cache": rejected_cache,
        "user_blocklist": user_blocklist,
        "filter_cache": filter_cache,
        "file_blocklist": file_blocklist,
    }

    log.info("\n--- Phase A: Individual Signal Profiling ---")
    phase_a = run_phase_a(scrape_cache, signals, top_n=top_n, **scoring_kwargs)

    log.info("--- Phase B: Ablation ---")
    phase_b = run_phase_b(scrape_cache, signals, top_n=top_n, **scoring_kwargs)

    log.info("--- Phase C: Degraded Scenarios ---")
    phase_c = run_phase_c(scrape_cache, signals, top_n=top_n, **scoring_kwargs)

    log.info("--- Phase D: Recommendations ---")
    phase_d = run_phase_d(scrape_cache, signals, top_n=top_n, **scoring_kwargs)

    library_count = len(set().union(
        signals["favorites"].keys(),
        signals["playcount"].keys(),
        signals["playlists"].keys(),
    ))
    report = generate_wargaming_report(phase_a, phase_b, phase_c, phase_d,
                                        library_count=library_count, top_n=top_n)

    return report, phase_a, phase_d
```

- [ ] **Step 2: Update `main()` default run path**

Update the caller to unpack 3 return values and save phase_a:

```python
    report, phase_a, phase_d = run_experiment(
        signals, scrape_cache, apple_cache, rejected_cache,
        user_blocklist, top_n=args.top_n,
        filter_cache=filter_cache, file_blocklist=file_blocklist)

    # ... existing report and recs saving ...

    # Save phase_a for stratified playlist building
    phase_a_path = cache_dir / "signal_wargaming_phase_a.json"
    serializable_a = {}
    for sig, data in phase_a.items():
        serializable_a[sig] = {"ranked": data["ranked"]}
    phase_a_path.write_text(json.dumps(serializable_a, indent=2))
```

Also update the eval artists display at the end to use the new `build_stratified_artist_list` instead of `get_evaluation_artists`.

- [ ] **Step 3: Update integration test for new return value**

In `tests/test_signal_experiment.py`, update `test_full_experiment_produces_report`:

```python
    report, phase_a, phase_d = run_experiment(...)
    assert "Phase A" in report
    assert "ratings" in phase_a  # ratings should be in phase_a
```

- [ ] **Step 4: Run full test suite**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add signal_experiment.py tests/test_signal_experiment.py
git commit -m "feat: save phase_a results, update experiment flow for stratified eval"
```

---

### Task 10: Update `--build-playlist` handler for stratified + manifest flow

**Files:**
- Modify: `signal_experiment.py` (`--build-playlist` block in `main()`)

- [ ] **Step 1: Rewrite `--build-playlist` handler**

Replace the existing `--build-playlist` block in `main()` with:

```python
    if args.build_playlist:
        recs_path = cache_dir / "signal_wargaming_recs.json"
        if not recs_path.exists():
            log.error("No saved recommendations found. Run the experiment first.")
            sys.exit(1)
        saved_recs = json.loads(recs_path.read_text())

        phase_a_path = cache_dir / "signal_wargaming_phase_a.json"
        if not phase_a_path.exists():
            log.error("No phase A results found. Run the experiment first.")
            sys.exit(1)
        saved_phase_a = json.loads(phase_a_path.read_text())

        manifest_path = cache_dir / "eval_playlist_manifest.json"
        manifest = load_manifest(manifest_path)
        prior_artists = get_prior_artists(manifest)
        if prior_artists:
            log.info(f"Excluding {len(prior_artists)} artists from prior sessions.")

        artist_list = build_stratified_artist_list(
            saved_phase_a, saved_recs,
            target_total=105, exclude=eval_exclude, prior_artists=prior_artists)

        log.info(f"\nBuilding evaluation playlist with {len(artist_list)} target artists...")

        # Show stratum breakdown
        strata = {}
        for entry in artist_list:
            s = entry["stratum"].split(":")[0]
            strata[s] = strata.get(s, 0) + 1
        for s, count in strata.items():
            log.info(f"  {s}: {count} artists")

        from music_discovery import (
            search_itunes, fetch_top_tracks, RATE_LIMIT,
        )
        import time

        playlist_name = "_TESTING Signal Wargaming"
        if not _setup_named_playlist(playlist_name):
            log.error("Could not create playlist — aborting.")
            sys.exit(1)

        api_key = os.environ.get("LASTFM_API_KEY")
        for i, entry in enumerate(artist_list, 1):
            artist = entry["name"]
            log.info(f"[{i}/{len(artist_list)}] {artist} ({entry['stratum']})")
            tracks = fetch_top_tracks(artist, api_key) if api_key else []
            added = False
            for track in tracks[:3]:
                if _add_track_to_named_playlist(artist, track["name"], playlist_name):
                    entry["added"] = True
                    added = True
                    break
            if not added:
                entry["added"] = False
            time.sleep(RATE_LIMIT)

        added_count = sum(1 for e in artist_list if e.get("added", False))
        log.info(f"\nEvaluation playlist '{playlist_name}' built: "
                 f"{added_count} tracks from {len(artist_list)} target artists.")

        save_manifest_session(manifest_path, manifest, artist_list)
        log.info(f"Manifest saved ({len(manifest['sessions'])} sessions total).")

        log.info("Listen, favorite what you like, then run:")
        log.info("  python signal_experiment.py --post-listen")
        return
```

- [ ] **Step 2: Run full test suite**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add signal_experiment.py
git commit -m "feat: stratified --build-playlist with manifest tracking"
```

---

### Task 11: Verify scipy dependency is available

**Files:**
- Check: system Python packages

- [ ] **Step 1: Check if scipy is installed**

Run: `python3 -c "from scipy.stats import fisher_exact; print('scipy OK')"`

If not installed:

Run: `pip3 install scipy`

- [ ] **Step 2: Commit requirements update if needed**

If there's a `requirements.txt`, add `scipy`. If not, check how dependencies are managed in the project and follow that pattern.

```bash
git add requirements.txt
git commit -m "deps: add scipy for statistical testing"
```

---

### Task 12: End-to-end smoke test

**Files:**
- No file changes — validation only

- [ ] **Step 1: Run full test suite**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/ -v`
Expected: All PASS, no regressions

- [ ] **Step 2: Verify ratings collection works with real data**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -c "from signal_collectors import collect_ratings_jxa; r = collect_ratings_jxa(); print(f'{len(r)} artists'); import statistics; vals = [d[\"avg_centered\"] for d in r.values()]; print(f'mean={statistics.mean(vals):.3f}, min={min(vals):.3f}, max={max(vals):.3f}')"`

Expected: ~4454 artists, mean near -0.1 to 0.1 (centered around neutral), range from -1.0 to +1.0.

- [ ] **Step 3: Verify full experiment run (dry run)**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 signal_experiment.py --skip-api 2>&1 | tail -30`

Expected: Report generated with ratings signal in Phase A, new configs in Phase D, phase_a saved alongside recs.

- [ ] **Step 4: Verify signal_wargaming_phase_a.json was created**

Run: `ls -la /Users/brianhill/.cache/music_discovery/signal_wargaming_phase_a.json`

Expected: File exists with recent timestamp.
