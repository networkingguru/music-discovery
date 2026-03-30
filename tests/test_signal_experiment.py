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
    mock_ratings = {"haken": {"avg_centered": 1.0, "count": 5}}
    mock_hr = {"haken", "tool"}
    mock_recs = {"meshuggah"}

    with patch("signal_experiment.parse_library_jxa", return_value=mock_favorites), \
         patch("signal_experiment.collect_playcounts_jxa", return_value=mock_playcounts), \
         patch("signal_experiment.collect_user_playlists_jxa", return_value=mock_playlists), \
         patch("signal_experiment.collect_ratings_jxa", return_value=mock_ratings), \
         patch("signal_experiment.collect_heavy_rotation", return_value=mock_hr), \
         patch("signal_experiment.collect_recommendations", return_value=mock_recs):
        signals = collect_all_signals(
            cache_dir=tmp_path,
            api_session=MagicMock(),
        )

    assert signals["favorites"] == mock_favorites
    assert signals["playcount"] == mock_playcounts
    assert signals["playlists"] == mock_playlists
    assert signals["ratings"] == mock_ratings
    assert signals["heavy_rotation"] == mock_hr
    assert signals["recommendations"] == mock_recs

    assert (tmp_path / "playcount_cache.json").exists()
    assert (tmp_path / "playlist_membership_cache.json").exists()
    assert (tmp_path / "ratings_cache.json").exists()
    assert (tmp_path / "heavy_rotation_cache.json").exists()
    assert (tmp_path / "recommendations_cache.json").exists()


def test_collect_all_signals_loads_from_cache(tmp_path):
    """Should load from cache when files exist instead of re-collecting."""
    from signal_experiment import collect_all_signals
    (tmp_path / "playcount_cache.json").write_text(json.dumps({"haken": 100}))
    (tmp_path / "playlist_membership_cache.json").write_text(json.dumps({"haken": 3}))
    (tmp_path / "ratings_cache.json").write_text(json.dumps({"haken": {"avg_centered": 1.0, "count": 5}}))
    (tmp_path / "heavy_rotation_cache.json").write_text(json.dumps(["haken"]))
    (tmp_path / "recommendations_cache.json").write_text(json.dumps(["meshuggah"]))

    mock_favorites = {"haken": 5}

    with patch("signal_experiment.parse_library_jxa", return_value=mock_favorites), \
         patch("signal_experiment.collect_playcounts_jxa") as mock_pc, \
         patch("signal_experiment.collect_user_playlists_jxa") as mock_pl, \
         patch("signal_experiment.collect_ratings_jxa") as mock_rat, \
         patch("signal_experiment.collect_heavy_rotation") as mock_hr, \
         patch("signal_experiment.collect_recommendations") as mock_rec:
        signals = collect_all_signals(
            cache_dir=tmp_path,
            api_session=MagicMock(),
        )

    mock_pc.assert_not_called()
    mock_pl.assert_not_called()
    mock_rat.assert_not_called()
    mock_hr.assert_not_called()
    mock_rec.assert_not_called()

    assert signals["playcount"] == {"haken": 100}
    assert signals["ratings"] == {"haken": {"avg_centered": 1.0, "count": 5}}
    assert signals["heavy_rotation"] == {"haken"}


def test_collect_all_signals_skips_api_without_session(tmp_path):
    """Without an API session, API signals should be empty sets."""
    from signal_experiment import collect_all_signals
    mock_favorites = {"haken": 5}
    mock_playcounts = {"haken": 100}
    mock_playlists = {"haken": 3}
    mock_ratings = {"haken": {"avg_centered": 1.0, "count": 5}}

    with patch("signal_experiment.parse_library_jxa", return_value=mock_favorites), \
         patch("signal_experiment.collect_playcounts_jxa", return_value=mock_playcounts), \
         patch("signal_experiment.collect_user_playlists_jxa", return_value=mock_playlists), \
         patch("signal_experiment.collect_ratings_jxa", return_value=mock_ratings):
        signals = collect_all_signals(
            cache_dir=tmp_path,
            api_session=None,
        )

    assert signals["heavy_rotation"] == set()
    assert signals["recommendations"] == set()
    assert signals["ratings"] == mock_ratings


# --- Task 5: Ratings collection tests ---

def test_collect_all_signals_includes_ratings(tmp_path):
    """Ratings should be collected and cached."""
    from signal_experiment import collect_all_signals
    mock_ratings = {"tool": {"avg_centered": 0.5, "count": 3}, "haken": {"avg_centered": 1.0, "count": 10}}

    with patch("signal_experiment.parse_library_jxa", return_value={"haken": 5}), \
         patch("signal_experiment.collect_playcounts_jxa", return_value={}), \
         patch("signal_experiment.collect_user_playlists_jxa", return_value={}), \
         patch("signal_experiment.collect_ratings_jxa", return_value=mock_ratings), \
         patch("signal_experiment.collect_heavy_rotation", return_value=set()), \
         patch("signal_experiment.collect_recommendations", return_value=set()):
        signals = collect_all_signals(cache_dir=tmp_path, api_session=MagicMock())

    assert signals["ratings"] == mock_ratings
    assert (tmp_path / "ratings_cache.json").exists()
    cached = json.loads((tmp_path / "ratings_cache.json").read_text())
    assert cached["tool"]["avg_centered"] == 0.5


