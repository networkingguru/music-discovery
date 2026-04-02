# Adaptive Music Discovery Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static proximity-based ranking with an adaptive engine that learns signal weights from user feedback and propagates taste through a similarity graph.

**Architecture:** Two-channel scoring system. An L2-regularized logistic regression learns which signals predict favorites, while an affinity graph propagates feedback (faves, skips) through artist similarity networks. Combined via `alpha * model_score + (1-alpha) * affinity_score`. Feedback collected by diffing Music.app library state before/after each listening round.

**Tech Stack:** Python 3.14, scikit-learn (new dependency), numpy (transitive), existing: requests, beautifulsoup4, JXA/AppleScript

**Spec:** `docs/superpowers/specs/2026-04-02-adaptive-engine-design.md`

---

## MANDATORY Review Fixes

The plan was reviewed by 4 expert reviewers (correctness, test quality, architecture, spec coverage). The following bugs and gaps MUST be addressed during implementation of the relevant task. The implementing subagent should treat these as hard requirements, not suggestions.

### Per-Task Fixes

**Task 2 (JXA track metadata):**
- Use bulk JXA property access (`tracks.name()`, `tracks.skippedCount()`, etc.) instead of per-track iteration. Per-track access sends N Apple Events and will take minutes for a 10K+ track library. The existing collectors in `signal_collectors.py` show the bulk pattern.

**Task 4 (feedback.py):**
- Fix `test_create_snapshot_from_track_metadata` assertions to use lowercase keys: `("opeth", "ghost")` not `("opeth", "Ghost")` — `create_snapshot` lowercases both.
- Fix `test_create_snapshot_filters_to_offered_only` assertion: `("tool", "other")` not `("tool", "Other")`.
- `aggregate_artist_feedback` must accept and use `all_offered_tracks` (including unplayed tracks) for `tracks_offered` count. This is critical for skip attenuation — without it, offered-but-unplayed tracks aren't counted.
- Add `save_snapshot`/`load_snapshot` roundtrip test.

**Task 5 (affinity graph):**
- Fix `inject_feedback` to accumulate injections (`+=`) — already done in the plan, but callers must `reset_injections()` at the start of each `--build` run to prevent unbounded accumulation across runs. Add a `reset_injections()` method.
- Add assertion to `test_prune_removes_cold_nodes`: `assert "c" not in g.nodes`.
- The spec says listen-no-fave propagation is limited to 2 hops, not 3. Add a `max_hops` parameter to `inject_feedback` or `propagate` that can be overridden for weak signals.
- Separate propagation paths for music-map and Last.fm edges so they can be weighted independently: `propagate()` should return `{"musicmap": {artist: score}, "lastfm": {artist: score}}` or at minimum accept separate weight parameters.

**Task 6 (weight learner):**
- **Remove the sklearn load hack.** Do NOT fit a dummy model and overwrite coef_. Instead, implement `predict_proba` directly using the sigmoid formula: `1 / (1 + exp(-(bias + dot(weights, features))))`. Use sklearn only for `fit()`. The `load()` method just restores weights/bias and sets `_fitted=True`. This eliminates the fragile sklearn internal state dependency.
- `WeightLearner.__init__` must accept `signal_names` dynamically. When Last.fm username is not configured, `lastfm_loved` must be excluded from the list entirely (not fed as zeros). The caller decides which signals to include.
- Add test: `test_fit_bias_is_negative` — with ~1:9 class imbalance, the bias should be negative.
- Add test: `test_predict_proba_range_of_inputs` for load/save roundtrip (not just one point).

