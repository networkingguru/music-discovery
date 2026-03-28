# tests/test_signal_analysis.py
import pytest


def _make_test_data():
    """Shared test fixtures for analysis tests.

    Designed so that different signals activate different seed artists,
    producing distinct candidate sets.  'quiet_fan' is only a favorite
    (no play-count / playlists), so candidates reachable *only* through
    quiet_fan will drop out when favorites is ablated.
    """
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
    }
    return cache, signals


def test_phase_a_produces_per_signal_results():
    from signal_analysis import run_phase_a
    cache, signals = _make_test_data()
    results = run_phase_a(cache, signals, top_n=10)
    assert set(results.keys()) == {"favorites", "playcount", "playlists",
                                    "heavy_rotation", "recommendations"}
    for signal_name, data in results.items():
        assert "ranked" in data
        assert "unique" in data
        assert "baseline_overlap" in data


def test_phase_a_favorites_only_matches_baseline():
    from signal_analysis import run_phase_a
    cache, signals = _make_test_data()
    results = run_phase_a(cache, signals, top_n=10)
    assert results["favorites"]["baseline_overlap"] == 100.0


def test_phase_a_unique_artists_are_exclusive():
    from signal_analysis import run_phase_a
    cache, signals = _make_test_data()
    results = run_phase_a(cache, signals, top_n=10)
    for sig, data in results.items():
        other_artists = set()
        for other_sig, other_data in results.items():
            if other_sig != sig:
                other_artists.update(name for _, name in other_data["ranked"][:10])
        for artist in data["unique"]:
            assert artist not in other_artists


def test_phase_b_produces_per_signal_ablation():
    from signal_analysis import run_phase_b
    cache, signals = _make_test_data()
    results = run_phase_b(cache, signals, top_n=10)
    assert set(results.keys()) == {"favorites", "playcount", "playlists",
                                    "heavy_rotation", "recommendations"}
    for signal_name, data in results.items():
        assert "dropped" in data
        assert "entered" in data
        assert "ranked" in data


def test_phase_b_dropping_signal_changes_results():
    from signal_analysis import run_phase_b
    cache, signals = _make_test_data()
    results = run_phase_b(cache, signals, top_n=10)
    any_changes = any(
        len(data["dropped"]) > 0 or len(data["entered"]) > 0
        for data in results.values()
    )
    assert any_changes