def test_collect_all_signals_loads_ratings_from_cache(tmp_path):
    """Ratings should load from cache when file exists."""
    from signal_experiment import collect_all_signals
    cached_ratings = {"haken": {"avg_centered": 1.0, "count": 5}}
    (tmp_path / "ratings_cache.json").write_text(json.dumps(cached_ratings))
    (tmp_path / "playcount_cache.json").write_text(json.dumps({}))
    (tmp_path / "playlist_membership_cache.json").write_text(json.dumps({}))
    (tmp_path / "heavy_rotation_cache.json").write_text(json.dumps([]))
    (tmp_path / "recommendations_cache.json").write_text(json.dumps([]))

    with patch("signal_experiment.parse_library_jxa", return_value={"haken": 5}), \
         patch("signal_experiment.collect_ratings_jxa") as mock_rat:
        signals = collect_all_signals(cache_dir=tmp_path, api_session=MagicMock())

    mock_rat.assert_not_called()
    assert signals["ratings"] == cached_ratings


# --- Task 6: Stratified eval playlist builder ---

def test_build_stratified_artist_list_equal_per_signal():
    """Each signal should get roughly equal slots in stratum 1."""
    from signal_experiment import build_stratified_artist_list
    phase_a = {
        "playcount": {"ranked": [(1.0, f"pc_{i}") for i in range(50)]},
        "playlists": {"ranked": [(1.0, f"pl_{i}") for i in range(50)]},
        "favorites": {"ranked": [(1.0, f"fav_{i}") for i in range(50)]},
    }
    phase_d = [
        {"name": "blend1", "ranked": [(1.0, f"blend_{i}") for i in range(50)]},
    ]
    result = build_stratified_artist_list(phase_a, phase_d, target_total=105)

    # Check stratum 1 has roughly equal per signal
    solo_counts = {}
    for entry in result:
        if entry["stratum"].startswith("solo:"):
            sig = entry["stratum"].split(":", 1)[1]
            solo_counts[sig] = solo_counts.get(sig, 0) + 1

    counts = list(solo_counts.values())
    assert len(counts) == 3
    # Each should be stratum1_total // n_signals = 78 // 3 = 26
    for c in counts:
        assert c == 26

    assert len(result) == 105


def test_build_stratified_artist_list_deduplicates():
    """No duplicate artists in the result."""
    from signal_experiment import build_stratified_artist_list
    # Overlapping artists across signals
    phase_a = {
        "sig1": {"ranked": [(1.0, "shared"), (0.9, "unique1")]},
        "sig2": {"ranked": [(1.0, "shared"), (0.9, "unique2")]},
    }
    phase_d = [{"name": "blend", "ranked": [(1.0, "shared"), (0.9, "blend1")]}]
    result = build_stratified_artist_list(phase_a, phase_d, target_total=10)

    names = [e["name"] for e in result]
    assert len(names) == len(set(names)), "Duplicate artists found"


def test_build_stratified_artist_list_excludes_prior():
    """Prior session artists should be excluded."""
    from signal_experiment import build_stratified_artist_list
    phase_a = {
        "sig1": {"ranked": [(1.0, "old_artist"), (0.9, "new_artist")]},
    }
    phase_d = []
    result = build_stratified_artist_list(
        phase_a, phase_d, target_total=10,
        prior_artists={"old_artist"})

    names = [e["name"] for e in result]
    assert "old_artist" not in names
    assert "new_artist" in names


# --- Task 7: Manifest tracking ---

def test_load_manifest_empty(tmp_path):
    """Loading a non-existent manifest returns empty structure."""
    from signal_experiment import load_manifest
    manifest = load_manifest(tmp_path / "nonexistent.json")
    assert manifest == {"sessions": []}


def test_load_manifest_existing(tmp_path):
    """Loading an existing manifest returns its content."""
    from signal_experiment import load_manifest
    data = {"sessions": [{"session_id": 1, "artists": [{"name": "haken"}]}]}
    (tmp_path / "manifest.json").write_text(json.dumps(data))
    manifest = load_manifest(tmp_path / "manifest.json")
    assert manifest == data


def test_get_prior_artists_from_manifest():
    """Should extract all artist names from all sessions."""
    from signal_experiment import get_prior_artists
    manifest = {
        "sessions": [
            {"artists": [{"name": "haken"}, {"name": "tool"}]},
            {"artists": [{"name": "bjork"}, {"name": "haken"}]},
        ]
    }
    prior = get_prior_artists(manifest)
    assert prior == {"haken", "tool", "bjork"}


