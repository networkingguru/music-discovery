# tests/test_signal_scoring.py
import math
import pytest


def test_compute_signal_value_logarithmic():
    from signal_scoring import compute_signal_value
    result = compute_signal_value(10)
    assert abs(result - math.sqrt(math.log(11))) < 0.001

def test_compute_signal_value_zero():
    from signal_scoring import compute_signal_value
    assert compute_signal_value(0) == 0.0

def test_compute_signal_value_capped():
    from signal_scoring import compute_signal_value
    capped = compute_signal_value(100, cap=5)
    uncapped_at_5 = compute_signal_value(5)
    assert abs(capped - uncapped_at_5) < 0.001

def test_compute_seed_weight_single_signal():
    from signal_scoring import compute_seed_weight
    weights = {"favorites": 1.0, "playcount": 0.0, "playlists": 0.0,
               "heavy_rotation": 0.0, "recommendations": 0.0}
    signals = {
        "favorites": {"haken": 5},
        "playcount": {"haken": 100},
        "playlists": {"haken": 3},
        "heavy_rotation": {"haken"},
        "recommendations": set(),
    }
    result = compute_seed_weight("haken", signals, weights)
    expected = 1.0 * math.sqrt(math.log(6))
    assert abs(result - expected) < 0.001

def test_compute_seed_weight_multi_signal():
    from signal_scoring import compute_seed_weight
    weights = {"favorites": 1.0, "playcount": 0.3, "playlists": 0.0,
               "heavy_rotation": 0.0, "recommendations": 0.0}
    signals = {
        "favorites": {"haken": 5},
        "playcount": {"haken": 100},
        "playlists": {},
        "heavy_rotation": set(),
        "recommendations": set(),
    }
    result = compute_seed_weight("haken", signals, weights)
    fav_part = 1.0 * math.sqrt(math.log(6))
    pc_part = 0.3 * math.sqrt(math.log(101))
    assert abs(result - (fav_part + pc_part)) < 0.001

def test_compute_seed_weight_binary_signal():
    from signal_scoring import compute_seed_weight
    weights = {"favorites": 0.0, "playcount": 0.0, "playlists": 0.0,
               "heavy_rotation": 0.5, "recommendations": 0.0}
    signals = {
        "favorites": {}, "playcount": {}, "playlists": {},
        "heavy_rotation": {"haken"}, "recommendations": set(),
    }
    result = compute_seed_weight("haken", signals, weights)
    assert abs(result - 0.5) < 0.001

def test_compute_seed_weight_not_in_binary_signal():
    from signal_scoring import compute_seed_weight
    weights = {"favorites": 0.0, "playcount": 0.0, "playlists": 0.0,
               "heavy_rotation": 0.5, "recommendations": 0.0}
    signals = {
        "favorites": {}, "playcount": {}, "playlists": {},
        "heavy_rotation": {"tool"}, "recommendations": set(),
    }
    result = compute_seed_weight("haken", signals, weights)
    assert result == 0.0

def test_score_candidates_multisignal_basic():
    from signal_scoring import score_candidates_multisignal
    cache = {
        "haken": {"umpfel": 0.9, "native construct": 0.8},
        "tool": {"umpfel": 0.7, "meshuggah": 0.6},
    }
    signals = {
        "favorites": {"haken": 5, "tool": 2},
        "playcount": {"haken": 100, "tool": 50},
        "playlists": {},
        "heavy_rotation": set(),
        "recommendations": set(),
    }
    weights = {"favorites": 1.0, "playcount": 0.3, "playlists": 0.0,
               "heavy_rotation": 0.0, "recommendations": 0.0}
    ranked = score_candidates_multisignal(cache, signals, weights)
    names = [name for _, name in ranked]
    assert "umpfel" in names
    assert "haken" not in names
    assert "tool" not in names

def test_score_candidates_multisignal_excludes_blocklist():
    from signal_scoring import score_candidates_multisignal
    cache = {"haken": {"umpfel": 0.9, "bad artist": 0.8}}
    signals = {
        "favorites": {"haken": 5}, "playcount": {}, "playlists": {},
        "heavy_rotation": set(), "recommendations": set(),
    }
    weights = {"favorites": 1.0, "playcount": 0.0, "playlists": 0.0,
               "heavy_rotation": 0.0, "recommendations": 0.0}
    ranked = score_candidates_multisignal(
        cache, signals, weights, user_blocklist={"bad artist"})
    names = [name for _, name in ranked]
    assert "umpfel" in names
    assert "bad artist" not in names

