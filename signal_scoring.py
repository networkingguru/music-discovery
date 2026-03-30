# signal_scoring.py
"""
Multi-signal scoring for the wargaming experiment.

Computes composite seed weights from multiple preference signals
and scores candidates using the weighted similarity formula.
"""

import math
import logging

log = logging.getLogger("signal_scoring")

CONTINUOUS_SIGNALS = ("favorites", "playcount", "playlists")
RATINGS_SIGNAL = "ratings"
BINARY_SIGNALS = ("heavy_rotation", "recommendations")
ALL_SIGNALS = CONTINUOUS_SIGNALS + (RATINGS_SIGNAL,) + BINARY_SIGNALS
DEFAULT_WEIGHTS = {s: 0.0 for s in ALL_SIGNALS}


def compute_signal_value(raw_count, cap=None):
    """Compute logarithmically scaled signal value.
    Formula: sqrt(log(min(raw_count, cap) + 1))
    Returns 0.0 for zero input.
    """
    if raw_count <= 0:
        return 0.0
    if cap is not None and raw_count > cap:
        raw_count = cap
    return math.sqrt(math.log(raw_count + 1))


def compute_seed_weight(artist, signals, weights, caps=None):
    """Compute composite seed weight for a library artist."""
    if caps is None:
        caps = {}
    total = 0.0
    for sig in CONTINUOUS_SIGNALS:
        w = weights.get(sig, 0.0)
        if w == 0.0:
            continue
        raw = signals.get(sig, {}).get(artist, 0)
        total += w * compute_signal_value(raw, cap=caps.get(sig))
    # Ratings: special continuous signal that allows negative values
    w = weights.get(RATINGS_SIGNAL, 0.0)
    if w != 0.0:
        rating_data = signals.get(RATINGS_SIGNAL, {}).get(artist)
        if rating_data is not None:
            avg = rating_data["avg_centered"]
            count = rating_data["count"]
            total += w * avg * math.sqrt(math.log(count + 1))
    for sig in BINARY_SIGNALS:
        w = weights.get(sig, 0.0)
        if w == 0.0:
            continue
        if artist in signals.get(sig, set()):
            total += w
    return total


NEGATIVE_PENALTY = 0.4


def score_candidates_multisignal(cache, signals, weights, *,
                                  apple_cache=None, apple_weight=0.2,
                                  blocklist_cache=None, neg_penalty=NEGATIVE_PENALTY,
                                  user_blocklist=None, caps=None):
    """Score candidates using multi-signal seed weights.

    Positive (music-map):
        score(C) += seed_weight(L) * proximity(L, C)

    Positive (Apple Music, add-if-absent):
        score(C) += apple_weight  (flat, only if C not in music-map for that seed)

    Negative (rejected discovery artists):
        score(C) -= neg_penalty * proximity(B, C)
    """
    if apple_cache is None:
        apple_cache = {}
    if blocklist_cache is None:
        blocklist_cache = {}
    if user_blocklist is None:
        user_blocklist = set()

    library_set = set(cache.keys())
    exclude = library_set | user_blocklist
    scores = {}

    # Scoring from music-map (positive or negative based on seed weight)
    for lib_artist, similar in cache.items():
        if not isinstance(similar, dict):
            continue
        weight = compute_seed_weight(lib_artist, signals, weights, caps=caps)
        if weight == 0:
            continue
        for candidate, proximity in similar.items():
            if candidate not in exclude:
                scores[candidate] = scores.get(candidate, 0.0) + weight * proximity

    # Positive scoring from Apple Music (add-if-absent)
    if apple_weight > 0:
        for lib_artist, apple_similar in apple_cache.items():
            if lib_artist not in library_set:
                continue
            weight = compute_seed_weight(lib_artist, signals, weights, caps=caps)
            if weight <= 0:
                continue
            musicmap_similar = cache.get(lib_artist, {})
            for candidate in apple_similar:
                candidate_lower = candidate.lower()
                if candidate_lower not in exclude and candidate_lower not in musicmap_similar:
                    scores[candidate_lower] = scores.get(candidate_lower, 0.0) + apple_weight

    # Negative scoring from rejected discovery artists
    if neg_penalty > 0:
        for bl_artist, similar in blocklist_cache.items():
            if not isinstance(similar, dict):
                continue
            for candidate, proximity in similar.items():
                if candidate not in exclude:
                    scores[candidate] = scores.get(candidate, 0.0) - neg_penalty * proximity

    return sorted(((v, k) for k, v in scores.items()),
                  key=lambda x: x[0], reverse=True)
