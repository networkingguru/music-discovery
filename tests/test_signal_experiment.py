# tests/test_signal_experiment.py
import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


def test_collect_all_signals_caches_results(tmp_path):
    """Should cache all signal data to JSON files."""
    from signal_experiment import collect_all_signals
    mock_favorites = {"haken": 5, "tool": 2}
    mock_playcounts = {"haken": 100, "tool": 50}
    mock_playlists = {"haken": 3}
    mock_hr = {"haken", "tool"}
    mock_recs = {"meshuggah"}

    with patch("signal_experiment.parse_library_jxa", return_value=mock_favorites), \
         patch("signal_experiment.collect_playcounts_jxa", return_value=mock_playcounts), \
         patch("signal_experiment.collect_user_playlists_jxa", return_value=mock_playlists), \
         patch("signal_experiment.collect_heavy_rotation", return_value=mock_hr), \
         patch("signal_experiment.collect_recommendations", return_value=mock_recs):
        signals = collect_all_signals(
            cache_dir=tmp_path,
            api_session=MagicMock(),
        )

    assert signals["favorites"] == mock_favorites
    assert signals["playcount"] == mock_playcounts
    assert signals["playlists"] == mock_playlists
    assert signals["heavy_rotation"] == mock_hr
    assert signals["recommendations"] == mock_recs

    assert (tmp_path / "playcount_cache.json").exists()
    assert (tmp_path / "playlist_membership_cache.json").exists()
    assert (tmp_path / "heavy_rotation_cache.json").exists()
    assert (tmp_path / "recommendations_cache.json").exists()


def test_collect_all_signals_loads_from_cache(tmp_path):
    """Should load from cache when files exist instead of re-collecting."""
    from signal_experiment import collect_all_signals
    (tmp_path / "playcount_cache.json").write_text(json.dumps({"haken": 100}))
    (tmp_path / "playlist_membership_cache.json").write_text(json.dumps({"haken": 3}))
    (tmp_path / "heavy_rotation_cache.json").write_text(json.dumps(["haken"]))
    (tmp_path / "recommendations_cache.json").write_text(json.dumps(["meshuggah"]))

    mock_favorites = {"haken": 5}

    with patch("signal_experiment.parse_library_jxa", return_value=mock_favorites), \
         patch("signal_experiment.collect_playcounts_jxa") as mock_pc, \
         patch("signal_experiment.collect_user_playlists_jxa") as mock_pl, \
         patch("signal_experiment.collect_heavy_rotation") as mock_hr, \
         patch("signal_experiment.collect_recommendations") as mock_rec:
        signals = collect_all_signals(
            cache_dir=tmp_path,
            api_session=MagicMock(),
        )

    mock_pc.assert_not_called()
    mock_pl.assert_not_called()
    mock_hr.assert_not_called()
    mock_rec.assert_not_called()

    assert signals["playcount"] == {"haken": 100}
    assert signals["heavy_rotation"] == {"haken"}


def test_collect_all_signals_skips_api_without_session(tmp_path):
    """Without an API session, API signals should be empty sets."""
    from signal_experiment import collect_all_signals
    mock_favorites = {"haken": 5}
    mock_playcounts = {"haken": 100}
    mock_playlists = {"haken": 3}

    with patch("signal_experiment.parse_library_jxa", return_value=mock_favorites), \
         patch("signal_experiment.collect_playcounts_jxa", return_value=mock_playcounts), \
         patch("signal_experiment.collect_user_playlists_jxa", return_value=mock_playlists):
        signals = collect_all_signals(
            cache_dir=tmp_path,
            api_session=None,
        )

    assert signals["heavy_rotation"] == set()
    assert signals["recommendations"] == set()


# --- Task 9: Evaluation artist selection ---

def test_get_evaluation_artists_union_of_top_10():
    """Should return union of top-10 artists across all recommendations."""
    from signal_experiment import get_evaluation_artists
    recs = [
        {"name": "A", "ranked": [(1.0, f"artist_{i}") for i in range(25)]},
        {"name": "B", "ranked": [(1.0, f"other_{i}") for i in range(25)]},
    ]
    artists = get_evaluation_artists(recs, top_n=10)
    assert len(artists) == 20
    assert "artist_0" in artists
    assert "other_0" in artists
    assert "artist_15" not in artists