**Task 7 (adaptive engine, seed mode):**
- **Fix bootstrap similarity lookup.** The ternary is backwards. Replace with simple correct logic: for each candidate, iterate seed artists and collect `{seed: scrape_cache[seed].get(candidate, 0.0)}` for seeds that have non-zero proximity. Never look up the candidate as a cache key.
- **Fix `generate_apple_music_token()` call.** It requires 3 positional args: `(key_id, team_id, key_path)`. Read these from env vars (they're already used in `signal_experiment.py`). The silent `except Exception: pass` must at minimum log a warning so the user knows API signals are missing.
- **Set `ai_heuristic_score=0.0`** (not 1.0) for all bootstrap examples. The spec explicitly says new signals are 0.0 for bootstrap. 1.0 means "definitely human" which biases training.
- Wire `check_ai_artist()` to compute real ai_heuristic scores for seed mode candidates (where filter data is available).

**Task 8 (--build mode):**
- **Fix affinity normalization to preserve negative scores.** Do NOT clamp to `max(0, ...)`. Use symmetric normalization: `aff_max = max(abs(v) for v in affinity_scores.values())`, then `aff / aff_max` maps to [-1, 1]. The final_score formula handles negative affinity correctly.
- **Reset graph injections** at the start of `_run_build` before injecting library favorites and replaying feedback history.
- **Use actual `dateAdded`** from `collect_track_metadata_jxa()` for library recency instead of hardcoded `days_ago=90`.
- **Fix `add_track_to_playlist` call.** The existing function hardcodes playlist name "Music Discovery". Either pass a playlist name parameter (may require modifying music_discovery.py) or use the existing `_add_track_to_named_playlist` from signal_experiment.py.
- **Wire `generate_explanation()`** into the playlist explanation file — it exists and is tested but never called.
- **Store raw features per artist** in `offered_features.json` (already added to plan) AND copy them into the feedback round's `raw_features` field during `--feedback`.
- **Compute real `ai_heuristic_score`** via `check_ai_artist()` for candidates where filter data exists.
- **Collect Last.fm similar data** for new candidates lazily during build (via a dedicated Last.fm-only call, not the full `fetch_filter_data` which adds unnecessary MusicBrainz calls).

**Task 9 (--feedback mode):**
- **Pass `all_offered_tracks`** (from snapshot keys) to `aggregate_artist_feedback`.
- **Copy raw features** from `offered_features.json` into the feedback round's `raw_features` dict so model retraining has access to feature vectors.
- **Diff library-wide favorites** (compare current `parse_library_jxa()` with a stored library snapshot) to detect new favorites on non-discovery artists. Inject these into the affinity graph.
- **Process expunged feedback** from `artist_overrides.json`: skip expunged artist/round combinations when replaying feedback into the graph, and exclude them from model training data.

**Task 10 (integration test):**
- **Pass real feature dicts** (not `raw_features={}`) into `_collect_feedback_round`. Without this, the model refit loop is a no-op and the core adaptive behavior is untested.
- **Add round 2 and 3** to match the spec's 3-round simulation requirement. Round 3 should introduce a jazz cluster to verify the model adapts to a second taste dimension.
- **Verify model weights shift** after refitting (assert the weight for the predictive signal increased).
- **Add pagination test** for `collect_lastfm_loved` (multi-page response).

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `adaptive_engine.py` | **Create** | CLI entry point, orchestration, scoring combination |
| `weight_learner.py` | **Create** | L2 logistic regression, feature normalization, bootstrap |
| `affinity_graph.py` | **Create** | Graph construction, propagation, pruning, recency decay |
| `feedback.py` | **Create** | Snapshots, diff, feedback history, idempotency |
| `signal_collectors.py` | **Modify** | Add `collect_lastfm_loved()`, `collect_lastfm_similar()` |
| `music_discovery.py` | **Modify** | Extract Last.fm similar from `fetch_filter_data()`, add `collect_track_metadata_jxa()` |
| `requirements.txt` | **Modify** | Add scikit-learn |
| `tests/test_feedback.py` | **Create** | Tests for snapshot, diff, history |
| `tests/test_affinity_graph.py` | **Create** | Tests for graph propagation, scaling, pruning |
| `tests/test_weight_learner.py` | **Create** | Tests for model fitting, normalization |
| `tests/test_adaptive_engine.py` | **Create** | Tests for scoring combination, CLI, overrides, cooldown |
| `tests/test_signal_collectors.py` | **Modify** | Tests for new Last.fm collectors |
| `tests/test_music_discovery.py` | **Modify** | Tests for extended fetch_filter_data, track metadata |

Note: the spec puts weight learning and affinity graph in `adaptive_engine.py`. This plan splits them into separate modules (`weight_learner.py`, `affinity_graph.py`) because each is independently testable and the combined file would exceed 500 lines. `adaptive_engine.py` orchestrates both.

---

### Task 1: Extend fetch_filter_data() to return Last.fm similar artists

**Files:**
- Modify: `music_discovery.py:836-904` (fetch_filter_data return value)
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_music_discovery.py`, add:

```python
def test_fetch_filter_data_returns_similar_artists(monkeypatch):
    """fetch_filter_data extracts similar artists from getInfo response."""
    search_json = {"results": {"artistmatches": {"artist": [{"name": "Opeth"}]}}}
    getinfo_json = {
        "artist": {
            "stats": {"listeners": "500000"},
            "mbid": "",
            "bio": {"content": "Swedish band"},
            "tags": {"tag": [{"name": "metal"}]},
            "similar": {
                "artist": [
                    {"name": "Katatonia", "match": "0.85"},
                    {"name": "Porcupine Tree", "match": "0.72"},
                ]
            },
        }
    }

    call_count = {"n": 0}
    def mock_get(url, **kwargs):
        call_count["n"] += 1
        resp = type("R", (), {"status_code": 200})()
        if call_count["n"] == 1:
            resp.json = lambda: search_json
        else:
            resp.json = lambda: getinfo_json
        return resp

    monkeypatch.setattr("music_discovery.requests.get", mock_get)
    monkeypatch.setattr("music_discovery.time.sleep", lambda x: None)

    result = fetch_filter_data("opeth", "fake_key")
    assert "similar_artists" in result
    assert result["similar_artists"] == [
        {"name": "Katatonia", "match": 0.85},
        {"name": "Porcupine Tree", "match": 0.72},
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_music_discovery.py::test_fetch_filter_data_returns_similar_artists -v`
Expected: FAIL — `similar_artists` key missing from result dict

- [ ] **Step 3: Write minimal implementation**

In `music_discovery.py`, after line 841 (`tag_count = ...`), add extraction of similar artists:

```python
        similar_raw = data.get("similar", {}).get("artist", [])
        similar_artists = []
        for s in similar_raw:
            name = s.get("name", "").strip()
            try:
                match = float(s.get("match", 0))
            except (ValueError, TypeError):
                match = 0.0
            if name:
                similar_artists.append({"name": name, "match": match})
```

Then in the return dict (line 897-904), add:

```python
            "similar_artists": similar_artists,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_music_discovery.py::test_fetch_filter_data_returns_similar_artists -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_music_discovery.py -v`
Expected: All pass. Existing tests that mock `fetch_filter_data` may need `similar_artists` added to their mock return dicts if they assert on exact structure.

- [ ] **Step 6: Commit**

```bash
git add music_discovery.py tests/test_music_discovery.py
git commit -m "feat: extract Last.fm similar artists from fetch_filter_data"
```

---

### Task 2: Add JXA track metadata collector (skippedCount, dateAdded)

**Files:**
- Modify: `music_discovery.py` (add new function after `parse_library_jxa`)
- Test: `tests/test_music_discovery.py`

- [ ] **Step 1: Write the failing test**

```python
def test_collect_track_metadata_jxa(monkeypatch):
    """collect_track_metadata_jxa returns per-track skip counts, play counts, fave state, dateAdded."""
    jxa_output = json.dumps([
        {"name": "Blackwater Park", "artist": "opeth", "playedCount": 15,
         "skippedCount": 2, "favorited": True, "dateAdded": "2024-06-15T10:30:00Z"},
        {"name": "Damnation", "artist": "opeth", "playedCount": 8,
         "skippedCount": 0, "favorited": False, "dateAdded": "2024-06-15T10:30:00Z"},
    ])
    monkeypatch.setattr("music_discovery._run_jxa", lambda script: (jxa_output, 0))

    result = collect_track_metadata_jxa()
    assert len(result) == 2
    assert result[0]["name"] == "Blackwater Park"
    assert result[0]["skippedCount"] == 2
    assert result[0]["favorited"] is True
    assert result[0]["dateAdded"] == "2024-06-15T10:30:00Z"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_music_discovery.py::test_collect_track_metadata_jxa -v`
Expected: FAIL — `collect_track_metadata_jxa` not defined

- [ ] **Step 3: Write minimal implementation**

Add after `parse_library_jxa()` in `music_discovery.py`:

```python
def collect_track_metadata_jxa():
    """Collect per-track metadata via JXA: name, artist, playedCount, skippedCount, favorited, dateAdded.

    Returns list of dicts, one per track in the library.
    """
    script = """
    var app = Application("Music");
    var tracks = app.libraryPlaylists[0].tracks();
    var results = [];
    for (var i = 0; i < tracks.length; i++) {
        var t = tracks[i];
        results.push({
            name: t.name(),
            artist: t.artist().toLowerCase(),
            playedCount: t.playedCount(),
            skippedCount: t.skippedCount(),
            favorited: t.favorited(),
            dateAdded: t.dateAdded().toISOString()
        });
    }
    JSON.stringify(results);
    """
    out, code = _run_jxa(script)
    if code != 0 or not out.strip():
        log.warning("collect_track_metadata_jxa failed (code=%d)", code)
        return []
    try:
        return json.loads(out.strip())
    except json.JSONDecodeError:
        log.warning("collect_track_metadata_jxa: invalid JSON output")
        return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_music_discovery.py::test_collect_track_metadata_jxa -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add music_discovery.py tests/test_music_discovery.py
git commit -m "feat: add JXA track metadata collector (skippedCount, dateAdded)"
```

---

### Task 3: Add Last.fm loved tracks collector

**Files:**
- Modify: `signal_collectors.py` (add new function)
- Test: `tests/test_signal_collectors.py`

- [ ] **Step 1: Write the failing test**

```python
def test_collect_lastfm_loved(monkeypatch):
    """collect_lastfm_loved returns set of lowercase artist names with loved tracks."""
    page1_json = {
        "lovedtracks": {
            "track": [
                {"artist": {"name": "Opeth"}},
                {"artist": {"name": "Katatonia"}},
            ],
            "@attr": {"totalPages": "1"},
        }
    }

    def mock_get(url, **kwargs):
        resp = type("R", (), {"status_code": 200})()
        resp.json = lambda: page1_json
        resp.raise_for_status = lambda: None
        return resp

    monkeypatch.setattr("signal_collectors.requests.get", mock_get)
    result = collect_lastfm_loved("testuser", "fakekey")
    assert result == {"opeth", "katatonia"}


def test_collect_lastfm_loved_no_username():
    """collect_lastfm_loved returns empty set when username is None."""
    result = collect_lastfm_loved(None, "fakekey")
    assert result == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_signal_collectors.py::test_collect_lastfm_loved -v`
Expected: FAIL — `collect_lastfm_loved` not defined

- [ ] **Step 3: Write minimal implementation**

Add to `signal_collectors.py`:

```python
import requests

LASTFM_API_URL = "http://ws.audioscrobbler.com/2.0/"


def collect_lastfm_loved(username, api_key):
    """Fetch loved tracks from Last.fm user profile. Returns set of lowercase artist names.

    Returns empty set if username is None or API fails.
    """
    if not username:
        return set()
    artists = set()
    page = 1
    while True:
        try:
            resp = requests.get(LASTFM_API_URL, timeout=10, params={
                "method": "user.getLovedTracks",
                "user": username,
                "api_key": api_key,
                "format": "json",
                "limit": 200,
                "page": page,
            })
            resp.raise_for_status()
        except Exception as e:
            log.warning(f"Last.fm loved tracks fetch failed (page {page}): {e}")
            break
        data = resp.json().get("lovedtracks", {})
        tracks = data.get("track", [])
        if not tracks:
            break
        for t in tracks:
            name = t.get("artist", {}).get("name", "").strip()
            if name:
                artists.add(name.lower())
        total_pages = int(data.get("@attr", {}).get("totalPages", 1))
        if page >= total_pages:
            break
        page += 1
    log.info(f"  {len(artists)} loved artists from Last.fm.")
    return artists
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_signal_collectors.py::test_collect_lastfm_loved tests/test_signal_collectors.py::test_collect_lastfm_loved_no_username -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add signal_collectors.py tests/test_signal_collectors.py
git commit -m "feat: add Last.fm loved tracks collector"
```

---

### Task 4: Build feedback module (snapshots, diff, history)

**Files:**
- Create: `feedback.py`
- Create: `tests/test_feedback.py`

- [ ] **Step 1: Write failing tests for snapshot creation and diffing**

Create `tests/test_feedback.py`:

```python
"""Tests for feedback.py — snapshot, diff, history."""
import json
import pytest
from feedback import create_snapshot, diff_snapshot, FeedbackRound, load_feedback_history, save_feedback_history


def test_create_snapshot_from_track_metadata():
    """create_snapshot extracts per-track skip/play/fave keyed by artist+title."""
    tracks = [
        {"name": "Ghost", "artist": "opeth", "playedCount": 10, "skippedCount": 1, "favorited": False},
        {"name": "Burden", "artist": "opeth", "playedCount": 5, "skippedCount": 0, "favorited": True},
    ]
    offered = [("opeth", "Ghost"), ("opeth", "Burden")]
    snap = create_snapshot(tracks, offered)
    assert snap[("opeth", "ghost")] == {"played": 10, "skipped": 1, "favorited": False}
    assert snap[("opeth", "burden")] == {"played": 5, "skipped": 0, "favorited": True}


def test_create_snapshot_filters_to_offered_only():
    """create_snapshot only includes tracks that were offered in the discovery playlist."""
    tracks = [
        {"name": "Ghost", "artist": "opeth", "playedCount": 10, "skippedCount": 1, "favorited": False},
        {"name": "Other", "artist": "tool", "playedCount": 99, "skippedCount": 0, "favorited": True},
    ]
    offered = [("opeth", "Ghost")]
    snap = create_snapshot(tracks, offered)
    assert ("tool", "Other") not in snap
    assert len(snap) == 1


def test_diff_snapshot_detects_favorite():
    """diff_snapshot detects newly favorited tracks."""
    before = {("opeth", "Ghost"): {"played": 10, "skipped": 1, "favorited": False}}
    after = {("opeth", "Ghost"): {"played": 11, "skipped": 1, "favorited": True}}
    diffs = diff_snapshot(before, after)
    assert diffs[("opeth", "Ghost")]["feedback"] == "favorite"


def test_diff_snapshot_detects_skip():
    """diff_snapshot detects newly skipped tracks."""
    before = {("opeth", "Ghost"): {"played": 10, "skipped": 1, "favorited": False}}
    after = {("opeth", "Ghost"): {"played": 10, "skipped": 3, "favorited": False}}
    diffs = diff_snapshot(before, after)
    assert diffs[("opeth", "Ghost")]["feedback"] == "skip"
    assert diffs[("opeth", "Ghost")]["skip_delta"] == 2


def test_diff_snapshot_detects_listen_no_fave():
    """diff_snapshot detects played-but-not-favorited tracks."""
    before = {("opeth", "Ghost"): {"played": 10, "skipped": 1, "favorited": False}}
    after = {("opeth", "Ghost"): {"played": 12, "skipped": 1, "favorited": False}}
    diffs = diff_snapshot(before, after)
    assert diffs[("opeth", "Ghost")]["feedback"] == "listen"


def test_diff_snapshot_excludes_unplayed():
    """diff_snapshot excludes tracks with no play count change."""
    before = {("opeth", "Ghost"): {"played": 10, "skipped": 1, "favorited": False}}
    after = {("opeth", "Ghost"): {"played": 10, "skipped": 1, "favorited": False}}
    diffs = diff_snapshot(before, after)
    assert ("opeth", "Ghost") not in diffs


def test_diff_snapshot_favorite_trumps_skip():
    """If a track is both favorited and skipped (played, loved, then skipped on replay), favorite wins."""
    before = {("opeth", "Ghost"): {"played": 10, "skipped": 1, "favorited": False}}
    after = {("opeth", "Ghost"): {"played": 12, "skipped": 2, "favorited": True}}
    diffs = diff_snapshot(before, after)
    assert diffs[("opeth", "Ghost")]["feedback"] == "favorite"


def test_feedback_history_idempotency(tmp_path):
    """Saving the same round_id twice does not duplicate."""
    path = tmp_path / "history.json"
    round_data = FeedbackRound(
        round_id="2026-04-02",
        artist_feedback={"opeth": {"fave_tracks": 1, "skip_tracks": 0, "listen_tracks": 1}},
        raw_features={"opeth": {"favorites": 5, "playcount": 200}},
    )
    history = load_feedback_history(path)
    history = save_feedback_history(path, history, round_data)
    assert len(history["rounds"]) == 1

    # Save again with same round_id
    history = save_feedback_history(path, history, round_data)
    assert len(history["rounds"]) == 1  # Still 1, not 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_feedback.py -v`
Expected: FAIL — `feedback` module not found

- [ ] **Step 3: Write implementation**

Create `feedback.py`:

```python
"""Feedback collection for adaptive music discovery.

Handles pre/post-listen snapshots, diffing, per-artist aggregation,
and feedback history with idempotency.
"""
import json
import logging
import pathlib
from dataclasses import dataclass, field, asdict

log = logging.getLogger(__name__)


@dataclass
class FeedbackRound:
    round_id: str
    artist_feedback: dict = field(default_factory=dict)  # {artist: {fave_tracks, skip_tracks, listen_tracks}}
    raw_features: dict = field(default_factory=dict)      # {artist: {signal: value, ...}} for training


def create_snapshot(track_metadata, offered_tracks):
    """Create a snapshot of per-track state for offered discovery tracks.

    Args:
        track_metadata: list of dicts from collect_track_metadata_jxa()
        offered_tracks: list of (artist_lower, track_name) tuples in the playlist

    Returns:
        dict keyed by (artist, track_name) with {played, skipped, favorited}
    """
    offered_set = {(a.lower(), n.lower()) for a, n in offered_tracks}
    # Index track metadata by (artist, name) for fast lookup
    snap = {}
    for t in track_metadata:
        key = (t["artist"].lower(), t["name"].lower())
        if key in offered_set:
            snap[key] = {
                "played": t["playedCount"],
                "skipped": t["skippedCount"],
                "favorited": t["favorited"],
            }
    return snap


def diff_snapshot(before, after):
    """Diff two snapshots to extract per-track feedback.

    Returns dict keyed by (artist, track_name) with feedback type and deltas.
    Tracks with no change are excluded.
    """
    diffs = {}
    for key, pre in before.items():
        post = after.get(key)
        if post is None:
            continue
        play_delta = post["played"] - pre["played"]
        skip_delta = post["skipped"] - pre["skipped"]
        newly_faved = post["favorited"] and not pre["favorited"]

        # Determine feedback type (favorite > skip > listen > excluded)
        if newly_faved:
            feedback = "favorite"
        elif skip_delta > 0:
            feedback = "skip"
        elif play_delta > 0:
            feedback = "listen"
        else:
            continue  # No change — exclude

        diffs[key] = {
            "feedback": feedback,
            "play_delta": play_delta,
            "skip_delta": skip_delta,
            "newly_faved": newly_faved,
        }
    return diffs


def aggregate_artist_feedback(diffs, all_offered_tracks=None):
    """Aggregate per-track diffs into per-artist feedback.

    Args:
        diffs: output of diff_snapshot (only tracks with changes)
        all_offered_tracks: list of all (artist, track) tuples offered (includes unplayed)

    Returns {artist: {"fave_tracks": int, "skip_tracks": int, "listen_tracks": int, "tracks_offered": int}}
    """
    # Count total tracks offered per artist (including unplayed)
    offered_counts = {}
    if all_offered_tracks:
        for artist, _track in all_offered_tracks:
            a = artist.lower()
            offered_counts[a] = offered_counts.get(a, 0) + 1
    artists = {}
    for (artist, _track), info in diffs.items():
        if artist not in artists:
            artists[artist] = {"fave_tracks": 0, "skip_tracks": 0, "listen_tracks": 0, "tracks_offered": 0}
        if info["feedback"] == "favorite":
            artists[artist]["fave_tracks"] += 1
        elif info["feedback"] == "skip":
            artists[artist]["skip_tracks"] += 1
        elif info["feedback"] == "listen":
            artists[artist]["listen_tracks"] += 1
    # Set tracks_offered from the full offered list (includes unplayed tracks)
    for artist in artists:
        artists[artist]["tracks_offered"] = offered_counts.get(artist, artists[artist]["fave_tracks"] + artists[artist]["skip_tracks"] + artists[artist]["listen_tracks"])
    return artists


def load_feedback_history(path):
    """Load feedback history from JSON, or return empty structure."""
    path = pathlib.Path(path)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, KeyError):
            pass
    return {"schema_version": 1, "rounds": []}


def save_feedback_history(path, history, round_data):
    """Append a round to history with idempotency guard.

    If round_data.round_id already exists, skip (no-op).
    Returns updated history.
    """
    existing_ids = {r["round_id"] for r in history["rounds"]}
    if round_data.round_id in existing_ids:
        log.warning(f"Round {round_data.round_id} already in history, skipping.")
        return history
    history["rounds"].append(asdict(round_data))
    pathlib.Path(path).write_text(json.dumps(history, indent=2))
    return history


def save_snapshot(path, snapshot):
    """Save snapshot to JSON. Keys are serialized as "artist|||track_name"."""
    serializable = {f"{a}|||{t}": v for (a, t), v in snapshot.items()}
    pathlib.Path(path).write_text(json.dumps(
        {"schema_version": 1, "tracks": serializable}, indent=2))


def load_snapshot(path):
    """Load snapshot from JSON. Returns dict with (artist, track_name) tuple keys."""
    path = pathlib.Path(path)
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    tracks = data.get("tracks", {})
    return {tuple(k.split("|||", 1)): v for k, v in tracks.items()}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_feedback.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add feedback.py tests/test_feedback.py
git commit -m "feat: add feedback module with snapshots, diff, and history"
```

---

### Task 5: Build affinity graph module

**Files:**
- Create: `affinity_graph.py`
- Create: `tests/test_affinity_graph.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_affinity_graph.py`:

```python
"""Tests for affinity_graph.py — graph construction, propagation, pruning."""
import math
import json
import pytest
from affinity_graph import AffinityGraph


def test_add_edges_musicmap():
    g = AffinityGraph()
    g.add_edges_musicmap({"opeth": {"katatonia": 0.8, "porcupine tree": 0.6}})
    assert g.get_musicmap_neighbors("opeth") == {"katatonia": 0.8, "porcupine tree": 0.6}


def test_add_edges_lastfm():
    g = AffinityGraph()
    g.add_edges_lastfm("opeth", [{"name": "Katatonia", "match": 0.85}])
    assert g.get_lastfm_neighbors("opeth") == {"katatonia": 0.85}


def test_inject_feedback_single_fave():
    g = AffinityGraph()
    g.add_edges_musicmap({"a": {"b": 0.8, "c": 0.5}})
    g.inject_feedback("a", fave_count=1, skip_count=0, listen_count=0, tracks_offered=2)
    assert g.get_raw_injection("a") == 1.0


def test_inject_feedback_multi_fave_sqrt():
    g = AffinityGraph()
    g.add_edges_musicmap({"a": {"b": 0.8}})
    g.inject_feedback("a", fave_count=9, skip_count=0, listen_count=0, tracks_offered=2)
    assert g.get_raw_injection("a") == pytest.approx(3.0)  # sqrt(9) = 3.0


def test_inject_feedback_skip_attenuated():
    """Skip injection is attenuated when fewer than 3 tracks offered."""
    g = AffinityGraph()
    g.add_edges_musicmap({"a": {"b": 0.8}})
    g.inject_feedback("a", fave_count=0, skip_count=1, listen_count=0, tracks_offered=1)
    # -0.7 * min(1, 3)/3 = -0.7 * 0.333 = -0.233
    assert g.get_raw_injection("a") == pytest.approx(-0.7 * 1 / 3, abs=0.01)


def test_inject_feedback_skip_full_strength_at_3_tracks():
    g = AffinityGraph()
    g.add_edges_musicmap({"a": {"b": 0.8}})
    g.inject_feedback("a", fave_count=0, skip_count=1, listen_count=0, tracks_offered=3)
    assert g.get_raw_injection("a") == pytest.approx(-0.7)


def test_inject_feedback_first_listen_neutral():
    """First listen-no-fave is 0.0 (neutral)."""
    g = AffinityGraph()
    g.add_edges_musicmap({"a": {"b": 0.8}})
    g.inject_feedback("a", fave_count=0, skip_count=0, listen_count=1, tracks_offered=2)
    assert g.get_raw_injection("a") == 0.0


def test_inject_feedback_second_listen_negative():
    """2+ listen-no-fave produces -0.1 per extra listen."""
    g = AffinityGraph()
    g.add_edges_musicmap({"a": {"b": 0.8}})
    g.inject_feedback("a", fave_count=0, skip_count=0, listen_count=3, tracks_offered=2)
    # (listen_count - 1) * -0.1 = 2 * -0.1 = -0.2
    assert g.get_raw_injection("a") == pytest.approx(-0.2)


def test_inject_feedback_mixed_net():
    """Mixed feedback uses net formula: sqrt(faves) - skips*0.7 - (listens-1)*0.1."""
    g = AffinityGraph()
    g.add_edges_musicmap({"a": {"b": 0.8}})
    g.inject_feedback("a", fave_count=2, skip_count=1, listen_count=0, tracks_offered=3)
    expected = math.sqrt(2) * 1.0 - 1 * 0.7
    assert g.get_raw_injection("a") == pytest.approx(expected, abs=0.01)


def test_propagate_single_hop():
    """Propagation decays by 0.4 per hop."""
    g = AffinityGraph()
    g.add_edges_musicmap({"a": {"b": 0.8}})
    g.inject_feedback("a", fave_count=1, skip_count=0, listen_count=0, tracks_offered=2)
    scores = g.propagate()
    # b gets: injection(a) * decay * edge_weight = 1.0 * 0.4 * 0.8 = 0.32
    assert scores["b"] == pytest.approx(0.32)


def test_propagate_two_hops():
    """Signal propagates through two hops with compound decay."""
    g = AffinityGraph()
    g.add_edges_musicmap({"a": {"b": 0.8}, "b": {"c": 0.6}})
    g.inject_feedback("a", fave_count=1, skip_count=0, listen_count=0, tracks_offered=2)
    scores = g.propagate()
    # c gets: 1.0 * 0.4 * 0.8 (a->b) * 0.4 * 0.6 (b->c) = 0.0768
    assert scores["c"] == pytest.approx(0.0768, abs=0.001)


def test_propagate_max_3_hops():
    """Propagation stops at 3 hops."""
    g = AffinityGraph()
    g.add_edges_musicmap({"a": {"b": 1.0}, "b": {"c": 1.0}, "c": {"d": 1.0}, "d": {"e": 1.0}})
    g.inject_feedback("a", fave_count=1, skip_count=0, listen_count=0, tracks_offered=2)
    scores = g.propagate()
    assert "d" in scores  # 3 hops
    assert scores.get("e", 0.0) == 0.0  # 4 hops — cut off


def test_propagate_dual_sources():
    """Music-map and Last.fm edges contribute separately, then sum."""
    g = AffinityGraph()
    g.add_edges_musicmap({"a": {"b": 0.8}})
    g.add_edges_lastfm("a", [{"name": "b", "match": 0.5}])
    g.inject_feedback("a", fave_count=1, skip_count=0, listen_count=0, tracks_offered=2)
    scores = g.propagate()
    # musicmap: 1.0 * 0.4 * 0.8 = 0.32
    # lastfm:   1.0 * 0.4 * 0.5 = 0.20
    # total: 0.52
    assert scores["b"] == pytest.approx(0.52, abs=0.01)


def test_recency_decay():
    """Old feedback is decayed by recency factor."""
    g = AffinityGraph()
    g.add_edges_musicmap({"a": {"b": 0.8}})
    g.inject_feedback("a", fave_count=1, skip_count=0, listen_count=0,
                       tracks_offered=2, days_ago=180, is_discovery=True)
    scores = g.propagate()
    # Discovery half-life = 90 days. At 180 days, factor = 0.25
    # b gets: 1.0 * 0.25 * 0.4 * 0.8 = 0.08
    assert scores["b"] == pytest.approx(0.08, abs=0.01)


def test_prune_removes_cold_nodes():
    """prune() removes nodes with no feedback and low affinity."""
    g = AffinityGraph()
    g.add_edges_musicmap({"a": {"b": 0.8, "c": 0.01}})
    g.inject_feedback("a", fave_count=1, skip_count=0, listen_count=0, tracks_offered=2)
    g.propagate()
    g.prune(threshold=0.05)
    assert "b" in g.nodes  # affinity 0.32, above threshold
    # c might be below threshold: 1.0 * 0.4 * 0.01 = 0.004


def test_save_load_roundtrip(tmp_path):
    """Graph survives save/load cycle."""
    g = AffinityGraph()
    g.add_edges_musicmap({"a": {"b": 0.8}})
    g.add_edges_lastfm("a", [{"name": "c", "match": 0.5}])
    path = tmp_path / "graph.json"
    g.save(path)
    g2 = AffinityGraph.load(path)
    assert g2.get_musicmap_neighbors("a") == {"b": 0.8}
    assert g2.get_lastfm_neighbors("a") == {"c": 0.5}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_affinity_graph.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write implementation**

Create `affinity_graph.py`:

```python
"""Affinity graph for adaptive music discovery.

Two edge types (music-map, Last.fm similar) with feedback injection,
hop-decayed propagation, recency weighting, and pruning.
"""
import json
import math
import logging
import pathlib
from collections import defaultdict

log = logging.getLogger(__name__)

HOP_DECAY = 0.4
MAX_HOPS = 3
SKIP_STRENGTH = 0.7
LISTEN_PENALTY = 0.1  # per occurrence after first
MAX_LISTEN_PENALTY = 0.5
LIBRARY_HALF_LIFE_DAYS = 180
DISCOVERY_HALF_LIFE_DAYS = 90


def _recency_factor(days_ago, is_discovery):
    """Exponential recency decay. Returns factor in (0, 1]."""
    if days_ago <= 0:
        return 1.0
    half_life = DISCOVERY_HALF_LIFE_DAYS if is_discovery else LIBRARY_HALF_LIFE_DAYS
    lam = math.log(2) / half_life
    return math.exp(-lam * days_ago)


class AffinityGraph:
    def __init__(self):
        self._musicmap = defaultdict(dict)   # {artist: {neighbor: weight}}
        self._lastfm = defaultdict(dict)     # {artist: {neighbor: weight}}
        self._injections = defaultdict(float) # {artist: raw_injection_strength}
        self._recency = {}                    # {artist: recency_factor}

    @property
    def nodes(self):
        """All nodes in the graph."""
        all_nodes = set(self._musicmap.keys()) | set(self._lastfm.keys())
        for neighbors in self._musicmap.values():
            all_nodes.update(neighbors.keys())
        for neighbors in self._lastfm.values():
            all_nodes.update(neighbors.keys())
        all_nodes.update(self._injections.keys())
        return all_nodes

    def add_edges_musicmap(self, cache):
        """Add music-map edges from scrape cache: {artist: {neighbor: proximity}}."""
        for artist, neighbors in cache.items():
            if isinstance(neighbors, dict):
                for neighbor, weight in neighbors.items():
                    self._musicmap[artist.lower()][neighbor.lower()] = weight

    def add_edges_lastfm(self, artist, similar_list):
        """Add Last.fm similar edges: [{"name": str, "match": float}]."""
        artist_lower = artist.lower()
        for s in similar_list:
            name = s.get("name", "").strip().lower()
            match = s.get("match", 0.0)
            if name and match > 0:
                self._lastfm[artist_lower][name] = match

    def get_musicmap_neighbors(self, artist):
        return dict(self._musicmap.get(artist.lower(), {}))

    def get_lastfm_neighbors(self, artist):
        return dict(self._lastfm.get(artist.lower(), {}))

    def get_raw_injection(self, artist):
        return self._injections.get(artist.lower(), 0.0)

    def inject_feedback(self, artist, *, fave_count, skip_count, listen_count,
                        tracks_offered, days_ago=0, is_discovery=True):
        """Inject feedback for an artist into the graph.

        Uses net injection formula:
          positive = sqrt(fave_count) if fave_count > 0 else 0
          negative_skip = skip_count * SKIP_STRENGTH * min(tracks_offered, 3) / 3
          negative_listen = max(0, listen_count - 1) * LISTEN_PENALTY  (capped)
          net = positive - negative_skip - negative_listen
        """
        artist_lower = artist.lower()
        positive = math.sqrt(fave_count) if fave_count > 0 else 0.0
        attenuation = min(tracks_offered, 3) / 3.0
        negative_skip = skip_count * SKIP_STRENGTH * attenuation
        negative_listen = min(max(0, listen_count - 1) * LISTEN_PENALTY, MAX_LISTEN_PENALTY)
        net = positive - negative_skip - negative_listen
        recency = _recency_factor(days_ago, is_discovery)
        self._injections[artist_lower] = self._injections.get(artist_lower, 0.0) + net * recency
        self._recency[artist_lower] = recency

    def propagate(self):
        """Propagate injections through the graph via BFS up to MAX_HOPS.

        Returns {artist: affinity_score} for all reachable nodes.
        Both edge types contribute independently and sum.
        """
        scores = defaultdict(float)
        # Start from all artists with non-zero injection
        seeds = {a: v for a, v in self._injections.items() if v != 0.0}

        for source, injection in seeds.items():
            # BFS from source, up to MAX_HOPS
            frontier = [(source, injection, 0)]  # (node, signal_at_node, hop_count)
            visited = {source}
            while frontier:
                next_frontier = []
                for node, signal, hops in frontier:
                    if hops >= MAX_HOPS:
                        continue
                    # Propagate through both edge types
                    for edge_dict in (self._musicmap, self._lastfm):
                        for neighbor, edge_weight in edge_dict.get(node, {}).items():
                            if neighbor in visited:
                                continue
                            propagated = signal * HOP_DECAY * edge_weight
                            if abs(propagated) > 0.001:
                                scores[neighbor] += propagated
                                visited.add(neighbor)
                                next_frontier.append((neighbor, propagated, hops + 1))
                frontier = next_frontier

        return dict(scores)

    def prune(self, threshold=0.01):
        """Remove nodes with no injections and affinity below threshold."""
        scores = self.propagate()
        keep = set(self._injections.keys())  # Always keep injected nodes
        for node, score in scores.items():
            if abs(score) >= threshold:
                keep.add(node)
        # Prune edge dicts
        for edge_dict in (self._musicmap, self._lastfm):
            to_remove = [k for k in edge_dict if k not in keep]
            for k in to_remove:
                del edge_dict[k]

    def save(self, path):
        """Save graph topology to JSON (injections are NOT saved — recomputed from feedback)."""
        data = {
            "schema_version": 1,
            "musicmap": dict(self._musicmap),
            "lastfm": dict(self._lastfm),
        }
        pathlib.Path(path).write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, path):
        """Load graph topology from JSON."""
        path = pathlib.Path(path)
        g = cls()
        if path.exists():
            data = json.loads(path.read_text())
            for artist, neighbors in data.get("musicmap", {}).items():
                g._musicmap[artist] = dict(neighbors)
            for artist, neighbors in data.get("lastfm", {}).items():
                g._lastfm[artist] = dict(neighbors)
        return g
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_affinity_graph.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add affinity_graph.py tests/test_affinity_graph.py
git commit -m "feat: add affinity graph with propagation, pruning, and recency decay"
```

---

### Task 6: Build weight learner module

**Files:**
- Create: `weight_learner.py`
- Create: `tests/test_weight_learner.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Add scikit-learn dependency**

Append `scikit-learn` to `requirements.txt`. Run: `pip install scikit-learn`

- [ ] **Step 2: Write failing tests**

Create `tests/test_weight_learner.py`:

```python
"""Tests for weight_learner.py — L2 logistic regression, normalization, features."""
import json
import numpy as np
import pytest
from weight_learner import WeightLearner, compute_candidate_features


def test_fit_produces_nonzero_weights():
    """Fitting on labeled data produces non-trivial weights."""
    learner = WeightLearner(signal_names=["sig_a", "sig_b"])
    # sig_a predicts favorites, sig_b is noise
    X = [{"sig_a": 5.0, "sig_b": 1.0},   # fave
         {"sig_a": 4.0, "sig_b": 2.0},   # fave
         {"sig_a": 0.5, "sig_b": 1.5},   # not
         {"sig_a": 0.2, "sig_b": 2.5},   # not
         {"sig_a": 6.0, "sig_b": 0.5},   # fave
         {"sig_a": 0.1, "sig_b": 3.0}]   # not
    y = [1, 1, 0, 0, 1, 0]
    learner.fit(X, y)
    # sig_a should have positive weight, higher than sig_b
    assert learner.weights["sig_a"] > learner.weights["sig_b"]


def test_fit_handles_class_imbalance():
    """Model handles 1:9 class imbalance without collapsing to predict all-negative."""
    learner = WeightLearner(signal_names=["sig_a"])
    X = [{"sig_a": 5.0}] * 3 + [{"sig_a": 0.5}] * 27  # 3 positives, 27 negatives
    y = [1] * 3 + [0] * 27
    learner.fit(X, y)
    # Should predict higher probability for sig_a=5.0 than sig_a=0.5
    p_high = learner.predict_proba({"sig_a": 5.0})
    p_low = learner.predict_proba({"sig_a": 0.5})
    assert p_high > p_low


def test_predict_proba_without_fit_returns_base_rate():
    """Before fitting, predict_proba returns 0.5 (no information)."""
    learner = WeightLearner(signal_names=["sig_a"])
    p = learner.predict_proba({"sig_a": 3.0})
    assert p == pytest.approx(0.5)


def test_normalization_uses_training_stats():
    """Features are normalized using mean/std from ALL training data."""
    learner = WeightLearner(signal_names=["sig_a"])
    X = [{"sig_a": v} for v in [0, 10, 20, 30, 0, 10, 20, 30]]
    y = [0, 0, 1, 1, 0, 0, 1, 1]
    learner.fit(X, y)
    assert learner.norm_mean["sig_a"] == pytest.approx(15.0)
    assert learner.norm_std["sig_a"] > 0


def test_save_load_roundtrip(tmp_path):
    """Learner survives save/load cycle."""
    learner = WeightLearner(signal_names=["sig_a", "sig_b"])
    X = [{"sig_a": 5.0, "sig_b": 1.0}, {"sig_a": 0.5, "sig_b": 2.0}]
    y = [1, 0]
    learner.fit(X, y)
    path = tmp_path / "weights.json"
    learner.save(path)
    loaded = WeightLearner.load(path)
    assert loaded.weights.keys() == learner.weights.keys()
    assert loaded.predict_proba({"sig_a": 5.0, "sig_b": 1.0}) == pytest.approx(
        learner.predict_proba({"sig_a": 5.0, "sig_b": 1.0}), abs=0.01)


def test_compute_candidate_features_proximity_weighted():
    """Candidate features are proximity-weighted sums from seed artists."""
    seed_signals = {
        "opeth": {"favorites": 50, "playcount": 1000},
        "tool": {"favorites": 30, "playcount": 500},
    }
    similarity = {"opeth": 0.8, "tool": 0.5}
    lastfm_similar_count = 2
    result = compute_candidate_features(
        candidate="katatonia",
        seed_signals=seed_signals,
        similarity=similarity,
        lastfm_similar_count=lastfm_similar_count,
        in_recs=False,
        in_heavy_rotation=False,
        lastfm_loved=False,
        ai_heuristic_score=0.9,
    )
    assert result["favorites"] == pytest.approx(50 * 0.8 + 30 * 0.5)  # 55.0
    assert result["playcount"] == pytest.approx(1000 * 0.8 + 500 * 0.5)  # 1050.0
    assert result["lastfm_similar"] == 2
    assert result["recommendations"] == 0
    assert result["ai_heuristic"] == 0.9
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_weight_learner.py -v`
Expected: FAIL — module not found

- [ ] **Step 4: Write implementation**

Create `weight_learner.py`:

```python
"""Weight learner for adaptive music discovery.

L2-regularized logistic regression fitted on accumulated feedback data.
Features are z-score normalized using training set statistics.
"""
import json
import logging
import pathlib
import numpy as np
from sklearn.linear_model import LogisticRegression

log = logging.getLogger(__name__)

# Signals that are proximity-weighted aggregates from seed artists
SEED_AGGREGATE_SIGNALS = ("favorites", "playcount", "playlists", "ratings")
# Signals that are direct per-candidate values
DIRECT_SIGNALS = ("heavy_rotation", "recommendations", "lastfm_similar",
                  "lastfm_loved", "ai_heuristic")
ALL_SIGNAL_NAMES = SEED_AGGREGATE_SIGNALS + DIRECT_SIGNALS


def compute_candidate_features(candidate, *, seed_signals, similarity,
                                lastfm_similar_count, in_recs, in_heavy_rotation,
                                lastfm_loved, ai_heuristic_score):
    """Compute the feature vector for a candidate artist.

    Args:
        candidate: candidate artist name (unused, for logging)
        seed_signals: {seed_artist: {signal: value}} for library artists
        similarity: {seed_artist: proximity} for seeds similar to this candidate
        lastfm_similar_count: int, how many favorites list this candidate as similar
        in_recs: bool, in Apple Music recommendations
        in_heavy_rotation: bool, in Apple Music heavy rotation
        lastfm_loved: bool, has loved tracks on Last.fm
        ai_heuristic_score: float 0-1, AI detection soft score (1 = likely human)

    Returns:
        dict of {signal_name: value}
    """
    features = {}
    # Proximity-weighted aggregates
    for sig in SEED_AGGREGATE_SIGNALS:
        total = 0.0
        for seed, prox in similarity.items():
            seed_val = seed_signals.get(seed, {}).get(sig, 0.0)
            total += seed_val * prox
        features[sig] = total

    # Direct signals
    features["heavy_rotation"] = 1.0 if in_heavy_rotation else 0.0
    features["recommendations"] = 1.0 if in_recs else 0.0
    features["lastfm_similar"] = float(lastfm_similar_count)
    features["lastfm_loved"] = 1.0 if lastfm_loved else 0.0
    features["ai_heuristic"] = ai_heuristic_score
    return features


class WeightLearner:
    def __init__(self, signal_names=None):
        self.signal_names = list(signal_names or ALL_SIGNAL_NAMES)
        self.weights = {s: 0.0 for s in self.signal_names}
        self.bias = 0.0
        self.norm_mean = {s: 0.0 for s in self.signal_names}
        self.norm_std = {s: 1.0 for s in self.signal_names}
        self._model = None
        self._fitted = False

    def fit(self, feature_dicts, labels):
        """Fit L2-regularized logistic regression on labeled data.

        Args:
            feature_dicts: list of {signal_name: value} dicts
            labels: list of 0/1 ints
        """
        n = len(feature_dicts)
        if n < 2 or sum(labels) == 0 or sum(labels) == n:
            log.warning(f"Cannot fit: {n} samples, {sum(labels)} positives")
            return

        # Build feature matrix
        X = np.zeros((n, len(self.signal_names)))
        for i, fd in enumerate(feature_dicts):
            for j, sig in enumerate(self.signal_names):
                X[i, j] = fd.get(sig, 0.0)
        y = np.array(labels)

        # Compute and store normalization stats from training data
        self.norm_mean = {sig: float(X[:, j].mean()) for j, sig in enumerate(self.signal_names)}
        self.norm_std = {sig: max(float(X[:, j].std()), 1e-8) for j, sig in enumerate(self.signal_names)}

        # Normalize
        X_norm = np.zeros_like(X)
        for j, sig in enumerate(self.signal_names):
            X_norm[:, j] = (X[:, j] - self.norm_mean[sig]) / self.norm_std[sig]

        # Fit
        self._model = LogisticRegression(
            penalty="l2", C=1.0, class_weight="balanced",
            solver="lbfgs", max_iter=1000, random_state=42,
        )
        self._model.fit(X_norm, y)
        self._fitted = True

        # Extract weights and bias
        for j, sig in enumerate(self.signal_names):
            self.weights[sig] = float(self._model.coef_[0, j])
        self.bias = float(self._model.intercept_[0])
        log.info(f"Model fitted: bias={self.bias:.3f}, weights={self.weights}")

    def predict_proba(self, feature_dict):
        """Predict P(favorite) for a single candidate. Returns float 0-1."""
        if not self._fitted:
            return 0.5
        x = np.zeros((1, len(self.signal_names)))
        for j, sig in enumerate(self.signal_names):
            raw = feature_dict.get(sig, 0.0)
            x[0, j] = (raw - self.norm_mean[sig]) / self.norm_std[sig]
        return float(self._model.predict_proba(x)[0, 1])

    def save(self, path):
        data = {
            "schema_version": 1,
            "signal_names": self.signal_names,
            "weights": self.weights,
            "bias": self.bias,
            "norm_mean": self.norm_mean,
            "norm_std": self.norm_std,
            "fitted": self._fitted,
        }
        pathlib.Path(path).write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, path):
        path = pathlib.Path(path)
        data = json.loads(path.read_text())
        learner = cls(signal_names=data["signal_names"])
        learner.weights = data["weights"]
        learner.bias = data["bias"]
        learner.norm_mean = data["norm_mean"]
        learner.norm_std = data["norm_std"]
        learner._fitted = data.get("fitted", False)
        if learner._fitted:
            # Reconstruct a model that produces the same predictions
            # by using the stored weights/bias directly
            learner._model = LogisticRegression(
                penalty="l2", C=1.0, solver="lbfgs", max_iter=1)
            n_features = len(learner.signal_names)
            # Fake a fit so sklearn internals are initialized
            X_dummy = np.zeros((2, n_features))
            X_dummy[0, 0] = 1.0
            learner._model.fit(X_dummy, [0, 1])
            # Overwrite with real weights
            learner._model.coef_ = np.array([[learner.weights[s] for s in learner.signal_names]])
            learner._model.intercept_ = np.array([learner.bias])
        return learner
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_weight_learner.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add weight_learner.py tests/test_weight_learner.py requirements.txt
git commit -m "feat: add weight learner with L2 logistic regression and normalization"
```

---

### Task 7: Build adaptive engine (scoring, overrides, cooldown, CLI)

**Files:**
- Create: `adaptive_engine.py`
- Create: `tests/test_adaptive_engine.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_adaptive_engine.py`:

```python
"""Tests for adaptive_engine.py — scoring, overrides, cooldown, explanation."""
import json
import pytest
from adaptive_engine import (
    compute_final_score, apply_overrides, check_cooldown,
    load_overrides, generate_explanation,
)


def test_final_score_combines_model_and_affinity():
    """Final score = alpha * model_score + (1-alpha) * affinity."""
    score = compute_final_score(model_score=0.8, affinity_score=0.4, alpha=0.5)
    assert score == pytest.approx(0.6)


def test_final_score_alpha_one_ignores_affinity():
    score = compute_final_score(model_score=0.8, affinity_score=0.4, alpha=1.0)
    assert score == pytest.approx(0.8)


def test_final_score_alpha_zero_ignores_model():
    score = compute_final_score(model_score=0.8, affinity_score=0.4, alpha=0.0)
    assert score == pytest.approx(0.4)


def test_override_pin_positive():
    """Positive pin overrides the computed score."""
    overrides = {"pins": {"opeth": 1.0}, "expunged_feedback": []}
    scores = {"opeth": 0.3, "tool": 0.5}
    result = apply_overrides(scores, overrides)
    assert result["opeth"] == 1.0
    assert result["tool"] == 0.5


def test_override_pin_negative():
    """Negative pin suppresses the score."""
    overrides = {"pins": {"opeth": -1.0}, "expunged_feedback": []}
    scores = {"opeth": 0.9}
    result = apply_overrides(scores, overrides)
    assert result["opeth"] == -1.0


def test_cooldown_blocks_recent_non_fave():
    """Non-favorited artist offered 1 round ago is in cooldown."""
    history_rounds = [
        {"round_id": "r1", "artist_feedback": {
            "opeth": {"fave_tracks": 0, "skip_tracks": 0, "listen_tracks": 1}
        }},
    ]
    assert check_cooldown("opeth", history_rounds, current_round=2, cooldown_rounds=3) is True


def test_cooldown_allows_favorited_artist():
    """Favorited artist is never in cooldown."""
    history_rounds = [
        {"round_id": "r1", "artist_feedback": {
            "opeth": {"fave_tracks": 1, "skip_tracks": 0, "listen_tracks": 0}
        }},
    ]
    assert check_cooldown("opeth", history_rounds, current_round=2, cooldown_rounds=3) is False


def test_cooldown_expires():
    """Non-favorited artist is allowed after cooldown_rounds have passed."""
    history_rounds = [
        {"round_id": "r1", "artist_feedback": {
            "opeth": {"fave_tracks": 0, "skip_tracks": 1, "listen_tracks": 0}
        }},
    ]
    assert check_cooldown("opeth", history_rounds, current_round=5, cooldown_rounds=3) is False


def test_load_overrides_missing_file(tmp_path):
    """Missing overrides file returns empty structure."""
    result = load_overrides(tmp_path / "nonexistent.json")
    assert result == {"pins": {}, "expunged_feedback": []}


def test_generate_explanation():
    """Explanation includes score, top signals, and affinity path."""
    explanation = generate_explanation(
        artist="katatonia",
        final_score=0.72,
        model_score=0.65,
        affinity_score=0.79,
        feature_dict={"favorites": 55.0, "playcount": 1050.0, "lastfm_similar": 3.0,
                      "ratings": 2.1, "recommendations": 0, "heavy_rotation": 0,
                      "lastfm_loved": 1, "ai_heuristic": 0.95, "playlists": 10.0},
        weights={"favorites": 0.8, "playcount": 0.3, "lastfm_similar": 0.6,
                 "ratings": 0.2, "recommendations": 0.1, "heavy_rotation": 0.05,
                 "lastfm_loved": 0.4, "ai_heuristic": 0.1, "playlists": 0.15},
        affinity_path="opeth -> katatonia (0.8)",
    )
    assert "katatonia" in explanation
    assert "0.72" in explanation
    assert "favorites" in explanation  # top signal
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_adaptive_engine.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write implementation**

Create `adaptive_engine.py`:

```python
#!/usr/bin/env python3
"""Adaptive music discovery engine.

CLI entry point and scoring orchestration. Combines a learned logistic model
with an affinity graph for two-channel recommendation scoring.

Usage:
    python adaptive_engine.py --seed        # one-time: build graph, train model, sanity check
    python adaptive_engine.py --build       # snapshot + score + build playlist
    python adaptive_engine.py --feedback    # collect feedback + update model
    python adaptive_engine.py --feedback --rescan <round_id>  # re-scan a prior round
"""
import argparse
import json
import logging
import pathlib
import sys

log = logging.getLogger(__name__)

DEFAULT_ALPHA = 0.5
DEFAULT_COOLDOWN_ROUNDS = 3
DEFAULT_PLAYLIST_ARTISTS = 50
DEFAULT_TRACKS_PER_ARTIST = 2


def compute_final_score(model_score, affinity_score, alpha=DEFAULT_ALPHA):
    """Two-channel combination: alpha * model + (1-alpha) * affinity."""
    return alpha * model_score + (1.0 - alpha) * affinity_score


def apply_overrides(scores, overrides):
    """Apply manual pin overrides to scores dict. Returns new dict."""
    result = dict(scores)
    for artist, pin_score in overrides.get("pins", {}).items():
        if artist in result:
            result[artist] = pin_score
    return result


def check_cooldown(artist, history_rounds, current_round, cooldown_rounds=DEFAULT_COOLDOWN_ROUNDS):
    """Check if an artist is in cooldown (offered recently, not favorited).

    Returns True if the artist should be skipped.
    """
    for i, rnd in enumerate(reversed(history_rounds)):
        round_num = len(history_rounds) - i
        rounds_ago = current_round - round_num
        if rounds_ago >= cooldown_rounds:
            break  # Past cooldown window
        feedback = rnd.get("artist_feedback", {}).get(artist, {})
        if feedback:
            if feedback.get("fave_tracks", 0) > 0:
                return False  # Favorited — no cooldown
            return True  # Offered but not favorited — in cooldown
    return False  # Not found in recent history


def load_overrides(path):
    """Load artist overrides (pins and expunges) from JSON."""
    path = pathlib.Path(path)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, KeyError):
            pass
    return {"pins": {}, "expunged_feedback": []}


