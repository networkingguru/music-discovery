# tests/test_signal_report.py
import pytest


def _make_fake_analysis():
    from signal_scoring import ALL_SIGNALS

    phase_a = {}
    for sig in ALL_SIGNALS:
        phase_a[sig] = {
            "ranked": [(1.0, "artist_a"), (0.5, "artist_b")],
            "unique": ["artist_a"] if sig == "playcount" else [],
            "baseline_overlap": 80.0 if sig != "favorites" else 100.0,
        }

    phase_b = {}
    for sig in ALL_SIGNALS:
        phase_b[sig] = {
            "ranked": [(1.0, "artist_a"), (0.5, "artist_b")],
            "dropped": ["artist_c"] if sig == "favorites" else [],
            "entered": ["artist_d"] if sig == "favorites" else [],
        }

    phase_c = {
        "baseline": {
            "desc": "Favorites only", "ranked": [(1.0, "a")],
            "weights": {"favorites": 1.0}, "caps": {}, "full_overlap": 70.0,
        },
        "full_signals": {
            "desc": "All on", "ranked": [(1.0, "a"), (0.5, "b")],
            "weights": {s: 1.0 for s in ALL_SIGNALS}, "caps": {}, "full_overlap": 100.0,
        },
    }

    phase_d = [
        {
            "name": "Balanced",
            "rationale": "Good default",
            "weights": {"favorites": 1.0, "playcount": 0.5, "playlists": 0.3,
                        "heavy_rotation": 0.2, "recommendations": 0.2},
            "ranked": [(1.0, "artist_a"), (0.8, "artist_b")],
            "baseline_diff": {"entered": ["artist_b"], "dropped": []},
        },
    ]

    return phase_a, phase_b, phase_c, phase_d


def test_generate_report_contains_all_phases():
    from signal_report import generate_wargaming_report
    a, b, c, d = _make_fake_analysis()
    report = generate_wargaming_report(a, b, c, d, library_count=1000)
    assert "Phase A" in report
    assert "Phase B" in report
    assert "Phase C" in report
    assert "Phase D" in report


def test_generate_report_contains_signal_names():
    from signal_report import generate_wargaming_report
    a, b, c, d = _make_fake_analysis()
    report = generate_wargaming_report(a, b, c, d, library_count=1000)
    for sig in ["favorites", "playcount", "playlists", "heavy_rotation", "recommendations"]:
        assert sig in report.lower() or sig.replace("_", " ") in report.lower()


def test_generate_report_contains_recommendation_names():
    from signal_report import generate_wargaming_report
    a, b, c, d = _make_fake_analysis()
    report = generate_wargaming_report(a, b, c, d, library_count=1000)
    assert "Balanced" in report
    assert "Good default" in report


def test_generate_report_is_string():
    from signal_report import generate_wargaming_report
    a, b, c, d = _make_fake_analysis()
    report = generate_wargaming_report(a, b, c, d, library_count=1000)
    assert isinstance(report, str)
    assert len(report) > 100