def test_get_evaluation_artists_deduplicates():
    """Artists appearing in multiple configs should only appear once."""
    from signal_experiment import get_evaluation_artists
    recs = [
        {"name": "A", "ranked": [(1.0, "haken"), (0.9, "tool")]},
        {"name": "B", "ranked": [(1.0, "haken"), (0.9, "meshuggah")]},
    ]
    artists = get_evaluation_artists(recs, top_n=10)
    assert artists.count("haken") <= 1
    assert set(artists) == {"haken", "tool", "meshuggah"}


# --- Task 11: Integration test ---

def test_full_experiment_produces_report(tmp_path):
    """Full experiment should produce a report with all phases."""
    from signal_experiment import collect_all_signals, run_experiment, get_evaluation_artists

    scrape_cache = {
        "haken": {"umpfel": 0.9, "native construct": 0.8, "caligulas horse": 0.7},
        "tool": {"meshuggah": 0.8, "umpfel": 0.6, "gojira": 0.5},
        "radiohead": {"portishead": 0.7, "massive attack": 0.6, "bjork": 0.5},
    }
    apple_cache = {
        "haken": ["leprous", "between the buried and me"],
        "tool": ["a perfect circle", "deftones"],
    }
    rejected_cache = {
        "reo speedwagon": {"journey": 0.9, "foreigner": 0.8},
    }
    user_blocklist = {"reo speedwagon"}

    mock_favorites = {"haken": 5, "tool": 3, "radiohead": 2}
    mock_playcounts = {"haken": 100, "tool": 50, "radiohead": 30, "adele": 200}
    mock_playlists = {"haken": 3, "radiohead": 2}
    mock_hr = {"tool", "radiohead"}
    mock_recs = {"haken", "bjork"}

    with patch("signal_experiment.parse_library_jxa", return_value=mock_favorites), \
         patch("signal_experiment.collect_playcounts_jxa", return_value=mock_playcounts), \
         patch("signal_experiment.collect_user_playlists_jxa", return_value=mock_playlists), \
         patch("signal_experiment.collect_heavy_rotation", return_value=mock_hr), \
         patch("signal_experiment.collect_recommendations", return_value=mock_recs):
        signals = collect_all_signals(cache_dir=tmp_path, api_session=MagicMock())

    report, phase_d = run_experiment(
        signals, scrape_cache, apple_cache, rejected_cache,
        user_blocklist, top_n=10)

    assert "Phase A" in report
    assert "Phase B" in report
    assert "Phase C" in report
    assert "Phase D" in report

    assert len(phase_d) >= 3
    for rec in phase_d:
        assert len(rec["ranked"]) > 0

    eval_artists = get_evaluation_artists(phase_d, top_n=10)
    assert len(eval_artists) > 0


# --- Task 12: Post-listen scoring ---

def test_post_listen_scoring():
    """Post-listen should score each config against new favorites."""
    from signal_experiment import score_post_listen

    recs = [
        {"name": "Config A", "weights": {}, "rationale": "test",
         "ranked": [(1.0, "haken"), (0.9, "tool"), (0.8, "meshuggah"),
                    (0.7, "gojira"), (0.6, "umpfel"), (0.5, "leprous"),
                    (0.4, "bjork"), (0.3, "portishead"), (0.2, "massive attack"),
                    (0.1, "radiohead")],
         "baseline_diff": {"entered": [], "dropped": []}},
        {"name": "Config B", "weights": {}, "rationale": "test",
         "ranked": [(1.0, "bjork"), (0.9, "portishead"), (0.8, "massive attack"),
                    (0.7, "haken"), (0.6, "tool"), (0.5, "meshuggah"),
                    (0.4, "gojira"), (0.3, "umpfel"), (0.2, "leprous"),
                    (0.1, "radiohead")],
         "baseline_diff": {"entered": [], "dropped": []}},
    ]

    new_fav_artists = {"haken", "bjork"}
    results = score_post_listen(recs, new_fav_artists, top_n=10)

    assert len(results) == 2
    assert results[0]["name"] == "Config A"
    assert results[0]["hits"] == 2
    assert results[0]["precision"] == 20.0
    assert results[1]["name"] == "Config B"
    assert results[1]["hits"] == 2