def test_save_manifest_appends_session(tmp_path):
    """Should append a new session with date and ID."""
    from signal_experiment import save_manifest_session, load_manifest
    manifest_path = tmp_path / "manifest.json"
    manifest = {"sessions": []}
    artists = [{"name": "haken", "stratum": "solo:playcount", "rank": 1}]

    save_manifest_session(manifest_path, manifest, artists)

    loaded = load_manifest(manifest_path)
    assert len(loaded["sessions"]) == 1
    assert loaded["sessions"][0]["session_id"] == 1
    assert loaded["sessions"][0]["artists"] == artists
    assert "date" in loaded["sessions"][0]


# --- Task 8: Accumulative post-listen scoring ---

def test_load_post_listen_history_empty(tmp_path):
    """Loading non-existent history returns empty structure."""
    from signal_experiment import load_post_listen_history
    history = load_post_listen_history(tmp_path / "nonexistent.json")
    assert history == {"rounds": [], "cumulative": {}}


def test_accumulate_post_listen_round():
    """Should accumulate round data into cumulative totals."""
    from signal_experiment import accumulate_post_listen_round
    history = {"rounds": [], "cumulative": {}}
    round_data = {
        "new_favorites": ["haken", "tool"],
        "per_config_hits": {
            "Config A": {"hits": 2, "pool_size": 10},
            "Config B": {"hits": 1, "pool_size": 10},
        },
        "per_signal_solo_hits": {
            "playcount": {"hits": 1, "pool_size": 5},
        },
    }

    history = accumulate_post_listen_round(history, round_data)
    assert history["cumulative"]["total_new_favorites"] == 2
    assert history["cumulative"]["per_config"]["Config A"]["hits"] == 2
    assert history["cumulative"]["per_signal_solo"]["playcount"]["hits"] == 1
    assert len(history["rounds"]) == 1

    # Second round accumulates
    round_data2 = {
        "new_favorites": ["bjork"],
        "per_config_hits": {
            "Config A": {"hits": 1, "pool_size": 10},
        },
        "per_signal_solo_hits": {},
    }
    history = accumulate_post_listen_round(history, round_data2)
    assert history["cumulative"]["total_new_favorites"] == 3
    assert history["cumulative"]["per_config"]["Config A"]["hits"] == 3
    assert len(history["rounds"]) == 2


def test_run_statistical_test_insufficient_data():
    """Should return None when not enough favorites."""
    from signal_experiment import run_statistical_test
    cumulative = {"total_new_favorites": 5, "per_config": {}}
    assert run_statistical_test(cumulative) is None


def test_run_statistical_test_with_enough_data():
    """Should return test results when enough data."""
    from signal_experiment import run_statistical_test
    cumulative = {
        "total_new_favorites": 40,
        "per_config": {
            "Config A": {"hits": 15, "pool_size": 50},
            "Config B": {"hits": 5, "pool_size": 50},
        },
    }
    result = run_statistical_test(cumulative)
    assert result is not None
    assert result["best_config"] == "Config A"
    assert "p_value" in result
    assert isinstance(result["significant"], bool)
    assert "Config A" in result["all_rates"]
    assert result["all_rates"]["Config A"]["rate"] == 30.0


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


# --- Integration test ---

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
    mock_ratings = {"haken": {"avg_centered": 1.0, "count": 10}, "tool": {"avg_centered": 0.5, "count": 5}}
    mock_hr = {"tool", "radiohead"}
    mock_recs = {"haken", "bjork"}

    with patch("signal_experiment.parse_library_jxa", return_value=mock_favorites), \
         patch("signal_experiment.collect_playcounts_jxa", return_value=mock_playcounts), \
         patch("signal_experiment.collect_user_playlists_jxa", return_value=mock_playlists), \
         patch("signal_experiment.collect_ratings_jxa", return_value=mock_ratings), \
         patch("signal_experiment.collect_heavy_rotation", return_value=mock_hr), \
         patch("signal_experiment.collect_recommendations", return_value=mock_recs):
        signals = collect_all_signals(cache_dir=tmp_path, api_session=MagicMock())

    report, phase_a, phase_d = run_experiment(
        signals, scrape_cache, apple_cache, rejected_cache,
        user_blocklist, top_n=10)

    assert "Phase A" in report
    assert "Phase B" in report
    assert "Phase C" in report
    assert "Phase D" in report

    assert len(phase_d) >= 3
    for rec in phase_d:
        assert len(rec["ranked"]) > 0

    assert isinstance(phase_a, dict)
    assert len(phase_a) > 0

    eval_artists = get_evaluation_artists(phase_d, top_n=10)
    assert len(eval_artists) > 0


# --- Post-listen scoring ---

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