def generate_explanation(artist, final_score, model_score, affinity_score,
                         feature_dict, weights, affinity_path=""):
    """Generate a human-readable explanation for why an artist was recommended.

    Returns a formatted string.
    """
    # Sort signals by abs(weight * feature_value) to find top contributors
    contributions = []
    for sig, weight in weights.items():
        val = feature_dict.get(sig, 0.0)
        contributions.append((sig, weight * val, val, weight))
    contributions.sort(key=lambda x: abs(x[1]), reverse=True)
    top3 = contributions[:3]

    lines = [f"  {artist} — score: {final_score:.2f} (model: {model_score:.2f}, affinity: {affinity_score:.2f})"]
    for sig, contrib, val, weight in top3:
        lines.append(f"    {sig}: value={val:.1f}, weight={weight:.2f}, contrib={contrib:.2f}")
    if affinity_path:
        lines.append(f"    graph path: {affinity_path}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Adaptive music discovery engine")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--seed", action="store_true",
                       help="One-time setup: build graph, train model, show sanity check")
    group.add_argument("--build", action="store_true",
                       help="Snapshot + score + build playlist")
    group.add_argument("--feedback", action="store_true",
                       help="Collect feedback + update model")
    parser.add_argument("--rescan", type=str, default=None,
                        help="Re-scan a prior round (used with --feedback)")
    parser.add_argument("--alpha", type=float, default=DEFAULT_ALPHA,
                        help=f"Model/affinity mixing parameter (default: {DEFAULT_ALPHA})")
    parser.add_argument("--playlist-size", type=int, default=DEFAULT_PLAYLIST_ARTISTS,
                        help=f"Number of artists per playlist (default: {DEFAULT_PLAYLIST_ARTISTS})")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cache_dir = pathlib.Path.home() / ".cache" / "music_discovery"
    cache_dir.mkdir(parents=True, exist_ok=True)

    if args.seed:
        _run_seed(cache_dir, args)
    elif args.build:
        _run_build(cache_dir, args)
    elif args.feedback:
        _run_feedback(cache_dir, args)


