"""Tests for tuning_experiment.py."""
import pytest
import sys
import pathlib
from unittest.mock import MagicMock, patch
import json
import tempfile
import os

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from tuning_experiment import score_artists_tunable, prefetch_apple_data, generate_report, APPLE_WEIGHTS, NEG_PENALTIES
from tuning_experiment import main as tuning_main


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

        client.search_artist.assert_called_once_with("portishead")
        assert result["radiohead"] == ["thom yorke", "muse"]
        assert "massive attack" in result["portishead"]


class TestGenerateReport:
    """Test report generation."""

    def test_report_contains_all_variants(self):
        """Report includes a section for every variant in the matrix."""
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
        for aw in APPLE_WEIGHTS:
            for np_ in NEG_PENALTIES:
                if (aw, np_) not in variants:
                    variants[(aw, np_)] = [(1.0, "x")]
        report = generate_report(variants, top_n=5, library_count=10)
        lines = report.split("\n")
        baseline_entries = [l for l in lines if l.strip().startswith("5.")]
        assert len(baseline_entries) >= 1
        rank_6 = [l for l in lines if l.strip().startswith("6.")]
        assert len(rank_6) == 0


class TestMainSmoke:
    """Smoke test for main() wiring."""

    @patch("tuning_experiment.prefetch_apple_data")
    @patch("tuning_experiment.AppleMusicClient")
    @patch("tuning_experiment.generate_apple_music_token")
    @patch("tuning_experiment.filter_candidates")
    @patch("tuning_experiment.load_user_blocklist")
    @patch("tuning_experiment.load_cache")
    @patch("tuning_experiment.load_dotenv")
    @patch("tuning_experiment._build_paths")
    @patch("tuning_experiment.parse_library_jxa")
    def test_main_runs_without_error(self, mock_jxa, mock_paths, mock_dotenv,
                                      mock_load_cache, mock_ubl,
                                      mock_filter, mock_token, mock_client_cls,
                                      mock_prefetch, tmp_path, monkeypatch):
        """main() wires everything together without crashing."""
        mock_paths.return_value = {
            "cache": tmp_path / "music_map_cache.json",
            "filter_cache": tmp_path / "filter_cache.json",
            "blocklist": tmp_path / "blocklist_cache.json",
            "rejected_scrape": tmp_path / "rejected_scrape_cache.json",
            "top_tracks": tmp_path / "top_tracks_cache.json",
            "output": tmp_path / "results.txt",
            "playlist_xml": tmp_path / "playlist.xml",
        }
        mock_jxa.return_value = {"loved1": 3, "loved2": 1}
        mock_load_cache.side_effect = [
            {"loved1": {"cand_a": 0.9, "cand_b": 0.5}},
            {"cand_a": {"listeners": 1000, "debut_year": 2015}},
            {},
        ]
        mock_ubl.return_value = set()
        mock_filter.side_effect = lambda scored, *a, **kw: scored
        mock_prefetch.return_value = {"loved1": ["cand_d"]}
        mock_token.return_value = "fake-token"

        monkeypatch.setattr("sys.argv", ["tuning_experiment.py"])
        monkeypatch.setenv("APPLE_MUSIC_KEY_ID", "test")
        monkeypatch.setenv("APPLE_MUSIC_TEAM_ID", "test")
        monkeypatch.setenv("APPLE_MUSIC_KEY_PATH", "/tmp/fake.p8")
        monkeypatch.setattr("tuning_experiment.OUTPUT_DIR", tmp_path)

        tuning_main()  # should not raise
        assert (tmp_path / "tuning_results.md").exists()
