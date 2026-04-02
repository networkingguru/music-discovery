# weight_learner.py
"""
Weight learner for adaptive music discovery.

Trains an L2-regularized logistic regression model that learns which signals
predict whether a user will like a discovery artist. Trained on accumulated
feedback data (favorites vs non-favorites).

Inference uses a direct sigmoid computation from stored weights and bias,
without requiring sklearn at prediction time.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

log = logging.getLogger("weight_learner")

# ── Signal name constants ──────────────────────────────────────────────────────

SEED_AGGREGATE_SIGNALS: Tuple[str, ...] = (
    "favorites",
    "playcount",
    "playlists",
    "ratings",
)

DIRECT_SIGNALS: Tuple[str, ...] = (
    "heavy_rotation",
    "recommendations",
    "lastfm_similar",
    "lastfm_loved",
    "ai_heuristic",
)

ALL_SIGNAL_NAMES: Tuple[str, ...] = SEED_AGGREGATE_SIGNALS + DIRECT_SIGNALS

_SCHEMA_VERSION = 1


# ── Standalone feature computation ────────────────────────────────────────────

def compute_candidate_features(
    candidate: str,
    seed_signals: Dict[str, Dict[str, float]],
    proximities: Dict[str, Dict[str, float]],
    direct_signals: Dict[str, float],
    signal_names: Optional[Sequence[str]] = None,
) -> Dict[str, float]:
    """Compute a feature dict for a candidate artist.

    The first 4 signals (favorites, playcount, playlists, ratings) are
    proximity-weighted aggregates:
        feature[s] = sum over seed artists S of: seed_signals[s][S] * proximity[S][candidate]

    Remaining signals are direct per-candidate values read from *direct_signals*.

    Args:
        candidate: Lowercase artist name to compute features for.
        seed_signals: {signal_name: {seed_artist: float_value}} for the 4 aggregate signals.
        proximities: {seed_artist: {candidate_artist: proximity_weight}} from similarity graph.
        direct_signals: {signal_name: float_value} for per-candidate direct signals.
        signal_names: Which signals to include. Defaults to ALL_SIGNAL_NAMES.

    Returns:
        {signal_name: float_value}
    """
    if signal_names is None:
        signal_names = ALL_SIGNAL_NAMES

    features: Dict[str, float] = {}

    for sig in signal_names:
        if sig in SEED_AGGREGATE_SIGNALS:
            # Proximity-weighted sum across seed artists
            total = 0.0
            sig_data = seed_signals.get(sig, {})
            for seed_artist, seed_val in sig_data.items():
                prox = proximities.get(seed_artist, {}).get(candidate, 0.0)
                total += seed_val * prox
            features[sig] = total
        else:
            # Direct per-candidate value
            features[sig] = float(direct_signals.get(sig, 0.0))

    return features


# ── WeightLearner ──────────────────────────────────────────────────────────────

class WeightLearner:
    """L2-regularized logistic regression for discovery signal weighting.

    Train with fit(), then use predict_proba() for inference. Predictions use a
    direct sigmoid computation from stored weights and bias — no sklearn required
    at inference time.

    Normalization stats are computed from the full training set and stored
    alongside weights for consistent inference after save/load.
    """

    def __init__(self, signal_names: Optional[Sequence[str]] = None) -> None:
        """Initialize the learner.

        Args:
            signal_names: Which signals to use as features. When Last.fm username
                is not configured, exclude 'lastfm_loved' from this list. Defaults
                to ALL_SIGNAL_NAMES.
        """
        self.signal_names: List[str] = list(
            signal_names if signal_names is not None else ALL_SIGNAL_NAMES
        )
        self._weights: List[float] = []
        self._bias: float = 0.0
        self._mean: List[float] = []
        self._std: List[float] = []
        self._fitted: bool = False

    # ── Training ──────────────────────────────────────────────────────────────

    def fit(
        self,
        feature_dicts: List[Dict[str, float]],
        labels: List[int],
    ) -> "WeightLearner":
        """Fit the model on accumulated feedback data.

        Computes normalization stats (mean/std) from the full training set,
        normalizes features, then fits L2 logistic regression via sklearn.
        Extracts weights and bias for direct sigmoid inference.

        Args:
            feature_dicts: List of {signal_name: float_value} feature dicts,
                one per training example.
            labels: Binary labels (1 = favorite, 0 = non-favorite) per example.

        Returns:
            self (for method chaining)
        """
        if not feature_dicts:
            raise ValueError("fit() requires at least one training example")
        if len(feature_dicts) != len(labels):
            raise ValueError("feature_dicts and labels must have the same length")

        try:
            from sklearn.linear_model import LogisticRegression
        except ImportError as exc:
            raise ImportError(
                "scikit-learn is required for fit(). Install it with: "
                "pip install scikit-learn"
            ) from exc

        n = len(self.signal_names)
        m = len(feature_dicts)

        # Build raw feature matrix: shape (m, n)
        X_raw = [
            [fd.get(sig, 0.0) for sig in self.signal_names]
            for fd in feature_dicts
        ]

        # Compute mean and std from training data
        means = []
        stds = []
        for col_idx in range(n):
            col = [X_raw[row_idx][col_idx] for row_idx in range(m)]
            mu = sum(col) / m
            variance = sum((v - mu) ** 2 for v in col) / m
            sigma = math.sqrt(variance) if variance > 0 else 1.0
            means.append(mu)
            stds.append(sigma)

        self._mean = means
        self._std = stds

        # Normalize features
        X_norm = [
            [(X_raw[row][col] - means[col]) / stds[col] for col in range(n)]
            for row in range(m)
        ]

        # Fit L2 logistic regression with balanced class weights
        # penalty='l2' deprecated in sklearn 1.8+; use l1_ratio=0 for L2 behaviour.
        # Fallback to keyword for older sklearn versions.
        try:
            clf = LogisticRegression(
                l1_ratio=0,
                class_weight="balanced",
                max_iter=1000,
                solver="lbfgs",
                random_state=42,
            )
        except TypeError:
            # sklearn < 1.8 does not accept l1_ratio without elasticnet solver
            clf = LogisticRegression(
                penalty="l2",
                class_weight="balanced",
                max_iter=1000,
                solver="lbfgs",
                random_state=42,
            )
        clf.fit(X_norm, labels)

        # Extract weights and bias (coef_ is shape (1, n) for binary classification)
        self._weights = list(map(float, clf.coef_[0]))
        self._bias = float(clf.intercept_[0])
        self._fitted = True

        log.debug(
            "WeightLearner fit: %d examples, %d signals, bias=%.4f",
            m, n, self._bias,
        )
        return self

    # ── Inference ─────────────────────────────────────────────────────────────

    def predict_proba(self, feature_dict: Dict[str, float]) -> float:
        """Return P(favorite) for a candidate described by feature_dict.

        Uses direct sigmoid computation:
            p = 1 / (1 + exp(-(bias + sum(w[i] * normalized_x[i]))))

        Returns 0.5 if the model has not been fitted.

        Args:
            feature_dict: {signal_name: float_value} for the candidate.

        Returns:
            Probability in [0, 1] that this candidate will be a favorite.
        """
        if not self._fitted:
            return 0.5

        # Normalize using training stats
        logit = self._bias
        for i, sig in enumerate(self.signal_names):
            raw = float(feature_dict.get(sig, 0.0))
            norm = (raw - self._mean[i]) / self._std[i]
            logit += self._weights[i] * norm

        # Sigmoid
        try:
            return 1.0 / (1.0 + math.exp(-logit))
        except OverflowError:
            return 0.0 if logit < 0 else 1.0

    # ── Persistence ──────────────────────────────────────────────────────────

    def save(self, path: str | Path) -> None:
        """Persist model weights, bias, and normalization stats to JSON.

        Args:
            path: File path to write. Parent directories are created if needed.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "signal_names": self.signal_names,
            "weights": self._weights,
            "bias": self._bias,
            "mean": self._mean,
            "std": self._std,
            "fitted": self._fitted,
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        log.debug("Saved WeightLearner to %s", path)

    @classmethod
    def load(cls, path: str | Path) -> "WeightLearner":
        """Load a previously saved model from JSON.

        Restores weights, bias, normalization stats, and signal names.
        Does NOT reconstruct an sklearn model — predict_proba() works
        from stored weights alone.

        Args:
            path: File path to read.

        Returns:
            A WeightLearner instance ready for predict_proba().

        Raises:
            FileNotFoundError: If path does not exist.
            ValueError: If schema_version is unrecognised.
        """
        path = Path(path)
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)

        version = payload.get("schema_version")
        if version != _SCHEMA_VERSION:
            raise ValueError(
                f"Unknown WeightLearner schema_version {version!r}; expected {_SCHEMA_VERSION}"
            )

        learner = cls(signal_names=payload["signal_names"])
        learner._weights = [float(w) for w in payload["weights"]]
        learner._bias = float(payload["bias"])
        learner._mean = [float(v) for v in payload["mean"]]
        learner._std = [float(v) for v in payload["std"]]
        learner._fitted = bool(payload.get("fitted", True))

        log.debug("Loaded WeightLearner from %s", path)
        return learner