def _run_seed(cache_dir, args):
    """Seed mode: collect data, build graph, train initial model, show sanity check."""
    from music_discovery import (parse_library_jxa, load_cache, load_dotenv,
                                  fetch_filter_data, load_ai_blocklist, load_ai_allowlist,
                                  check_ai_artist)
    from signal_collectors import (collect_playcounts_jxa, collect_user_playlists_jxa,
                                    collect_ratings_jxa)
    from affinity_graph import AffinityGraph
    from weight_learner import WeightLearner, compute_candidate_features

    load_dotenv()
    import os
    api_key = os.environ.get("LASTFM_API_KEY", "")

    log.info("=== Seed Mode ===\n")

    # 1. Collect library signals
    log.info("Reading library favorites...")
    favorites = parse_library_jxa()
    log.info(f"  {len(favorites)} favorited artists.")

    log.info("Collecting play counts...")
    playcounts = collect_playcounts_jxa()
    log.info("Collecting playlist membership...")
    playlists = collect_user_playlists_jxa()
    log.info("Collecting ratings...")
    ratings = collect_ratings_jxa()

    seed_signals = {}
    for artist in favorites:
        seed_signals[artist] = {
            "favorites": favorites.get(artist, 0),
            "playcount": playcounts.get(artist, 0),
            "playlists": playlists.get(artist, 0),
            "ratings": ratings.get(artist, {}).get("avg_centered", 0.0),
        }

    # 2. Build similarity graph
    log.info("\nBuilding similarity graph...")
    paths = {"cache": cache_dir / "music_map_cache.json"}
    scrape_cache = load_cache(paths["cache"])
    graph = AffinityGraph()
    graph.add_edges_musicmap(scrape_cache)
    log.info(f"  Music-map: {len(scrape_cache)} seed artists loaded.")

    # Collect Last.fm similar for library artists (one-time cost)
    lastfm_similar_path = cache_dir / "lastfm_similar_cache.json"
    if lastfm_similar_path.exists():
        log.info("  Loading Last.fm similar from cache...")
        lfm_cache = json.loads(lastfm_similar_path.read_text())
    else:
        log.info("  Collecting Last.fm similar for library artists (one-time, ~18 min)...")
        lfm_cache = {}
        import time
        for i, artist in enumerate(favorites):
            if api_key:
                data = fetch_filter_data(artist, api_key)
                similar = data.get("similar_artists", [])
                lfm_cache[artist] = similar
                graph.add_edges_lastfm(artist, similar)
                if (i + 1) % 100 == 0:
                    log.info(f"    {i + 1}/{len(favorites)} artists...")
                time.sleep(1.0)
        lastfm_similar_path.write_text(json.dumps(lfm_cache, indent=2))
    for artist, similar in lfm_cache.items():
        graph.add_edges_lastfm(artist, similar)
    log.info(f"  Last.fm: {len(lfm_cache)} artists with similar data.")

    graph.save(cache_dir / "affinity_graph.json")

    # 3. Bootstrap model from wargaming data
    log.info("\nBootstrapping model from wargaming data...")
    manifest_path = cache_dir / "eval_manifest.json"
    history_path = cache_dir / "post_listen_history.json"

    training_X = []
    training_y = []

    if manifest_path.exists() and history_path.exists():
        manifest = json.loads(manifest_path.read_text())
        history = json.loads(history_path.read_text())
        all_faves = set()
        for rnd in history.get("rounds", []):
            all_faves.update(rnd.get("new_favorites", []))

        for session in manifest.get("sessions", []):
            for entry in session.get("artists", []):
                artist = entry["name"]
                if not entry.get("added", False):
                    continue
                # Compute similarity to this candidate from seed artists
                similarity = scrape_cache.get(artist, {})
                # For bootstrap, approximate features from current caches
                lfm_count = sum(1 for s_data in lfm_cache.values()
                                for s in s_data if s.get("name", "").lower() == artist)
                features = compute_candidate_features(
                    candidate=artist,
                    seed_signals=seed_signals,
                    similarity={s: p for s, p in similarity.items() if s in seed_signals} if not similarity else
                               {s: scrape_cache.get(s, {}).get(artist, 0.0) for s in seed_signals if scrape_cache.get(s, {}).get(artist, 0.0) > 0},
                    lastfm_similar_count=lfm_count,
                    in_recs=False,
                    in_heavy_rotation=False,
                    lastfm_loved=False,
                    ai_heuristic_score=1.0,  # Unknown for bootstrap
                )
                training_X.append(features)
                training_y.append(1 if artist in all_faves else 0)

    if training_X:
        learner = WeightLearner()
        learner.fit(training_X, training_y)
        learner.save(cache_dir / "adaptive_weights.json")
        log.info(f"  Trained on {len(training_X)} artists ({sum(training_y)} positives)")
        log.info(f"  Weights: {learner.weights}")
        log.info(f"  Bias: {learner.bias:.3f}")
    else:
        log.info("  No wargaming data found — starting with uninformed model.")
        learner = WeightLearner()
        learner.save(cache_dir / "adaptive_weights.json")

    # 4. Show sanity check
    log.info("\n=== Sanity Check: Top 50 Candidates ===\n")
    # Score all candidates from scrape cache
    library_set = set(favorites.keys())
    all_candidates = set()
    for similar in scrape_cache.values():
        if isinstance(similar, dict):
            all_candidates.update(similar.keys())
    candidates = all_candidates - library_set

    scored = []
    affinity_scores = graph.propagate() if graph._injections else {}
    for c in candidates:
        similarity = {s: scrape_cache.get(s, {}).get(c, 0.0) for s in seed_signals
                      if scrape_cache.get(s, {}).get(c, 0.0) > 0}
        lfm_count = sum(1 for s_data in lfm_cache.values()
                        for s in s_data if s.get("name", "").lower() == c)
        features = compute_candidate_features(
            candidate=c, seed_signals=seed_signals, similarity=similarity,
            lastfm_similar_count=lfm_count, in_recs=False, in_heavy_rotation=False,
            lastfm_loved=False, ai_heuristic_score=1.0,
        )
        model_score = learner.predict_proba(features)
        aff = affinity_scores.get(c, 0.0)
        # Normalize affinity to 0-1 range for combination
        final = compute_final_score(model_score, max(0, min(1, aff)), args.alpha)
        scored.append((final, model_score, aff, c, features))

    scored.sort(reverse=True)
    for final, ms, aff, name, feat in scored[:50]:
        log.info(f"  {final:.3f} | model={ms:.3f} aff={aff:.3f} | {name}")

    log.info(f"\nSeed complete. Review the top 50 above, then run --build.")


