#!/usr/bin/env python3
"""
Tuning experiment: compare scoring variants across Apple Music weight
and negative scoring penalty dimensions.

Generates a 4x4 matrix of ranked candidate lists and a movement report.
"""

import math
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))


def score_artists_tunable(cache, library_artists, *, apple_cache,
                          blocklist_cache, user_blocklist,
                          apple_weight, neg_penalty):
    """Score candidates with tunable Apple weight and negative penalty.

    Positive (music-map):
        score(C) += sqrt(log(loved_count+1)) * musicmap_proximity(L, C)

    Positive (Apple Music, add-if-absent):
        score(C) += apple_weight   (flat, only if C NOT in musicmap for that seed)

    Negative (blocklist):
        score(C) -= neg_penalty * musicmap_proximity(B, C)

    Returns list of (score, artist_name) sorted descending.
    """
    library_set = set(library_artists.keys())
    exclude = library_set | user_blocklist
    scores = {}

    # Positive scoring from music-map
    for lib_artist, similar in cache.items():
        if not isinstance(similar, dict):
            continue
        weight = math.log(library_artists.get(lib_artist, 1) + 1) ** 0.5
        for candidate, proximity in similar.items():
            if candidate not in exclude:
                scores[candidate] = scores.get(candidate, 0.0) + weight * proximity

    # Positive scoring from Apple Music (add-if-absent)
    if apple_weight > 0:
        for lib_artist, apple_similar in apple_cache.items():
            if lib_artist not in library_artists:
                continue
            musicmap_similar = cache.get(lib_artist, {})
            for candidate in apple_similar:
                candidate_lower = candidate.lower()
                if candidate_lower not in exclude and candidate_lower not in musicmap_similar:
                    scores[candidate_lower] = scores.get(candidate_lower, 0.0) + apple_weight

    # Negative scoring from blocklisted artists
    if neg_penalty > 0:
        for bl_artist, similar in blocklist_cache.items():
            if not isinstance(similar, dict):
                continue
            for candidate, proximity in similar.items():
                if candidate not in exclude:
                    scores[candidate] = scores.get(candidate, 0.0) - neg_penalty * proximity

    return sorted(((v, k) for k, v in scores.items()),
                  key=lambda x: x[0], reverse=True)
