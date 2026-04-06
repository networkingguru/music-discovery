# Seed Injection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make favorited discovery artists expand the candidate pool by scraping them as new seed nodes during `--feedback`, and add a `--reset` flag to wipe adaptive state.

**Architecture:** A new helper function `_scrape_new_favorites()` called from `_run_feedback()` after feedback replay. It detects newly favorited discovery artists, scrapes music-map and Last.fm for similar artists, and adds edges to the affinity graph. A separate `_run_reset()` function deletes learned state files while preserving expensive caches.

**Tech Stack:** Python 3, requests (HTTP scraping), BeautifulSoup (HTML parsing), Apple Music JXA (library reads)

**Spec:** `docs/superpowers/specs/2026-04-06-seed-injection-design.md`

---

### Task 1: `_run_reset()` function and CLI flag

**Files:**
- Modify: `adaptive_engine.py:1525-1540` (CLI parser)
- Modify: `adaptive_engine.py` (add `_run_reset` function near other `_run_*` functions)
- Modify: `adaptive_engine.py` (main dispatch block)
- Test: `tests/test_adaptive_engine.py`

- [ ] **Step 1: Write failing tests for reset**

Add to `tests/test_adaptive_engine.py`:

```python
class TestRunReset:
    """Tests for _run_reset() — wipes adaptive state, preserves caches."""

    def _populate_cache_dir(self, cache_dir):
        """Create all expected files in cache_dir for testing."""
        # Files that should be DELETED
        delete_files = [
            "feedback_history.json",
            "model_weights.json",
            "affinity_graph.json",
            "pre_listen_snapshot.json",
            "library_faves_snapshot.json",
            "offered_features.json",
            "search_strikes.json",
            "weight_model.json",
            "playlist_explanation.txt",
        ]
        # Files that should be PRESERVED
        preserve_files = [
            "offered_tracks.json",
            "music_map_cache.json",
            "filter_cache.json",
            "ai_detection_log.txt",
            "playcount_cache.json",
            "ratings_cache.json",
            "playlist_membership_cache.json",
            "heavy_rotation_cache.json",
            "recommendations_cache.json",
            "apple_music_cache.json",
        ]
        for f in delete_files + preserve_files:
            (cache_dir / f).write_text("{}")
        return delete_files, preserve_files

    def test_deletes_correct_files(self, tmp_path):
        from adaptive_engine import _run_reset
        delete_files, preserve_files = self._populate_cache_dir(tmp_path)
        _run_reset(tmp_path)
        for f in delete_files:
            assert not (tmp_path / f).exists(), f"Should have been deleted: {f}"
        for f in preserve_files:
            assert (tmp_path / f).exists(), f"Should have been preserved: {f}"

    def test_handles_missing_files(self, tmp_path):
        from adaptive_engine import _run_reset
        # Only create one file — rest are missing
        (tmp_path / "feedback_history.json").write_text("{}")
        _run_reset(tmp_path)  # Should not raise
        assert not (tmp_path / "feedback_history.json").exists()

    def test_preserves_offered_tracks(self, tmp_path):
        from adaptive_engine import _run_reset
        self._populate_cache_dir(tmp_path)
        (tmp_path / "offered_tracks.json").write_text(
            '{"version": 1, "tracks": [{"artist": "deftones", "track": "change", "round": 1}]}'
        )
        _run_reset(tmp_path)
        assert (tmp_path / "offered_tracks.json").exists()
        import json
        data = json.loads((tmp_path / "offered_tracks.json").read_text())
        assert len(data["tracks"]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_adaptive_engine.py::TestRunReset -v`
Expected: FAIL with `ImportError: cannot import name '_run_reset'`

- [ ] **Step 3: Implement `_run_reset()`**

Add to `adaptive_engine.py`, before `_run_feedback()` (around line 1305):