def _run_build(cache_dir, args):
    """Build mode: snapshot + score + build playlist."""
    log.info("=== Build Mode ===")
    log.info("(Full implementation in subsequent task)")
    # This will be wired up to:
    # 1. Collect current track metadata (snapshot)
    # 2. Score all candidates
    # 3. Apply overrides and cooldown
    # 4. Build playlist (top N artists, 2 tracks each)
    # 5. Save snapshot and explanation report


def _run_feedback(cache_dir, args):
    """Feedback mode: collect feedback + update model."""
    log.info("=== Feedback Mode ===")
    log.info("(Full implementation in subsequent task)")
    # This will be wired up to:
    # 1. Load pre-listen snapshot
    # 2. Collect current track metadata
    # 3. Diff snapshots
    # 4. Aggregate per-artist feedback
    # 5. Inject feedback into affinity graph
    # 6. Refit model on all accumulated data
    # 7. Save everything


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_adaptive_engine.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add adaptive_engine.py tests/test_adaptive_engine.py
git commit -m "feat: add adaptive engine with scoring, overrides, cooldown, and CLI skeleton"
```

---

### Task 8: Wire up --build mode (scoring + playlist building)

**Files:**
- Modify: `adaptive_engine.py` (`_run_build` function)
- Modify: `tests/test_adaptive_engine.py`

- [ ] **Step 1: Write failing test for build pipeline**

Add to `tests/test_adaptive_engine.py`:

```python
def test_build_scores_and_filters(tmp_path, monkeypatch):
    """Build mode scores candidates, applies cooldown, and respects blocklist."""
    from adaptive_engine import rank_candidates

    # Scores before filtering
    raw_scores = {"opeth": 0.9, "tool": 0.7, "blocked_artist": 0.8, "cooldown_artist": 0.6}
    blocklist = {"blocked_artist"}
    history_rounds = [
        {"round_id": "r1", "artist_feedback": {
            "cooldown_artist": {"fave_tracks": 0, "skip_tracks": 1, "listen_tracks": 0}
        }}
    ]
    overrides = {"pins": {}, "expunged_feedback": []}

    ranked = rank_candidates(
        raw_scores, blocklist=blocklist, overrides=overrides,
        history_rounds=history_rounds, current_round=2, cooldown_rounds=3,
    )
    names = [name for _, name in ranked]
    assert "blocked_artist" not in names
    assert "cooldown_artist" not in names
    assert names[0] == "opeth"
    assert names[1] == "tool"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_adaptive_engine.py::test_build_scores_and_filters -v`
Expected: FAIL — `rank_candidates` not defined

- [ ] **Step 3: Implement rank_candidates and wire up _run_build**

Add to `adaptive_engine.py`:

```python
def rank_candidates(scores, *, blocklist=None, overrides=None,
                     history_rounds=None, current_round=1, cooldown_rounds=DEFAULT_COOLDOWN_ROUNDS):
    """Rank candidates after applying blocklist, overrides, and cooldown.

    Returns [(score, artist_name)] sorted descending.
    """
    if blocklist is None:
        blocklist = set()
    if overrides is None:
        overrides = {"pins": {}, "expunged_feedback": []}
    if history_rounds is None:
        history_rounds = []

    scores = apply_overrides(scores, overrides)
    ranked = []
    for artist, score in scores.items():
        if artist in blocklist:
            continue
        if check_cooldown(artist, history_rounds, current_round, cooldown_rounds):
            continue
        ranked.append((score, artist))
    ranked.sort(reverse=True)
    return ranked
