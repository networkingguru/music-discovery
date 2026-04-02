"""Tests for adaptive_engine.py pure functions."""

import json
import pathlib
import sys
import tempfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from adaptive_engine import (
    DEFAULT_ALPHA,
    DEFAULT_COOLDOWN_ROUNDS,
    _collect_feedback_round,
    _normalize_affinity,
    apply_overrides,
    check_cooldown,
    compute_final_score,
    generate_explanation,
    load_overrides,
    rank_candidates,
)


# ── compute_final_score ──────────────────────────────────────────────────────


class TestComputeFinalScore:
    def test_combines_model_and_affinity(self):
        """alpha=0.5: equal blend of model and affinity."""
        # model_score=0.8, affinity_mm=0.6, affinity_lfm=0.0
        # affinity = 1.0*0.6 + 1.0*0.0 = 0.6, clamped to 0.6
        # mapped to [0,1]: (0.6+1)/2 = 0.8
        # final = 0.5*0.8 + 0.5*0.8 = 0.8
        result = compute_final_score(0.8, 0.6, 0.0, alpha=0.5)
        assert result == pytest.approx(0.8, abs=1e-6)

    def test_alpha_one_ignores_affinity(self):
        """alpha=1.0: only model score matters."""
        result = compute_final_score(0.7, 1.0, 1.0, alpha=1.0)
        assert result == pytest.approx(0.7, abs=1e-6)

    def test_alpha_zero_ignores_model(self):
        """alpha=0.0: only affinity matters."""
        # affinity_mm=0.5, affinity_lfm=0.3 → combined=0.8, mapped=(0.8+1)/2=0.9
        result = compute_final_score(0.9, 0.5, 0.3, alpha=0.0)
        assert result == pytest.approx(0.9, abs=1e-6)

    def test_negative_affinity_reduces_score(self):
        """Negative affinity should produce a lower score than neutral."""
        score_neutral = compute_final_score(0.5, 0.0, 0.0, alpha=0.5)
        score_negative = compute_final_score(0.5, -0.5, -0.3, alpha=0.5)
        assert score_negative < score_neutral

    def test_affinity_clamped(self):
        """Affinity beyond [-1, 1] is clamped."""
        # w_mm=1.0, w_lfm=1.0, mm=1.0, lfm=1.0 → combined=2.0, clamped to 1.0
        result = compute_final_score(0.5, 1.0, 1.0, alpha=0.5)
        # mapped affinity: (1.0+1)/2 = 1.0
        # final = 0.5*0.5 + 0.5*1.0 = 0.75
        assert result == pytest.approx(0.75, abs=1e-6)


# ── apply_overrides ──────────────────────────────────────────────────────────


class TestApplyOverrides:
    def test_pin_positive(self):
        """Positive pin overrides score to the pinned value."""
        scores = {"artist_a": 0.3, "artist_b": 0.5}
        overrides = {"pins": {"artist_a": 1.0}}
        result = apply_overrides(scores, overrides)
        assert result["artist_a"] == 1.0
        assert result["artist_b"] == 0.5  # unchanged

    def test_pin_negative(self):
        """Negative pin suppresses artist to 0.0."""
        scores = {"artist_a": 0.9, "artist_b": 0.5}
        overrides = {"pins": {"artist_a": -1.0}}
        result = apply_overrides(scores, overrides)
        assert result["artist_a"] == 0.0
        assert result["artist_b"] == 0.5

    def test_no_overrides(self):
        """Empty overrides leave scores unchanged."""
        scores = {"artist_a": 0.5}
        result = apply_overrides(scores, {"pins": {}})
        assert result == scores

    def test_original_not_mutated(self):
        """apply_overrides returns a new dict, not mutating input."""
        scores = {"artist_a": 0.3}
        overrides = {"pins": {"artist_a": 1.0}}
        result = apply_overrides(scores, overrides)
        assert scores["artist_a"] == 0.3  # original unchanged
        assert result["artist_a"] == 1.0


# ── check_cooldown ───────────────────────────────────────────────────────────


