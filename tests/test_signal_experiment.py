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
