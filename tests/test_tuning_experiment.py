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
        assert names[0] == "cand_a"
        assert len(result) == 3

    def test_apple_weight_adds_bonus(self):
        """Apple matches get flat bonus per seed artist."""
        cache = {"loved1": {"cand_a": 0.5}}
        library = {"loved1": 1}
        apple_cache = {"loved1": ["cand_a", "cand_b"]}
        result = score_artists_tunable(
            cache, library,
            apple_cache=apple_cache, blocklist_cache={}, user_blocklist=set(),
            apple_weight=0.1, neg_penalty=0.0,
        )
        scores = {name: score for score, name in result}
        assert scores["cand_a"] > scores["cand_b"]
        assert "cand_b" in scores

    def test_apple_add_if_absent_only(self):
        """Apple bonus only applies for candidates NOT already in musicmap for that seed."""
        cache = {"loved1": {"cand_a": 0.9}}
        library = {"loved1": 1}
        apple_cache = {"loved1": ["cand_a"]}
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
        scores_with = {name: score for score, name in result_with}
        scores_without = {name: score for score, name in result_without}
        assert scores_with["cand_a"] == scores_without["cand_a"]

    def test_negative_penalty_reduces_score(self):
        """Negative penalty reduces score for candidates near blocklisted artists."""
        cache = {"loved1": {"cand_a": 0.9, "cand_b": 0.5}}
        library = {"loved1": 2}
        blocklist_cache = {"bad_artist": {"cand_a": 0.8}}
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
        assert scores_with["cand_b"] == scores_no["cand_b"]

    def test_library_artists_excluded(self):
        """Library artists never appear as candidates."""
        cache = {"loved1": {"loved2": 0.9, "cand_a": 0.5}}
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
        cache = {"loved1": {"cand_a": 0.9, "blocked_one": 0.8}}
        library = {"loved1": 1}
        result = score_artists_tunable(
            cache, library,
            apple_cache={}, blocklist_cache={}, user_blocklist={"blocked_one"},
            apple_weight=0.0, neg_penalty=0.0,
        )
        names = [name for _, name in result]
        assert "blocked_one" not in names
