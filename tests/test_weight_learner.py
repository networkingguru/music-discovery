# tests/test_weight_learner.py
"""Tests for the weight_learner module."""

import json
import math
import sys
import pathlib
import tempfile
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from weight_learner import (
    WeightLearner,
    compute_candidate_features,
    ALL_SIGNAL_NAMES,
    SEED_AGGREGATE_SIGNALS,
    DIRECT_SIGNALS,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_features(sig_a: float, sig_b: float) -> dict:
    """Build a two-signal feature dict."""
    return {"sig_a": sig_a, "sig_b": sig_b}


def _fit_two_signal(n_pos: int = 10, n_neg: int = 10) -> WeightLearner:
    """Fit a learner where sig_a predicts positive class, sig_b is noise."""
    import random
    rng = random.Random(42)

    features = []
    labels = []

    # Positives: sig_a ~ N(1, 0.1), sig_b ~ N(0, 1)
    for _ in range(n_pos):
        features.append({"sig_a": 1.0 + rng.gauss(0, 0.1), "sig_b": rng.gauss(0, 1)})
        labels.append(1)

    # Negatives: sig_a ~ N(0, 0.1), sig_b ~ N(0, 1)
    for _ in range(n_neg):
        features.append({"sig_a": 0.0 + rng.gauss(0, 0.1), "sig_b": rng.gauss(0, 1)})
        labels.append(0)

    learner = WeightLearner(signal_names=["sig_a", "sig_b"])
    learner.fit(features, labels)
    return learner


# ── test_fit_produces_nonzero_weights ─────────────────────────────────────────

def test_fit_produces_nonzero_weights():
    """sig_a predicts favorites; sig_b is noise → |weight_a| > |weight_b|."""
    learner = _fit_two_signal(n_pos=20, n_neg=20)
    assert learner._fitted
    assert len(learner._weights) == 2
    w_a = abs(learner._weights[0])
    w_b = abs(learner._weights[1])
    assert w_a > w_b, (
        f"Expected |weight_sig_a|={w_a:.4f} > |weight_sig_b|={w_b:.4f}"
    )


# ── test_fit_handles_class_imbalance ─────────────────────────────────────────

def test_fit_handles_class_imbalance():
    """3 positives, 27 negatives → model still predicts higher P for positive examples."""
    import random
    rng = random.Random(7)

    features = []
    labels = []
    # Positives (3): sig_a high
    for _ in range(3):
        features.append({"sig_a": 2.0 + rng.gauss(0, 0.05), "sig_b": rng.gauss(0, 0.5)})
        labels.append(1)
    # Negatives (27): sig_a near zero
    for _ in range(27):
        features.append({"sig_a": 0.0 + rng.gauss(0, 0.05), "sig_b": rng.gauss(0, 0.5)})
        labels.append(0)

    learner = WeightLearner(signal_names=["sig_a", "sig_b"])
    learner.fit(features, labels)

    p_pos = learner.predict_proba({"sig_a": 2.0, "sig_b": 0.0})
    p_neg = learner.predict_proba({"sig_a": 0.0, "sig_b": 0.0})
    assert p_pos > p_neg, (
        f"Expected P(pos example)={p_pos:.4f} > P(neg example)={p_neg:.4f}"
    )


# ── test_fit_bias_is_negative ─────────────────────────────────────────────────

def test_fit_bias_is_negative():
    """With ~1:9 class imbalance and balanced class_weight, bias should be negative.

    With balanced weights sklearn upsamples the minority class, but the
    intercept still reflects the base rate imbalance in the feature-normalized
    space — when the minority class is small, bias < 0 is the expected result.
    """
    import random
    rng = random.Random(99)

    features = []
    labels = []
    # 5 positives (sig_a=1), 45 negatives (sig_a=0) → ~1:9 imbalance
    for _ in range(5):
        features.append({"sig_a": 1.0 + rng.gauss(0, 0.05), "sig_b": rng.gauss(0, 1)})
        labels.append(1)
    for _ in range(45):
        features.append({"sig_a": 0.0 + rng.gauss(0, 0.05), "sig_b": rng.gauss(0, 1)})
        labels.append(0)

    learner = WeightLearner(signal_names=["sig_a", "sig_b"])
    learner.fit(features, labels)

    assert learner._bias < 0, (
        f"Expected bias < 0 for 1:9 imbalance, got bias={learner._bias:.4f}"
    )


# ── test_predict_proba_without_fit_returns_base_rate ─────────────────────────

def test_predict_proba_without_fit_returns_base_rate():
    """Unfitted learner should return 0.5."""
    learner = WeightLearner()
    result = learner.predict_proba({"favorites": 1.0, "playcount": 0.5})
    assert result == 0.5, f"Expected 0.5, got {result}"


# ── test_normalization_uses_training_stats ────────────────────────────────────

def test_normalization_uses_training_stats():
    """Mean and std should be computed from the training data."""
    features = [
        {"sig_a": 10.0, "sig_b": 0.0},
        {"sig_a": 20.0, "sig_b": 0.0},
        {"sig_a": 30.0, "sig_b": 0.0},
    ]
    labels = [1, 0, 1]

    learner = WeightLearner(signal_names=["sig_a", "sig_b"])
    learner.fit(features, labels)

    expected_mean_a = 20.0
    expected_std_a = math.sqrt(((10 - 20) ** 2 + (20 - 20) ** 2 + (30 - 20) ** 2) / 3)

    assert abs(learner._mean[0] - expected_mean_a) < 1e-9, (
        f"mean[sig_a] = {learner._mean[0]}, expected {expected_mean_a}"
    )
    assert abs(learner._std[0] - expected_std_a) < 1e-6, (
        f"std[sig_a] = {learner._std[0]}, expected {expected_std_a}"
    )


# ── test_save_load_roundtrip ──────────────────────────────────────────────────

def test_save_load_roundtrip():
    """Predictions should match before and after save/load across multiple inputs."""
    learner = _fit_two_signal(n_pos=15, n_neg=15)

    test_inputs = [
        {"sig_a": 0.0, "sig_b": 0.0},
        {"sig_a": 1.0, "sig_b": 0.5},
        {"sig_a": -0.5, "sig_b": 2.0},
        {"sig_a": 5.0, "sig_b": -1.0},
        {"sig_a": 0.1, "sig_b": 0.1},
    ]

    proba_before = [learner.predict_proba(fd) for fd in test_inputs]

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        learner.save(tmp_path)
        loaded = WeightLearner.load(tmp_path)

        proba_after = [loaded.predict_proba(fd) for fd in test_inputs]

        for i, (before, after) in enumerate(zip(proba_before, proba_after)):
            assert abs(before - after) < 1e-9, (
                f"Input {i}: predict_proba before={before:.6f}, after={after:.6f}"
            )
    finally:
        import os
        os.unlink(tmp_path)


def test_save_load_schema_version():
    """Saved file should have schema_version=1."""
    learner = _fit_two_signal()

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as tmp:
        tmp_path = tmp.name

    try:
        learner.save(tmp_path)
        with open(tmp_path) as fh:
            payload = json.load(fh)
        assert payload["schema_version"] == 1
    finally:
        import os
        os.unlink(tmp_path)


def test_load_wrong_schema_version_raises():
    """Loading a file with unknown schema_version should raise ValueError."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as tmp:
        json.dump({"schema_version": 99, "signal_names": [], "weights": [],
                   "bias": 0.0, "mean": [], "std": []}, tmp)
        tmp_path = tmp.name

    try:
        with pytest.raises(ValueError, match="schema_version"):
            WeightLearner.load(tmp_path)
    finally:
        import os
        os.unlink(tmp_path)


# ── test_predict_proba_range_of_inputs ────────────────────────────────────────

def test_predict_proba_range_of_inputs():
    """Verify load/save roundtrip preserves predictions across a wide range of inputs."""
    learner = _fit_two_signal(n_pos=20, n_neg=20)

    # Stress test with extreme and typical values
    test_inputs = [
        {"sig_a": -100.0, "sig_b": -100.0},
        {"sig_a": -1.0, "sig_b": 0.0},
        {"sig_a": 0.0, "sig_b": 0.0},
        {"sig_a": 0.5, "sig_b": 0.5},
        {"sig_a": 1.0, "sig_b": 0.0},
        {"sig_a": 2.0, "sig_b": 1.0},
        {"sig_a": 100.0, "sig_b": 100.0},
    ]

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        learner.save(tmp_path)
        loaded = WeightLearner.load(tmp_path)

        for fd in test_inputs:
            p_orig = learner.predict_proba(fd)
            p_loaded = loaded.predict_proba(fd)
            assert abs(p_orig - p_loaded) < 1e-9, (
                f"Mismatch for {fd}: orig={p_orig:.8f}, loaded={p_loaded:.8f}"
            )

        # Probabilities are in [0, 1]
        for fd in test_inputs:
            p = learner.predict_proba(fd)
            assert 0.0 <= p <= 1.0, f"predict_proba out of range: {p} for {fd}"

        # High sig_a → higher probability than low sig_a
        p_high = learner.predict_proba({"sig_a": 5.0, "sig_b": 0.0})
        p_low = learner.predict_proba({"sig_a": -5.0, "sig_b": 0.0})
        assert p_high > p_low
    finally:
        import os
        os.unlink(tmp_path)


# ── test_compute_candidate_features_proximity_weighted ───────────────────────

def test_compute_candidate_features_proximity_weighted():
    """First 4 signals should be proximity-weighted sums from seed artists."""
    # Seed signal data: favorites for two seed artists
    seed_signals = {
        "favorites": {"radiohead": 3.0, "portishead": 1.5},
        "playcount": {"radiohead": 10.0, "portishead": 5.0},
        "playlists": {"radiohead": 2.0, "portishead": 0.0},
        "ratings": {"radiohead": 0.8, "portishead": 0.4},
    }

    # Candidate "thom_yorke" is 0.9 similar to radiohead, 0.3 to portishead
    proximities = {
        "radiohead": {"thom_yorke": 0.9, "burial": 0.4},
        "portishead": {"thom_yorke": 0.3, "massive_attack": 0.8},
    }

    # Direct signals for the candidate
    direct_signals = {
        "heavy_rotation": 1.0,
        "recommendations": 0.0,
        "lastfm_similar": 1.0,
        "lastfm_loved": 0.0,
        "ai_heuristic": 0.0,
    }

    features = compute_candidate_features(
        candidate="thom_yorke",
        seed_signals=seed_signals,
        proximities=proximities,
        direct_signals=direct_signals,
    )

    # favorites: 3.0*0.9 + 1.5*0.3 = 2.7 + 0.45 = 3.15
    assert abs(features["favorites"] - 3.15) < 1e-9, (
        f"favorites: expected 3.15, got {features['favorites']}"
    )

    # playcount: 10.0*0.9 + 5.0*0.3 = 9.0 + 1.5 = 10.5
    assert abs(features["playcount"] - 10.5) < 1e-9, (
        f"playcount: expected 10.5, got {features['playcount']}"
    )

    # playlists: 2.0*0.9 + 0.0*0.3 = 1.8
    assert abs(features["playlists"] - 1.8) < 1e-9, (
        f"playlists: expected 1.8, got {features['playlists']}"
    )

    # ratings: 0.8*0.9 + 0.4*0.3 = 0.72 + 0.12 = 0.84
    assert abs(features["ratings"] - 0.84) < 1e-9, (
        f"ratings: expected 0.84, got {features['ratings']}"
    )

    # Direct signal
    assert features["heavy_rotation"] == 1.0
    assert features["recommendations"] == 0.0


def test_compute_candidate_features_missing_proximity():
    """Candidate not in proximity dict should yield 0 for aggregate signals."""
    seed_signals = {
        "favorites": {"radiohead": 3.0},
        "playcount": {"radiohead": 10.0},
        "playlists": {},
        "ratings": {},
    }
    proximities = {"radiohead": {"burial": 0.5}}  # thom_yorke absent
    direct_signals = {}

    features = compute_candidate_features(
        candidate="thom_yorke",
        seed_signals=seed_signals,
        proximities=proximities,
        direct_signals=direct_signals,
    )

    for sig in SEED_AGGREGATE_SIGNALS:
        assert features[sig] == 0.0, f"{sig} should be 0.0 for missing candidate"


def test_compute_candidate_features_custom_signal_names():
    """Only requested signals appear in the output dict."""
    features = compute_candidate_features(
        candidate="burial",
        seed_signals={"favorites": {"radiohead": 1.0}},
        proximities={"radiohead": {"burial": 0.7}},
        direct_signals={"heavy_rotation": 1.0},
        signal_names=["favorites", "heavy_rotation"],
    )

    assert set(features.keys()) == {"favorites", "heavy_rotation"}
    assert abs(features["favorites"] - 0.7) < 1e-9


# ── test_dynamic_signal_names ─────────────────────────────────────────────────

def test_dynamic_signal_names():
    """WeightLearner with a custom signal list should work correctly end-to-end."""
    # lastfm_loved excluded (as would happen when Last.fm username is not configured)
    custom_signals = [s for s in ALL_SIGNAL_NAMES if s != "lastfm_loved"]

    import random
    rng = random.Random(55)

    features = []
    labels = []
    for _ in range(10):
        fd = {s: rng.random() for s in custom_signals}
        fd["favorites"] += 1.0  # Make favorites predictive for positives
        features.append(fd)
        labels.append(1)
    for _ in range(10):
        fd = {s: rng.random() * 0.1 for s in custom_signals}
        features.append(fd)
        labels.append(0)

    learner = WeightLearner(signal_names=custom_signals)
    learner.fit(features, labels)

    assert "lastfm_loved" not in learner.signal_names
    assert len(learner._weights) == len(custom_signals)
    assert learner._fitted

    # predict_proba works and returns valid probability
    p = learner.predict_proba({s: 0.5 for s in custom_signals})
    assert 0.0 <= p <= 1.0


def test_dynamic_signal_names_preserved_after_save_load():
    """Custom signal names should be preserved through save/load."""
    custom_signals = ["favorites", "playcount", "heavy_rotation"]

    import random
    rng = random.Random(77)

    features = [
        {s: rng.random() for s in custom_signals}
        for _ in range(20)
    ]
    labels = [1 if i < 10 else 0 for i in range(20)]

    learner = WeightLearner(signal_names=custom_signals)
    learner.fit(features, labels)

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        learner.save(tmp_path)
        loaded = WeightLearner.load(tmp_path)

        assert loaded.signal_names == custom_signals
        assert len(loaded._weights) == 3
    finally:
        import os
        os.unlink(tmp_path)


# ── test_fit_with_constant_feature_column ─────────────────────────────────────

def test_fit_with_constant_feature_column():
    """A constant feature column (std=0) should not cause division by zero."""
    import random
    rng = random.Random(42)

    features = [
        {"sig_a": rng.gauss(0, 1), "sig_const": 5.0}  # sig_const is constant
        for _ in range(20)
    ]
    labels = [1 if i < 10 else 0 for i in range(20)]

    learner = WeightLearner(signal_names=["sig_a", "sig_const"])
    # Should not raise ZeroDivisionError — std is set to 1.0 for constant columns
    learner.fit(features, labels)
    assert learner._fitted


# ── test_predict_proba_output_range ──────────────────────────────────────────

def test_predict_proba_output_range():
    """predict_proba should always return a value in [0, 1]."""
    learner = _fit_two_signal(n_pos=10, n_neg=10)

    extreme_inputs = [
        {"sig_a": 1e6, "sig_b": 1e6},
        {"sig_a": -1e6, "sig_b": -1e6},
        {"sig_a": 0.0, "sig_b": 0.0},
    ]
    for fd in extreme_inputs:
        p = learner.predict_proba(fd)
        assert 0.0 <= p <= 1.0, f"predict_proba={p} out of [0,1] for {fd}"