class TestCheckCooldown:
    def _make_round(self, round_id, artist, fave_tracks=0):
        return {
            "round_id": str(round_id),
            "artist_feedback": {
                artist: {"fave_tracks": fave_tracks, "skip_tracks": 0,
                         "listen_tracks": 0, "tracks_offered": 2}
            },
        }

    def test_blocks_recent_non_fave(self):
        """Artist offered in recent round without fave → cooled down."""
        history = [self._make_round(3, "artist_a", fave_tracks=0)]
        assert check_cooldown("artist_a", history, current_round=4) is True

    def test_allows_favorited_artist(self):
        """Artist that was favorited → NOT cooled down."""
        history = [self._make_round(3, "artist_a", fave_tracks=2)]
        assert check_cooldown("artist_a", history, current_round=4) is False

    def test_cooldown_expires(self):
        """After cooldown_rounds, artist is no longer blocked."""
        history = [self._make_round(1, "artist_a", fave_tracks=0)]
        # current_round=5, cooldown=3 → round 1 is 4 rounds ago, beyond cooldown
        assert check_cooldown("artist_a", history, current_round=5, cooldown_rounds=3) is False

    def test_unknown_artist_not_cooled(self):
        """Artist not in any history round → not cooled down."""
        history = [self._make_round(3, "other_artist", fave_tracks=0)]
        assert check_cooldown("artist_a", history, current_round=4) is False

    def test_empty_history(self):
        """No history → nothing to cool down."""
        assert check_cooldown("artist_a", [], current_round=1) is False


# ── load_overrides ───────────────────────────────────────────────────────────


class TestLoadOverrides:
    def test_missing_file(self):
        """Missing file returns empty defaults."""
        result = load_overrides("/nonexistent/path/overrides.json")
        assert result == {"pins": {}, "expunged_feedback": []}

    def test_valid_file(self):
        """Valid JSON file loads correctly."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"pins": {"artist_a": 1.0}, "expunged_feedback": ["r1"]}, f)
            f.flush()
            result = load_overrides(f.name)
        assert result["pins"] == {"artist_a": 1.0}
        assert result["expunged_feedback"] == ["r1"]
        pathlib.Path(f.name).unlink()

    def test_corrupt_file(self):
        """Corrupt JSON returns empty defaults."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{not valid json")
            f.flush()
            result = load_overrides(f.name)
        assert result == {"pins": {}, "expunged_feedback": []}
        pathlib.Path(f.name).unlink()


# ── generate_explanation ─────────────────────────────────────────────────────


class TestGenerateExplanation:
    def test_contains_required_info(self):
        """Explanation includes score, model score, artist name, and top signals."""
        features = {"favorites": 3.0, "playcount": 100.0, "playlists": 2.0,
                     "ratings": 0.5, "heavy_rotation": 0.0}
        weights = [0.5, 0.3, 0.2, 0.1, -0.05]
        text = generate_explanation(
            artist="Test Band",
            final_score=0.85,
            model_score=0.75,
            affinity_mm=0.3,
            affinity_lfm=0.1,
            feature_dict=features,
            weights=weights,
        )
        assert "Test Band" in text
        assert "0.85" in text
        assert "0.75" in text
        assert "favorites" in text
        assert "playcount" in text

    def test_includes_affinity_path(self):
        """If affinity_path is provided, it appears in the output."""
        text = generate_explanation(
            artist="X",
            final_score=0.5,
            model_score=0.5,
            affinity_mm=0.0,
            affinity_lfm=0.0,
            feature_dict={"favorites": 1.0},
            weights=[0.1],
            affinity_path="seed → A → B → X",
        )
        assert "seed → A → B → X" in text


# ── rank_candidates ──────────────────────────────────────────────────────────