```

Then flesh out `_run_build`:

```python
def _run_build(cache_dir, args):
    """Build mode: snapshot + score + build playlist."""
    from music_discovery import (parse_library_jxa, load_cache, load_dotenv,
                                  fetch_filter_data, fetch_top_tracks,
                                  add_track_to_playlist, load_ai_blocklist,
                                  load_ai_allowlist, check_ai_artist,
                                  collect_track_metadata_jxa, _applescript_escape)
    from signal_collectors import (collect_playcounts_jxa, collect_user_playlists_jxa,
                                    collect_ratings_jxa, collect_heavy_rotation,
                                    collect_recommendations, _make_user_session,
                                    collect_lastfm_loved)
    from affinity_graph import AffinityGraph
    from weight_learner import WeightLearner, compute_candidate_features
    from feedback import create_snapshot, save_snapshot, load_feedback_history
    import os, time

    load_dotenv()
    api_key = os.environ.get("LASTFM_API_KEY", "")
    lastfm_username = os.environ.get("LASTFM_USERNAME")

    log.info("=== Build Mode ===\n")

    # Load model and graph
    learner = WeightLearner.load(cache_dir / "adaptive_weights.json")
    graph = AffinityGraph.load(cache_dir / "affinity_graph.json")

    # Collect signals
    log.info("Collecting signals...")
    favorites = parse_library_jxa()
    playcounts = collect_playcounts_jxa()
    playlists_signal = collect_user_playlists_jxa()
    ratings = collect_ratings_jxa()

    seed_signals = {}
    for artist in favorites:
        seed_signals[artist] = {
            "favorites": favorites.get(artist, 0),
            "playcount": playcounts.get(artist, 0),
            "playlists": playlists_signal.get(artist, 0),
            "ratings": ratings.get(artist, {}).get("avg_centered", 0.0),
        }

    # Load caches
    scrape_cache = load_cache(cache_dir / "music_map_cache.json")
    lfm_cache = {}
    lfm_path = cache_dir / "lastfm_similar_cache.json"
    if lfm_path.exists():
        lfm_cache = json.loads(lfm_path.read_text())

    # Optional API signals
    recs = set()
    heavy_rot = set()
    try:
        from compare_similarity import generate_apple_music_token
        token = generate_apple_music_token()
        user_token = os.environ.get("APPLE_MUSIC_USER_TOKEN", "")
        if token and user_token:
            session = _make_user_session(token, user_token)
            recs = collect_recommendations(session)
            heavy_rot = collect_heavy_rotation(session)
    except Exception:
        pass

    loved = set()
    if lastfm_username and api_key:
        loved_cache_path = cache_dir / "lastfm_loved_cache.json"
        if loved_cache_path.exists():
            loved = set(json.loads(loved_cache_path.read_text()))
        else:
            loved = collect_lastfm_loved(lastfm_username, api_key)
            loved_cache_path.write_text(json.dumps(sorted(loved), indent=2))

    # Load blocklists, overrides, history
    project_dir = pathlib.Path(__file__).parent
    blocklist = set()
    bl_path = project_dir / "ai_blocklist.txt"
    if bl_path.exists():
        from music_discovery import load_ai_blocklist
        blocklist = load_ai_blocklist(bl_path)

    overrides = load_overrides(cache_dir / "artist_overrides.json")
    history = load_feedback_history(cache_dir / "feedback_history.json")

    # Inject library favorites into graph for affinity propagation
    import datetime
    for artist, count in favorites.items():
        graph.inject_feedback(artist, fave_count=count, skip_count=0,
                               listen_count=0, tracks_offered=3,
                               days_ago=90, is_discovery=False)  # Approximate

    # Replay feedback history into graph
    for i, rnd in enumerate(history.get("rounds", [])):
        for artist, fb in rnd.get("artist_feedback", {}).items():
            graph.inject_feedback(
                artist,
                fave_count=fb.get("fave_tracks", 0),
                skip_count=fb.get("skip_tracks", 0),
                listen_count=fb.get("listen_tracks", 0),
                tracks_offered=fb.get("tracks_offered", 2),
                days_ago=(len(history["rounds"]) - i) * 7,  # Approximate
                is_discovery=True,
            )

    affinity_scores = graph.propagate()

    # Normalize affinity scores to 0-1 for combination
    aff_values = [v for v in affinity_scores.values() if v > 0]
    aff_max = max(aff_values) if aff_values else 1.0

    # Score all candidates
    log.info("Scoring candidates...")
    library_set = set(favorites.keys())
    all_candidates = set()
    for similar in scrape_cache.values():
        if isinstance(similar, dict):
            all_candidates.update(similar.keys())
    for similar_list in lfm_cache.values():
        for s in similar_list:
            all_candidates.add(s.get("name", "").lower())
    candidates = all_candidates - library_set

    raw_scores = {}
    explanations = []
    for c in candidates:
        similarity = {s: scrape_cache.get(s, {}).get(c, 0.0) for s in seed_signals
                      if scrape_cache.get(s, {}).get(c, 0.0) > 0}
        lfm_count = sum(1 for s_data in lfm_cache.values()
                        for s in s_data if s.get("name", "").lower() == c)
        ai_score = 1.0  # Default to human; check_ai_artist if filter data available
        features = compute_candidate_features(
            candidate=c, seed_signals=seed_signals, similarity=similarity,
            lastfm_similar_count=lfm_count,
            in_recs=(c in recs), in_heavy_rotation=(c in heavy_rot),
            lastfm_loved=(c in loved), ai_heuristic_score=ai_score,
        )
        model_score = learner.predict_proba(features)
        aff = affinity_scores.get(c, 0.0) / aff_max if aff_max > 0 else 0.0
        aff = max(0.0, min(1.0, aff))
        final = compute_final_score(model_score, aff, args.alpha)
        raw_scores[c] = final

    # Rank and filter
    ranked = rank_candidates(
        raw_scores, blocklist=blocklist, overrides=overrides,
        history_rounds=history.get("rounds", []),
        current_round=len(history.get("rounds", [])) + 1,
    )

    # Build playlist
    playlist_name = "_Adaptive Discovery"
    playlist_artists = ranked[:args.playlist_size]
    log.info(f"\nBuilding playlist '{playlist_name}' with {len(playlist_artists)} artists...")

    offered_tracks = []
    added_count = 0
    for score, artist in playlist_artists:
        tracks = fetch_top_tracks(artist, api_key) if api_key else []
        artist_added = 0
        for track in tracks[:DEFAULT_TRACKS_PER_ARTIST]:
            if add_track_to_playlist(artist, track["name"]):
                offered_tracks.append((artist, track["name"]))
                artist_added += 1
                added_count += 1
            if artist_added >= DEFAULT_TRACKS_PER_ARTIST:
                break
        time.sleep(1.0)

    log.info(f"  {added_count} tracks added from {len(playlist_artists)} artists.")

    # Save raw features for each offered artist (needed for model retraining)
    offered_features = {}
    for score, artist in playlist_artists:
        similarity = {s: scrape_cache.get(s, {}).get(artist, 0.0) for s in seed_signals
                      if scrape_cache.get(s, {}).get(artist, 0.0) > 0}
        lfm_count = sum(1 for s_data in lfm_cache.values()
                        for s in s_data if s.get("name", "").lower() == artist)
        offered_features[artist] = compute_candidate_features(
            candidate=artist, seed_signals=seed_signals, similarity=similarity,
            lastfm_similar_count=lfm_count,
            in_recs=(artist in recs), in_heavy_rotation=(artist in heavy_rot),
            lastfm_loved=(artist in loved), ai_heuristic_score=1.0,
        )
    (cache_dir / "offered_features.json").write_text(json.dumps(offered_features, indent=2))

    # Save snapshot for feedback collection
    log.info("Saving pre-listen snapshot...")
    track_metadata = collect_track_metadata_jxa()
    snapshot = create_snapshot(track_metadata, offered_tracks)
    save_snapshot(cache_dir / "pre_listen_snapshot.json", snapshot)

    # Save explanation report
    log.info(f"Explanation report: {cache_dir / 'playlist_explanation.txt'}")
    # (Simplified — full explanation generation would use stored features)
    with open(cache_dir / "playlist_explanation.txt", "w") as f:
        f.write(f"Adaptive Discovery Playlist — {len(playlist_artists)} artists\n\n")
        for score, artist in playlist_artists[:50]:
            f.write(f"  {score:.3f} | {artist}\n")

    log.info("\nPlaylist built. Listen, then run --feedback.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_adaptive_engine.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add adaptive_engine.py tests/test_adaptive_engine.py
git commit -m "feat: wire up --build mode with scoring, filtering, and playlist building"
```

---

### Task 9: Wire up --feedback mode

**Files:**
- Modify: `adaptive_engine.py` (`_run_feedback` function)
- Modify: `tests/test_adaptive_engine.py`

- [ ] **Step 1: Write failing test for feedback pipeline**

Add to `tests/test_adaptive_engine.py`:

```python
def test_feedback_pipeline(tmp_path, monkeypatch):
    """Feedback mode collects diffs, updates graph and model, saves history."""
    from adaptive_engine import _collect_feedback_round
    from feedback import FeedbackRound

    before = {
        ("opeth", "ghost"): {"played": 10, "skipped": 1, "favorited": False},
        ("tool", "sober"): {"played": 5, "skipped": 0, "favorited": False},
        ("korn", "blind"): {"played": 0, "skipped": 0, "favorited": False},
    }
    after = {
        ("opeth", "ghost"): {"played": 12, "skipped": 1, "favorited": True},
        ("tool", "sober"): {"played": 5, "skipped": 2, "favorited": False},
        ("korn", "blind"): {"played": 0, "skipped": 0, "favorited": False},
    }

    round_data = _collect_feedback_round("2026-04-02", before, after, raw_features={})
    assert isinstance(round_data, FeedbackRound)
    assert round_data.artist_feedback["opeth"]["fave_tracks"] == 1
    assert round_data.artist_feedback["tool"]["skip_tracks"] == 2
    assert "korn" not in round_data.artist_feedback  # Not played
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_adaptive_engine.py::test_feedback_pipeline -v`
Expected: FAIL — `_collect_feedback_round` not defined

- [ ] **Step 3: Implement _collect_feedback_round and wire up _run_feedback**

Add to `adaptive_engine.py`:

```python
def _collect_feedback_round(round_id, before_snapshot, after_snapshot, raw_features):
    """Process snapshot diffs into a FeedbackRound.

    Returns FeedbackRound with per-artist aggregated feedback.
    """
    from feedback import diff_snapshot, aggregate_artist_feedback, FeedbackRound

    diffs = diff_snapshot(before_snapshot, after_snapshot)
    artist_feedback = aggregate_artist_feedback(diffs)
    return FeedbackRound(
        round_id=round_id,
        artist_feedback=artist_feedback,
        raw_features=raw_features,
    )
```

Then flesh out `_run_feedback`:

```python
def _run_feedback(cache_dir, args):
    """Feedback mode: collect feedback, update graph and model."""
    from music_discovery import parse_library_jxa, collect_track_metadata_jxa, load_dotenv
    from affinity_graph import AffinityGraph
    from weight_learner import WeightLearner
    from feedback import (load_snapshot, load_feedback_history,
                          save_feedback_history)
    import datetime

    load_dotenv()
    log.info("=== Feedback Mode ===\n")

    round_id = args.rescan or datetime.date.today().isoformat()

    # Load snapshots
    snapshot_path = cache_dir / "pre_listen_snapshot.json"
    before = load_snapshot(snapshot_path)
    if not before:
        log.error("No pre-listen snapshot found. Run --build first.")
        sys.exit(1)

    # Collect current state
    log.info("Reading current library state...")
    track_metadata = collect_track_metadata_jxa()
    offered_keys = list(before.keys())
    from feedback import create_snapshot
    after = create_snapshot(track_metadata, offered_keys)

    # Load raw features saved during --build
    features_path = cache_dir / "offered_features.json"
    raw_features = json.loads(features_path.read_text()) if features_path.exists() else {}

    # Collect feedback
    round_data = _collect_feedback_round(round_id, before, after, raw_features=raw_features)
    fave_count = sum(1 for fb in round_data.artist_feedback.values() if fb["fave_tracks"] > 0)
    skip_count = sum(1 for fb in round_data.artist_feedback.values() if fb["skip_tracks"] > 0)
    listen_count = sum(1 for fb in round_data.artist_feedback.values()
                       if fb["listen_tracks"] > 0 and fb["fave_tracks"] == 0)

    log.info(f"Round {round_id}: {fave_count} favorites, {skip_count} skips, {listen_count} listens")
    for artist, fb in sorted(round_data.artist_feedback.items()):
        status = "FAV" if fb["fave_tracks"] > 0 else "SKIP" if fb["skip_tracks"] > 0 else "listen"
        log.info(f"  {status}: {artist}")

    # Save to history (idempotent)
    history_path = cache_dir / "feedback_history.json"
    history = load_feedback_history(history_path)
    history = save_feedback_history(history_path, history, round_data)

    # Update affinity graph
    log.info("\nUpdating affinity graph...")
    graph = AffinityGraph.load(cache_dir / "affinity_graph.json")
    for artist, fb in round_data.artist_feedback.items():
        graph.inject_feedback(
            artist,
            fave_count=fb["fave_tracks"],
            skip_count=fb["skip_tracks"],
            listen_count=fb["listen_tracks"],
            tracks_offered=fb.get("tracks_offered", 2),
            days_ago=0,
            is_discovery=True,
        )
    graph.prune()
    graph.save(cache_dir / "affinity_graph.json")

    # Refit model on all accumulated data
    log.info("Refitting model on all feedback data...")
    learner = WeightLearner.load(cache_dir / "adaptive_weights.json")
    all_X = []
    all_y = []
    for rnd in history.get("rounds", []):
        for artist, fb in rnd.get("artist_feedback", {}).items():
            features = rnd.get("raw_features", {}).get(artist, {})
            if features:
                all_X.append(features)
                all_y.append(1 if fb.get("fave_tracks", 0) > 0 else 0)

    if all_X:
        learner.fit(all_X, all_y)
        learner.save(cache_dir / "adaptive_weights.json")
        log.info(f"  Refitted on {len(all_X)} artists ({sum(all_y)} positives)")
        log.info(f"  Updated weights: {learner.weights}")

    # Replace snapshot with current state
    from feedback import save_snapshot
    save_snapshot(snapshot_path, after)

    log.info(f"\nFeedback collected. Run --build for next playlist.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_adaptive_engine.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add adaptive_engine.py tests/test_adaptive_engine.py
git commit -m "feat: wire up --feedback mode with graph update and model refit"
```

---

### Task 10: Integration test — multi-round simulation

**Files:**
- Create: `tests/test_integration_adaptive.py`

- [ ] **Step 1: Write integration test**

```python
"""Integration test: simulate 3 rounds of adaptive discovery with synthetic data."""
import json
import math
import pytest
from affinity_graph import AffinityGraph
from weight_learner import WeightLearner, compute_candidate_features
from feedback import FeedbackRound, load_feedback_history, save_feedback_history
from adaptive_engine import compute_final_score, rank_candidates, _collect_feedback_round


def test_multi_round_learning(tmp_path):
    """Simulate 3 rounds. Verify model adapts: metal favorites boost metal candidates."""

    # Setup: 5 "metal" seeds, 5 "pop" seeds, 10 candidates (5 metal, 5 pop)
    seed_signals = {}
    for i in range(5):
        seed_signals[f"metal_seed_{i}"] = {"favorites": 10, "playcount": 500, "playlists": 3, "ratings": 0.5}
        seed_signals[f"pop_seed_{i}"] = {"favorites": 5, "playcount": 200, "playlists": 1, "ratings": 0.0}

    # Graph: metal seeds -> metal candidates, pop seeds -> pop candidates
    graph = AffinityGraph()
    mm_cache = {}
    for i in range(5):
        mm_cache[f"metal_seed_{i}"] = {f"metal_cand_{j}": 0.8 for j in range(5)}
        mm_cache[f"pop_seed_{i}"] = {f"pop_cand_{j}": 0.8 for j in range(5)}
    graph.add_edges_musicmap(mm_cache)

    # Round 1: offer all 10, user favorites 2 metal candidates
    history_path = tmp_path / "history.json"
    before = {
        (f"metal_cand_{i}", "track1"): {"played": 0, "skipped": 0, "favorited": False}
        for i in range(5)
    }
    before.update({
        (f"pop_cand_{i}", "track1"): {"played": 0, "skipped": 0, "favorited": False}
        for i in range(5)
    })
    after = dict(before)
    # User favorites metal_cand_0 and metal_cand_1
    after[("metal_cand_0", "track1")] = {"played": 3, "skipped": 0, "favorited": True}
    after[("metal_cand_1", "track1")] = {"played": 2, "skipped": 0, "favorited": True}
    # User skips pop_cand_0
    after[("pop_cand_0", "track1")] = {"played": 1, "skipped": 1, "favorited": False}
    # User listens to pop_cand_1, no fave
    after[("pop_cand_1", "track1")] = {"played": 1, "skipped": 0, "favorited": False}

    round1 = _collect_feedback_round("round1", before, after, raw_features={})
    history = load_feedback_history(history_path)
    history = save_feedback_history(history_path, history, round1)

    # Inject feedback into graph
    for artist, fb in round1.artist_feedback.items():
        graph.inject_feedback(artist, fave_count=fb["fave_tracks"],
                               skip_count=fb["skip_tracks"],
                               listen_count=fb["listen_tracks"],
                               tracks_offered=1, days_ago=0, is_discovery=True)

    # Propagate
    scores = graph.propagate()

    # Metal candidates that are neighbors of favorited metal_cand_0/1 should be boosted
    # Pop candidates near skipped pop_cand_0 should be penalized
    metal_affinities = [scores.get(f"metal_cand_{i}", 0.0) for i in range(2, 5)]
    pop_affinities = [scores.get(f"pop_cand_{i}", 0.0) for i in range(2, 5)]

    # Metal neighborhood should have higher average affinity than pop
    assert sum(metal_affinities) > sum(pop_affinities), \
        f"Metal affinities {metal_affinities} should exceed pop {pop_affinities}"

    # Verify idempotency
    history2 = save_feedback_history(history_path, history, round1)
    assert len(history2["rounds"]) == 1  # Not duplicated


def test_cooldown_integration(tmp_path):
    """Artist skipped in round 1 is blocked for 3 rounds, then allowed."""
    history_path = tmp_path / "history.json"
    history = load_feedback_history(history_path)

    for i in range(4):
        rnd = FeedbackRound(
            round_id=f"round{i+1}",
            artist_feedback={"skipped_artist": {"fave_tracks": 0, "skip_tracks": 1, "listen_tracks": 0}}
            if i == 0 else {},
            raw_features={},
        )
        history = save_feedback_history(history_path, history, rnd)

    scores = {"skipped_artist": 0.9, "other": 0.5}

    # Round 2: should be blocked
    ranked = rank_candidates(scores, history_rounds=history["rounds"],
                              current_round=2, cooldown_rounds=3)
    assert "skipped_artist" not in [n for _, n in ranked]

    # Round 5: cooldown expired
    ranked = rank_candidates(scores, history_rounds=history["rounds"],
                              current_round=5, cooldown_rounds=3)
    assert "skipped_artist" in [n for _, n in ranked]
```

- [ ] **Step 2: Run integration tests**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/test_integration_adaptive.py -v`
Expected: All PASS

- [ ] **Step 3: Run full test suite**

Run: `cd "/Users/brianhill/Scripts/Music Discovery" && python3 -m pytest tests/ -v --tb=short`
Expected: All pass, no regressions

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration_adaptive.py
git commit -m "test: add multi-round integration tests for adaptive engine"
```

---

## Post-Implementation Notes

**After all tasks are complete:**

1. Run `--seed` to verify it works against real library data
2. Review the top 50 sanity check output with the user
3. If the user approves, run `--build` for the first adaptive playlist
4. The `--feedback` pipeline should be tested after a real listening round

**What's NOT in this plan (intentionally):**
- Full explanation output with graph paths (the framework is there, can be enriched iteratively)
- `--rescan` for prior rounds (the CLI flag exists, the logic is straightforward once the core works)
- Per-round raw feature storage in feedback history (the field exists, wiring it up requires passing features through the build pipeline — straightforward but verbose)

These are polish items that build on the working core without changing any interfaces.

**Deferred (acceptable for v1, not blocking):**
- Cooldown early breakout via strong affinity score
- Cooldown 30-day time limit (currently only counts rounds)
- Schema version checking on load (version field is written, check is deferred)
- `collect_lastfm_similar()` extracted as reusable function in signal_collectors.py
- `--rescan` logic beyond using the round_id string