```python
def _run_reset(cache_dir: pathlib.Path):
    """Wipe adaptive state for a clean re-seed. Preserves expensive caches."""
    log.info("=== Reset Mode ===")

    delete_files = [
        "feedback_history.json",
        "model_weights.json",
        "affinity_graph.json",
        "pre_listen_snapshot.json",
        "library_faves_snapshot.json",
        "offered_features.json",
        "search_strikes.json",
        "weight_model.json",
        "playlist_explanation.txt",
    ]

    # Count what we're losing for the summary
    fb_path = cache_dir / "feedback_history.json"
    if fb_path.exists():
        try:
            import json as _json
            fb_data = _json.loads(fb_path.read_text(encoding="utf-8"))
            rounds = fb_data.get("rounds", [])
            total_artists = sum(
                len(r.get("artist_feedback", {})) for r in rounds
            )
            log.info("  Deleting feedback from %d rounds (%d artist evaluations).",
                     len(rounds), total_artists)
        except Exception:
            pass

    deleted = 0
    for filename in delete_files:
        path = cache_dir / filename
        if path.exists():
            path.unlink()
            log.info("  Deleted: %s", filename)
            deleted += 1
        else:
            log.debug("  Skipped (not found): %s", filename)

    log.info("Reset complete: %d files deleted.", deleted)
    log.info("Preserved: caches (music_map, filter, signal), offered_tracks, ai_detection_log.")
    log.info("\nRun --seed to rebuild the adaptive model from your current library.")
```

- [ ] **Step 4: Add `--reset` to CLI parser and dispatch**

In the mutually exclusive group at line 1525, add:

```python
group.add_argument(
    "--reset",
    action="store_true",
    help="Wipe adaptive state (feedback, model, graph) for clean re-seed",
)
```

In the dispatch block (around line 1555), add before the existing if/elif chain:

```python
if args.reset:
    _run_reset(cache_dir)
elif args.seed:
```