class TestRankCandidates:
    def test_filters_blocklist_and_cooldown(self):
        """Blocklisted and cooled-down artists are excluded."""
        scores = {
            "good_artist": 0.9,
            "blocked_artist": 0.8,
            "cooled_artist": 0.7,
            "another_good": 0.6,
        }
        blocklist = {"blocked_artist"}
        history = [{
            "round_id": "2",
            "artist_feedback": {
                "cooled_artist": {"fave_tracks": 0, "skip_tracks": 1,
                                   "listen_tracks": 0, "tracks_offered": 2}
            },
        }]
        ranked = rank_candidates(
            scores,
            blocklist=blocklist,
            history_rounds=history,
            current_round=3,
            cooldown_rounds=3,
        )
        names = [name for _, name in ranked]
        assert "blocked_artist" not in names
        assert "cooled_artist" not in names
        assert "good_artist" in names
        assert "another_good" in names

    def test_descending_order(self):
        """Results are sorted by score descending."""
        scores = {"a": 0.3, "b": 0.9, "c": 0.6}
        ranked = rank_candidates(scores)
        assert [name for _, name in ranked] == ["b", "c", "a"]

    def test_zero_scores_excluded(self):
        """Artists with zero or negative scores are excluded."""
        scores = {"a": 0.5, "b": 0.0, "c": -0.1}
        ranked = rank_candidates(scores)
        names = [name for _, name in ranked]
        assert names == ["a"]

    def test_overrides_applied(self):
        """Overrides modify scores before ranking."""
        scores = {"a": 0.3, "b": 0.5}
        overrides = {"pins": {"a": 1.0}}
        ranked = rank_candidates(scores, overrides=overrides)
        assert ranked[0] == (1.0, "a")


# ── _normalize_affinity ─────────────────────────────────────────────────────


class TestNormalizeAffinity:
    def test_preserves_negatives(self):
        """Symmetric normalization maps to [-1, 1], preserving negative scores."""
        raw = {"a": 0.5, "b": -0.3, "c": 1.0, "d": -1.0}
        normed = _normalize_affinity(raw)
        assert normed["a"] == pytest.approx(0.5)
        assert normed["b"] == pytest.approx(-0.3)
        assert normed["c"] == pytest.approx(1.0)
        assert normed["d"] == pytest.approx(-1.0)

    def test_empty(self):
        """Empty dict returns empty."""
        assert _normalize_affinity({}) == {}

    def test_scales_to_unit_range(self):
        """Largest absolute value maps to 1.0 (or -1.0)."""
        raw = {"a": 2.0, "b": -1.0, "c": 0.5}
        normed = _normalize_affinity(raw)
        assert normed["a"] == pytest.approx(1.0)
        assert normed["b"] == pytest.approx(-0.5)
        assert normed["c"] == pytest.approx(0.25)

    def test_all_zeros(self):
        """All-zero scores remain zero."""
        raw = {"a": 0.0, "b": 0.0}
        normed = _normalize_affinity(raw)
        assert normed["a"] == pytest.approx(0.0)
        assert normed["b"] == pytest.approx(0.0)

    def test_all_negative(self):
        """All-negative scores are normalized correctly."""
        raw = {"a": -0.4, "b": -0.8}
        normed = _normalize_affinity(raw)
        assert normed["a"] == pytest.approx(-0.5)
        assert normed["b"] == pytest.approx(-1.0)


# ── _collect_feedback_round ─────────────────────────────────────────────────