def test_score_candidates_multisignal_with_negative_scoring():
    from signal_scoring import score_candidates_multisignal
    cache = {"haken": {"umpfel": 0.9, "pop artist": 0.5}}
    blocklist_cache = {"reo speedwagon": {"pop artist": 0.8}}
    signals = {
        "favorites": {"haken": 5}, "playcount": {}, "playlists": {},
        "heavy_rotation": set(), "recommendations": set(),
    }
    weights = {"favorites": 1.0, "playcount": 0.0, "playlists": 0.0,
               "heavy_rotation": 0.0, "recommendations": 0.0}
    ranked = score_candidates_multisignal(
        cache, signals, weights, blocklist_cache=blocklist_cache, neg_penalty=0.4)
    scores = {name: score for score, name in ranked}
    assert scores["umpfel"] > scores["pop artist"]

def test_score_candidates_zero_weight_artist_excluded():
    from signal_scoring import score_candidates_multisignal
    cache = {
        "haken": {"umpfel": 0.9},
        "unknown": {"other": 0.9},
    }
    signals = {
        "favorites": {"haken": 5}, "playcount": {}, "playlists": {},
        "heavy_rotation": set(), "recommendations": set(),
    }
    weights = {"favorites": 1.0, "playcount": 0.0, "playlists": 0.0,
               "heavy_rotation": 0.0, "recommendations": 0.0}
    ranked = score_candidates_multisignal(cache, signals, weights)
    names = [name for _, name in ranked]
    scores = {name: score for score, name in ranked}
    assert "umpfel" in names
    assert scores.get("other", 0.0) == 0.0

def test_compute_seed_weight_ratings_positive():
    """Ratings signal should produce positive weight for liked artists."""
    from signal_scoring import compute_seed_weight
    weights = {"favorites": 0.0, "playcount": 0.0, "playlists": 0.0,
               "heavy_rotation": 0.0, "recommendations": 0.0, "ratings": 1.0}
    signals = {
        "favorites": {}, "playcount": {}, "playlists": {},
        "heavy_rotation": set(), "recommendations": set(),
        "ratings": {"haken": {"avg_centered": 0.75, "count": 20}},
    }
    result = compute_seed_weight("haken", signals, weights)
    assert result > 0
    expected = 1.0 * 0.75 * math.sqrt(math.log(21))
    assert abs(result - expected) < 0.001


def test_compute_seed_weight_ratings_negative():
    """Ratings signal should produce negative weight for disliked artists."""
    from signal_scoring import compute_seed_weight
    weights = {"favorites": 0.0, "playcount": 0.0, "playlists": 0.0,
               "heavy_rotation": 0.0, "recommendations": 0.0, "ratings": 1.0}
    signals = {
        "favorites": {}, "playcount": {}, "playlists": {},
        "heavy_rotation": set(), "recommendations": set(),
        "ratings": {"nickelback": {"avg_centered": -0.5, "count": 10}},
    }
    result = compute_seed_weight("nickelback", signals, weights)
    assert result < 0
    expected = 1.0 * (-0.5) * math.sqrt(math.log(11))
    assert abs(result - expected) < 0.001


def test_compute_seed_weight_ratings_zero_for_missing():
    """Artists not in ratings dict should get 0 from ratings signal."""
    from signal_scoring import compute_seed_weight
    weights = {"favorites": 0.0, "playcount": 0.0, "playlists": 0.0,
               "heavy_rotation": 0.0, "recommendations": 0.0, "ratings": 1.0}
    signals = {
        "favorites": {}, "playcount": {}, "playlists": {},
        "heavy_rotation": set(), "recommendations": set(),
        "ratings": {"haken": {"avg_centered": 0.75, "count": 20}},
    }
    result = compute_seed_weight("unknown", signals, weights)
    assert result == 0.0


def test_score_candidates_negative_seed_weight_penalizes():
    """An artist with negative seed weight should penalize similar candidates."""
    from signal_scoring import score_candidates_multisignal
    cache = {
        "liked": {"candidate_a": 0.9},
        "disliked": {"candidate_a": 0.8, "candidate_b": 0.9},
    }
    signals = {
        "favorites": {"liked": 5}, "playcount": {}, "playlists": {},
        "heavy_rotation": set(), "recommendations": set(),
        "ratings": {
            "liked": {"avg_centered": 0.75, "count": 20},
            "disliked": {"avg_centered": -0.75, "count": 20},
        },
    }
    weights = {"favorites": 1.0, "playcount": 0.0, "playlists": 0.0,
               "heavy_rotation": 0.0, "recommendations": 0.0, "ratings": 1.0}
    ranked = score_candidates_multisignal(cache, signals, weights)
    scores = {name: score for score, name in ranked}
    assert scores.get("candidate_b", 0) < 0