(Change the existing `if args.seed:` to `elif args.seed:`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_adaptive_engine.py::TestRunReset -v`
Expected: 3 PASS

- [ ] **Step 6: Run full test suite**

Run: `pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add adaptive_engine.py tests/test_adaptive_engine.py
git commit -m "feat: add --reset flag to wipe adaptive state for clean re-seed"
```

---

### Task 2: Detect newly favorited discovery artists

**Files:**
- Modify: `adaptive_engine.py` (add `_detect_new_favorite_seeds()` helper)
- Test: `tests/test_adaptive_engine.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_adaptive_engine.py`:

```python
class TestDetectNewFavoriteSeeds:
    """Tests for _detect_new_favorite_seeds() — finds discovery artists
    that were favorited and not yet scraped."""

    def test_basic_detection(self):
        from adaptive_engine import _detect_new_favorite_seeds
        history = [
            {"artist_feedback": {"deftones": {"fave_tracks": 1}, "tool": {"fave_tracks": 0}}},
            {"artist_feedback": {"agent fresco": {"fave_tracks": 2}}},
        ]
        favorites = {"deftones": 3, "agent fresco": 1, "radiohead": 9}
        scrape_cache = {"radiohead": {"thom yorke": 0.9}, "tool": {"apc": 0.8}}
        result = _detect_new_favorite_seeds(history, favorites, scrape_cache)
        assert "deftones" in result
        assert "agent fresco" in result
        assert "radiohead" not in result  # already in scrape cache
        assert "tool" not in result  # already in scrape cache

    def test_case_insensitive_cache_check(self):
        from adaptive_engine import _detect_new_favorite_seeds
        history = [{"artist_feedback": {"deftones": {"fave_tracks": 1}}}]
        favorites = {"deftones": 3}
        scrape_cache = {"Deftones": {"tool": 0.8}}  # Title case in cache
        result = _detect_new_favorite_seeds(history, favorites, scrape_cache)
        assert len(result) == 0  # should recognize Deftones == deftones

    def test_cap_at_10(self):
        from adaptive_engine import _detect_new_favorite_seeds
        history = [{"artist_feedback": {f"artist_{i}": {"fave_tracks": 1} for i in range(15)}}]
        favorites = {f"artist_{i}": 1 for i in range(15)}
        scrape_cache = {}
        result = _detect_new_favorite_seeds(history, favorites, scrape_cache)
        assert len(result) == 10

    def test_empty_favorites(self):
        from adaptive_engine import _detect_new_favorite_seeds
        history = [{"artist_feedback": {"deftones": {"fave_tracks": 1}}}]
        favorites = {}
        scrape_cache = {}
        result = _detect_new_favorite_seeds(history, favorites, scrape_cache)
        assert len(result) == 0

    def test_no_history(self):
        from adaptive_engine import _detect_new_favorite_seeds
        history = []
        favorites = {"deftones": 3}
        scrape_cache = {}
        result = _detect_new_favorite_seeds(history, favorites, scrape_cache)
        assert len(result) == 0

    def test_only_favorited_discovery_artists(self):
        """Artists offered but NOT favorited in library should not be scraped."""
        from adaptive_engine import _detect_new_favorite_seeds
        history = [{"artist_feedback": {"deftones": {"fave_tracks": 1}, "tool": {"fave_tracks": 0}}}]
        favorites = {"deftones": 3}  # tool not in library favorites
        scrape_cache = {}
        result = _detect_new_favorite_seeds(history, favorites, scrape_cache)
        assert "deftones" in result
        assert "tool" not in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_adaptive_engine.py::TestDetectNewFavoriteSeeds -v`
Expected: FAIL with `ImportError: cannot import name '_detect_new_favorite_seeds'`

- [ ] **Step 3: Implement `_detect_new_favorite_seeds()`**

Add to `adaptive_engine.py`, before `_run_feedback()`:

```python
MAX_SCRAPE_PER_ROUND = 10


def _detect_new_favorite_seeds(
    history: list,
    favorites: dict,
    scrape_cache: dict,
) -> list[str]:
    """Find discovery artists that the user favorited and haven't been scraped yet.

    Returns a list of artist names (lowercase), capped at MAX_SCRAPE_PER_ROUND.

    An artist qualifies if:
    - It appeared in any round's artist_feedback (was offered as a discovery candidate)
    - It is present in the current library favorites dict
    - It is NOT already a key in the scrape cache (case-insensitive)
    """
    # All artists ever offered in discovery
    offered = set()
    for rnd in history:
        offered.update(rnd.get("artist_feedback", {}).keys())

    # Case-insensitive set of already-scraped artists
    scraped_lower = {k.lower() for k in scrape_cache}

    new_seeds = [
        artist for artist in offered
        if artist in favorites and artist.lower() not in scraped_lower
    ]

    # Deterministic order (alphabetical) so results are reproducible
    new_seeds.sort()

    if len(new_seeds) > MAX_SCRAPE_PER_ROUND:
        log.info("  Capping new seed scraping at %d (found %d).",
                 MAX_SCRAPE_PER_ROUND, len(new_seeds))
        new_seeds = new_seeds[:MAX_SCRAPE_PER_ROUND]

    return new_seeds
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_adaptive_engine.py::TestDetectNewFavoriteSeeds -v`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add adaptive_engine.py tests/test_adaptive_engine.py
git commit -m "feat: detect newly favorited discovery artists for seed injection"
```

---

### Task 3: `_scrape_new_favorites()` helper function

**Files:**
- Modify: `adaptive_engine.py` (add `_scrape_new_favorites()`)
- Test: `tests/test_adaptive_engine.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_adaptive_engine.py`:

```python
from unittest.mock import patch, MagicMock


class TestScrapeNewFavorites:
    """Tests for _scrape_new_favorites() — scrapes music-map and Last.fm
    for newly favorited discovery artists."""

    def test_scrapes_and_adds_edges(self):
        from adaptive_engine import _scrape_new_favorites
        from affinity_graph import AffinityGraph

        graph = AffinityGraph()
        scrape_cache = {}
        filter_cache = {}
        new_seeds = ["deftones"]

        mock_scraper = MagicMock(return_value={
            "tool": 0.9, "korn": 0.7, "incubus": 0.5
        })

        with patch("adaptive_engine.detect_scraper", return_value=mock_scraper):
            with patch("adaptive_engine.fetch_filter_data", return_value={
                "listeners": 5000,
                "similar_artists": [
                    {"name": "Tool", "match": 0.8},
                    {"name": "Korn", "match": 0.6},
                ],
            }):
                with patch("adaptive_engine.time.sleep"):
                    _scrape_new_favorites(
                        new_seeds=new_seeds,
                        graph=graph,
                        scrape_cache=scrape_cache,
                        filter_cache=filter_cache,
                        api_key="test_key",
                    )

        # Scrape cache updated
        assert "deftones" in scrape_cache
        assert scrape_cache["deftones"]["tool"] == 0.9

        # Musicmap edges added (lowercased)
        assert graph.neighbors_musicmap("deftones")
        assert "tool" in graph.neighbors_musicmap("deftones")

        # Last.fm edges added
        assert "tool" in graph.neighbors_lastfm("deftones")

        # Filter cache updated
        assert "deftones" in filter_cache

    def test_empty_scrape_result(self):
        from adaptive_engine import _scrape_new_favorites
        from affinity_graph import AffinityGraph

        graph = AffinityGraph()
        scrape_cache = {}
        filter_cache = {}

        mock_scraper = MagicMock(return_value={})

        with patch("adaptive_engine.detect_scraper", return_value=mock_scraper):
            with patch("adaptive_engine.fetch_filter_data", return_value={}):
                with patch("adaptive_engine.time.sleep"):
                    _scrape_new_favorites(
                        new_seeds=["unknown_artist"],
                        graph=graph,
                        scrape_cache=scrape_cache,
                        filter_cache=filter_cache,
                        api_key="test_key",
                    )

        # Empty result should NOT create a cache key
        assert "unknown_artist" not in scrape_cache

    def test_no_api_key_skips_lastfm(self):
        from adaptive_engine import _scrape_new_favorites
        from affinity_graph import AffinityGraph

        graph = AffinityGraph()
        scrape_cache = {}
        filter_cache = {}

        mock_scraper = MagicMock(return_value={"tool": 0.9})

        with patch("adaptive_engine.detect_scraper", return_value=mock_scraper):
            with patch("adaptive_engine.fetch_filter_data") as mock_fetch:
                with patch("adaptive_engine.time.sleep"):
                    _scrape_new_favorites(
                        new_seeds=["deftones"],
                        graph=graph,
                        scrape_cache=scrape_cache,
                        filter_cache=filter_cache,
                        api_key=None,
                    )

        # Last.fm should not be called
        mock_fetch.assert_not_called()

        # Musicmap edges still added
        assert "deftones" in scrape_cache

    def test_lastfm_zero_match_filtered(self):
        from adaptive_engine import _scrape_new_favorites
        from affinity_graph import AffinityGraph

        graph = AffinityGraph()
        scrape_cache = {}
        filter_cache = {}

        mock_scraper = MagicMock(return_value={"tool": 0.9})

        with patch("adaptive_engine.detect_scraper", return_value=mock_scraper):
            with patch("adaptive_engine.fetch_filter_data", return_value={
                "similar_artists": [
                    {"name": "Tool", "match": 0.8},
                    {"name": "Zero", "match": 0.0},
                    {"name": "", "match": 0.5},
                ],
            }):
                with patch("adaptive_engine.time.sleep"):
                    _scrape_new_favorites(
                        new_seeds=["deftones"],
                        graph=graph,
                        scrape_cache=scrape_cache,
                        filter_cache=filter_cache,
                        api_key="test_key",
                    )

        lastfm_neighbors = graph.neighbors_lastfm("deftones")
        assert "tool" in lastfm_neighbors
        assert "zero" not in lastfm_neighbors  # match == 0.0 filtered

    def test_detect_scraper_failure(self):
        from adaptive_engine import _scrape_new_favorites
        from affinity_graph import AffinityGraph

        graph = AffinityGraph()
        scrape_cache = {}
        filter_cache = {}

        with patch("adaptive_engine.detect_scraper", side_effect=Exception("network down")):
            with patch("adaptive_engine.time.sleep"):
                # Should not raise
                _scrape_new_favorites(
                    new_seeds=["deftones"],
                    graph=graph,
                    scrape_cache=scrape_cache,
                    filter_cache=filter_cache,
                    api_key="test_key",
                )

        assert len(scrape_cache) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_adaptive_engine.py::TestScrapeNewFavorites -v`
Expected: FAIL with `ImportError: cannot import name '_scrape_new_favorites'`

- [ ] **Step 3: Implement `_scrape_new_favorites()`**

Add to `adaptive_engine.py`, after `_detect_new_favorite_seeds()`:

```python
def _scrape_new_favorites(
    new_seeds: list[str],
    graph,
    scrape_cache: dict,
    filter_cache: dict,
    api_key: str | None,
):
    """Scrape music-map and Last.fm for newly favorited discovery artists.

    Adds edges to graph, updates scrape_cache and filter_cache in-place.
    Logs progress for user visibility. Failures are non-fatal per-artist.
    """
    import time

    if not new_seeds:
        return

    log.info("Detected %d newly favorited discovery artist(s): %s",
             len(new_seeds), ", ".join(new_seeds))

    try:
        from music_discovery import detect_scraper, fetch_filter_data
        scrape_fn = detect_scraper()
    except Exception as e:
        log.error("  Could not initialise scraper: %s. Skipping seed expansion.", e)
        return

    candidates_before = sum(len(v) for v in scrape_cache.values() if isinstance(v, dict))
    mm_edges_added = 0
    lfm_edges_added = 0

    for artist in new_seeds:
        # ── Music-map scraping ──────────────────────────────────
        try:
            similar = scrape_fn(artist)
        except Exception as e:
            log.warning("  Scrape failed for %s: %s", artist, e)
            time.sleep(1.0)
            continue

        if not similar:
            log.info("  Scraping music-map for %s... no results", artist)
            time.sleep(1.0)
            continue

        log.info("  Scraping music-map for %s... found %d similar artists",
                 artist, len(similar))

        scrape_cache[artist] = similar
        for neighbor, weight in similar.items():
            graph.add_edge_musicmap(artist.lower(), neighbor.lower(), weight)
            mm_edges_added += 1

        time.sleep(1.0)

        # ── Last.fm similar artists ─────────────────────────────
        if api_key:
            try:
                filter_entry = fetch_filter_data(artist, api_key)
            except Exception as e:
                log.warning("  Last.fm fetch failed for %s: %s", artist, e)
                filter_entry = {}

            if filter_entry:
                filter_cache[artist] = filter_entry
                for sim in filter_entry.get("similar_artists", []):
                    sim_name = sim.get("name", "").strip().lower()
                    match_score = float(sim.get("match", 0))
                    if sim_name and match_score > 0:
                        graph.add_edge_lastfm(artist.lower(), sim_name, match_score)
                        lfm_edges_added += 1

            time.sleep(1.0)

    candidates_after = sum(len(v) for v in scrape_cache.values() if isinstance(v, dict))
    log.info("  Seed expansion complete: +%d music-map edges, +%d Last.fm edges. "
             "Candidate pool: %d → %d",
             mm_edges_added, lfm_edges_added, candidates_before, candidates_after)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_adaptive_engine.py::TestScrapeNewFavorites -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add adaptive_engine.py tests/test_adaptive_engine.py
git commit -m "feat: scrape newly favorited discovery artists for seed expansion"
```

---

### Task 4: Wire into `_run_feedback()`

**Files:**
- Modify: `adaptive_engine.py:_run_feedback()` (lines 1309-1317 imports, lines 1436-1440 insertion point)

- [ ] **Step 1: Add imports to `_run_feedback()`**

At line 1311, after the existing `from music_discovery import parse_library_jxa, collect_track_metadata_jxa`, add:

```python
from music_discovery import (
    parse_library_jxa, collect_track_metadata_jxa,
    load_cache, save_cache, load_dotenv,
)
```

(The `detect_scraper` and `fetch_filter_data` imports are inside `_scrape_new_favorites` already.)

- [ ] **Step 2: Add scraping block after feedback replay**

After line 1436 (the end of the feedback replay loop) and before line 1438 (`graph.propagate()`), insert:

```python
    # ── 10c. Scrape newly favorited discovery artists ───────────────────
    load_dotenv()
    api_key = os.environ.get("LASTFM_API_KEY", "").strip() or None

    scrape_cache_path = cache_dir / "music_map_cache.json"
    filter_cache_path = cache_dir / "filter_cache.json"
    scrape_cache = load_cache(scrape_cache_path)
    filter_cache = load_cache(filter_cache_path)

    new_seeds = _detect_new_favorite_seeds(history, favorites, scrape_cache)
    if new_seeds:
        _scrape_new_favorites(
            new_seeds=new_seeds,
            graph=graph,
            scrape_cache=scrape_cache,
            filter_cache=filter_cache,
            api_key=api_key,
        )
        save_cache(scrape_cache, scrape_cache_path)
        save_cache(filter_cache, filter_cache_path)
    else:
        log.info("No newly favorited discovery artists to scrape.")
```

- [ ] **Step 3: Run the full test suite**

Run: `pytest tests/ -x -q`
Expected: All pass (the new code path won't be exercised by existing tests since they mock everything, but no regressions)

- [ ] **Step 4: Commit**

```bash
git add adaptive_engine.py
git commit -m "feat: wire seed injection into --feedback mode"
```

---

### Task 5: Integration test and adversarial edge cases

**Files:**
- Test: `tests/test_adaptive_engine.py`

- [ ] **Step 1: Write integration and adversarial tests**

Add to `tests/test_adaptive_engine.py`:

```python
class TestSeedInjectionIntegration:
    """Integration tests: full flow from detection through graph update."""

    def test_full_flow_detection_to_graph(self):
        """Simulate: artist offered in round 1, user favorites it,
        then _detect + _scrape should add edges to graph."""
        from adaptive_engine import _detect_new_favorite_seeds, _scrape_new_favorites
        from affinity_graph import AffinityGraph

        history = [
            {"artist_feedback": {
                "caligula's horse": {"fave_tracks": 2, "skip_tracks": 0,
                                     "listen_tracks": 0, "presumed_skip_tracks": 0,
                                     "tracks_offered": 2},
            }},
        ]
        favorites = {"caligula's horse": 2}
        scrape_cache = {"radiohead": {"thom yorke": 0.9}}
        filter_cache = {}
        graph = AffinityGraph()

        # Detection
        new_seeds = _detect_new_favorite_seeds(history, favorites, scrape_cache)
        assert new_seeds == ["caligula's horse"]

        # Scraping (mocked)
        mock_scraper = MagicMock(return_value={
            "haken": 0.95, "leprous": 0.85, "tesseract": 0.7
        })

        with patch("adaptive_engine.detect_scraper", return_value=mock_scraper):
            with patch("adaptive_engine.fetch_filter_data", return_value={
                "similar_artists": [{"name": "Haken", "match": 0.9}],
            }):
                with patch("adaptive_engine.time.sleep"):
                    _scrape_new_favorites(
                        new_seeds=new_seeds,
                        graph=graph,
                        scrape_cache=scrape_cache,
                        filter_cache=filter_cache,
                        api_key="test_key",
                    )

        # Verify graph has new edges
        mm_neighbors = graph.neighbors_musicmap("caligula's horse")
        assert "haken" in mm_neighbors
        assert "leprous" in mm_neighbors
        assert "tesseract" in mm_neighbors

        lfm_neighbors = graph.neighbors_lastfm("caligula's horse")
        assert "haken" in lfm_neighbors

        # Verify scrape cache has new entry
        assert "caligula's horse" in scrape_cache
        assert len(scrape_cache) == 2  # radiohead + caligula's horse

        # Verify original cache entry unchanged
        assert scrape_cache["radiohead"] == {"thom yorke": 0.9}

    def test_scrape_failure_partial_success(self):
        """If one artist fails to scrape, others should still succeed."""
        from adaptive_engine import _scrape_new_favorites
        from affinity_graph import AffinityGraph

        graph = AffinityGraph()
        scrape_cache = {}
        filter_cache = {}

        call_count = 0

        def flaky_scraper(artist):
            nonlocal call_count
            call_count += 1
            if artist == "bad_artist":
                raise ConnectionError("timeout")
            return {"neighbor": 0.8}

        with patch("adaptive_engine.detect_scraper", return_value=flaky_scraper):
            with patch("adaptive_engine.fetch_filter_data", return_value={}):
                with patch("adaptive_engine.time.sleep"):
                    _scrape_new_favorites(
                        new_seeds=["bad_artist", "good_artist"],
                        graph=graph,
                        scrape_cache=scrape_cache,
                        filter_cache=filter_cache,
                        api_key=None,
                    )

        assert "bad_artist" not in scrape_cache
        assert "good_artist" in scrape_cache

    def test_already_in_cache_not_re_scraped(self):
        """Artist already in scrape cache should not be detected."""
        from adaptive_engine import _detect_new_favorite_seeds

        history = [{"artist_feedback": {"deftones": {"fave_tracks": 1}}}]
        favorites = {"deftones": 3}
        scrape_cache = {"deftones": {"tool": 0.9}}

        result = _detect_new_favorite_seeds(history, favorites, scrape_cache)
        assert len(result) == 0
```

- [ ] **Step 2: Run all new tests**

Run: `pytest tests/test_adaptive_engine.py -k "TestSeedInjection or TestDetectNew or TestScrapeNew or TestRunReset" -v`
Expected: All pass

- [ ] **Step 3: Run the full test suite**

Run: `pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_adaptive_engine.py
git commit -m "test: integration and adversarial tests for seed injection"
```

---

### Task 6: Manual verification with live data

- [ ] **Step 1: Verify `--reset` works**

Run: `python3 adaptive_engine.py --reset`

Expected output:
```
=== Reset Mode ===
  Deleting feedback from 3 rounds (N artist evaluations).
  Deleted: feedback_history.json
  Deleted: model_weights.json
  Deleted: affinity_graph.json
  ...
Reset complete: N files deleted.
Preserved: caches (music_map, filter, signal), offered_tracks, ai_detection_log.
Run --seed to rebuild the adaptive model from your current library.
```

Verify `offered_tracks.json` still exists:
```bash
ls -la ~/.cache/music_discovery/offered_tracks.json
```

- [ ] **Step 2: Run `--seed` to rebuild**

Run: `python3 adaptive_engine.py --seed`

Should complete without errors, rebuilding graph and model from current library.

- [ ] **Step 3: Run `--feedback` (should detect no new favorites since history was wiped)**

Run: `python3 adaptive_engine.py --feedback`

Expected: "No newly favorited discovery artists to scrape." (since feedback history is empty after reset, no discovery artists exist yet)

- [ ] **Step 4: Run `--build` to generate round 1 playlist**

Run: `python3 adaptive_engine.py --build`

Should produce a playlist. Verify it looks reasonable.

- [ ] **Step 5: Commit any adjustments**

If any fixes were needed during manual testing, commit them.