class TestCollectFeedbackRound:
    def test_processes_diffs_and_attaches_features(self):
        """_collect_feedback_round processes diffs and attaches features."""
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
        features = {
            "opeth": {"favorites": 55.0, "playcount": 1050.0},
            "tool": {"favorites": 30.0, "playcount": 500.0},
            "korn": {"favorites": 10.0, "playcount": 200.0},
        }
        all_offered = list(before.keys())

        result = _collect_feedback_round("2026-04-02", before, after, features, all_offered)
        assert result.round_id == "2026-04-02"
        assert result.artist_feedback["opeth"]["fave_tracks"] == 1
        assert result.artist_feedback["tool"]["skip_tracks"] == 1  # one track skipped
        # korn had no activity but IS in artist_feedback because aggregate_artist_feedback
        # includes all offered artists when all_offered_tracks is provided
        assert result.artist_feedback["korn"]["fave_tracks"] == 0
        assert result.artist_feedback["korn"]["skip_tracks"] == 0
        assert result.raw_features["opeth"]["favorites"] == 55.0
        assert result.raw_features["tool"]["favorites"] == 30.0
        # korn IS in raw_features because it's in artist_feedback (offered)
        assert result.raw_features["korn"]["favorites"] == 10.0

    def test_missing_features_excluded(self):
        """Artists without features in raw_features are not in round features."""
        before = {
            ("opeth", "ghost"): {"played": 10, "skipped": 1, "favorited": False},
        }
        after = {
            ("opeth", "ghost"): {"played": 12, "skipped": 1, "favorited": True},
        }
        # No features for opeth
        features = {}
        all_offered = list(before.keys())

        result = _collect_feedback_round("2026-04-02", before, after, features, all_offered)
        assert result.artist_feedback["opeth"]["fave_tracks"] == 1
        assert "opeth" not in result.raw_features

    def test_no_changes_still_records_offered(self):
        """When no tracks change, offered artists are still recorded via all_offered_tracks."""
        before = {
            ("tool", "sober"): {"played": 5, "skipped": 0, "favorited": False},
        }
        after = {
            ("tool", "sober"): {"played": 5, "skipped": 0, "favorited": False},
        }
        features = {"tool": {"favorites": 30.0}}
        all_offered = list(before.keys())

        result = _collect_feedback_round("2026-04-02", before, after, features, all_offered)
        # tool offered but no activity — still in artist_feedback with zero counts
        assert "tool" in result.artist_feedback
        assert result.artist_feedback["tool"]["tracks_offered"] == 1
        assert result.artist_feedback["tool"]["fave_tracks"] == 0

    def test_round_id_preserved(self):
        """Round ID is passed through to the FeedbackRound."""
        before = {("a", "b"): {"played": 0, "skipped": 0, "favorited": False}}
        after = {("a", "b"): {"played": 1, "skipped": 0, "favorited": False}}
        result = _collect_feedback_round("round-42", before, after, {}, list(before.keys()))
        assert result.round_id == "round-42"


# ── Task 5: Offered tracks persistence ──────────────────────────────────────


def test_load_offered_tracks_missing_file(tmp_path):
    from adaptive_engine import _load_offered_tracks
    track_set, entries = _load_offered_tracks(tmp_path / "offered_tracks.json")
    assert track_set == set()
    assert entries == []


def test_load_offered_tracks_corrupt_json(tmp_path):
    from adaptive_engine import _load_offered_tracks
    path = tmp_path / "offered_tracks.json"
    path.write_text("not json{{{")
    track_set, entries = _load_offered_tracks(path)
    assert track_set == set()
    assert entries == []


def test_load_offered_tracks_valid(tmp_path):
    from adaptive_engine import _load_offered_tracks
    path = tmp_path / "offered_tracks.json"
    path.write_text(json.dumps({
        "version": 1,
        "tracks": [
            {"artist": "fleet foxes", "track": "white winter hymnal", "round": 1},
            {"artist": "fleet foxes", "track": "mykonos", "round": 1},
        ]
    }))
    track_set, entries = _load_offered_tracks(path)
    assert ("fleet foxes", "white winter hymnal") in track_set
    assert ("fleet foxes", "mykonos") in track_set
    assert len(track_set) == 2
    assert len(entries) == 2


def test_save_offered_tracks_atomic(tmp_path):
    from adaptive_engine import _save_offered_tracks
    path = tmp_path / "offered_tracks.json"
    entries = [{"artist": "fleet foxes", "track": "white winter hymnal", "round": 1}]
    _save_offered_tracks(path, entries)
    data = json.loads(path.read_text())
    assert data["version"] == 1
    assert len(data["tracks"]) == 1
    assert not pathlib.Path(str(path) + ".tmp").exists()


def test_save_then_load_roundtrip(tmp_path):
    from adaptive_engine import _load_offered_tracks, _save_offered_tracks
    path = tmp_path / "offered_tracks.json"
    entries = [
        {"artist": "artist a", "track": "track 1", "round": 5},
        {"artist": "artist b", "track": "track 2", "round": 5},
    ]
    _save_offered_tracks(path, entries)
    loaded_set, loaded_entries = _load_offered_tracks(path)
    assert ("artist a", "track 1") in loaded_set
    assert ("artist b", "track 2") in loaded_set
    assert len(loaded_entries) == 2
