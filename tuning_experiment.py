#!/usr/bin/env python3
"""
Tuning experiment: compare scoring variants across Apple Music weight
and negative scoring penalty dimensions.

Generates a 4x4 matrix of ranked candidate lists and a movement report.
"""

import argparse
import json
import logging
import math
import os
import sys
import pathlib
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from music_discovery import (
    _build_paths, load_dotenv, load_cache,
    load_user_blocklist,
    filter_candidates, parse_library_jxa,
)
from compare_similarity import (
    generate_apple_music_token, AppleMusicClient,
)

log = logging.getLogger("tuning")

APPLE_WEIGHTS = [0.0, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5]
NEG_PENALTIES = [0.0, 0.2, 0.4, 0.8]
SELECTED_APPLE_WEIGHT = 0.2
TOP_N = 25
OUTPUT_DIR = pathlib.Path(__file__).parent


def prefetch_apple_data(client, library_artists, cache_path):
    """Fetch similar artists from Apple Music API for all library artists.

    Loads existing cache, fetches missing artists, saves updated cache.
    Returns {artist: [similar_artist_lowercase, ...]} dict.
    """
    # Load existing cache
    if cache_path.exists():
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)
    else:
        cache = {}

    to_fetch = [a for a in library_artists if a not in cache]
    if to_fetch:
        log.info(f"Fetching Apple Music data for {len(to_fetch)} artists "
                 f"({len(cache)} already cached)...")

    for i, artist in enumerate(to_fetch, 1):
        artist_id, matched_name = client.search_artist(artist)
        if artist_id is None:
            log.warning(f"  [{i}/{len(to_fetch)}] {artist} — not found on Apple Music")
            continue
        similar = client.get_similar_artists(artist_id)
        cache[artist] = [s["name"].lower() for s in similar]
        log.info(f"  [{i}/{len(to_fetch)}] {artist} → {len(similar)} similar artists")
        if i < len(to_fetch):
            time.sleep(0.05)  # brief pause between API calls

    # Save updated cache
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)

    return cache


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


def generate_report(variants, top_n=TOP_N, library_count=0):
    """Generate a formatted report comparing all scoring variants.

    Args:
        variants: {(apple_weight, neg_penalty): [(score, name), ...]}
        top_n: number of artists to show per variant
        library_count: number of library artists (for header)

    Returns:
        Formatted report string.
    """
    lines = []
    lines.append("=" * 70)
    lines.append("TUNING EXPERIMENT — Scoring Variant Comparison")
    lines.append(f"Library artists: {library_count}")
    lines.append(f"Matrix: {len(APPLE_WEIGHTS)} Apple weights × {len(NEG_PENALTIES)} negative penalties = {len(variants)} variants")
    lines.append(f"Showing top {top_n} per variant")
    lines.append("=" * 70)

    # Individual variant sections
    for aw in APPLE_WEIGHTS:
        for np_ in NEG_PENALTIES:
            key = (aw, np_)
            ranked = variants.get(key, [])
            lines.append("")
            label = f"apple={aw}, neg={np_}"
            if aw == 0.0 and np_ == 0.0:
                label += "  [BASELINE]"
            lines.append(f"--- {label} ---")
            for i, (score, name) in enumerate(ranked[:top_n], 1):
                lines.append(f"  {i:>2}. {name:<35s} ({score:.2f})")
            if not ranked:
                lines.append("  (no candidates)")

    # Movement analysis vs baseline
    baseline_key = (0.0, 0.0)
    baseline_names = [name for _, name in variants.get(baseline_key, [])[:top_n]]

    lines.append("")
    lines.append("=" * 70)
    lines.append("Movement Analysis vs baseline (apple=0.0, neg=0.0)")
    lines.append("=" * 70)

    for aw in APPLE_WEIGHTS:
        for np_ in NEG_PENALTIES:
            if aw == 0.0 and np_ == 0.0:
                continue
            key = (aw, np_)
            variant_names = [name for _, name in variants.get(key, [])[:top_n]]
            entered = [n for n in variant_names if n not in baseline_names]
            exited = [n for n in baseline_names if n not in variant_names]
            if not entered and not exited:
                continue
            lines.append(f"\n  apple={aw}, neg={np_}:")
            lines.append(f"    {len(entered)} entered, {len(exited)} dropped")
            if entered:
                lines.append(f"    New:     {', '.join(entered)}")
            if exited:
                lines.append(f"    Dropped: {', '.join(exited)}")

    # Biggest movers
    lines.append("")
    lines.append("=" * 70)
    lines.append("BIGGEST MOVERS — artists with largest rank swings")
    lines.append("=" * 70)

    all_artists = set()
    for ranked in variants.values():
        for _, name in ranked[:top_n]:
            all_artists.add(name)

    rank_ranges = {}
    for artist in all_artists:
        ranks = []
        for key, ranked in variants.items():
            names = [name for _, name in ranked[:top_n]]
            if artist in names:
                ranks.append(names.index(artist) + 1)
        if len(ranks) >= 2:
            rank_ranges[artist] = (min(ranks), max(ranks), len(ranks))

    movers = sorted(rank_ranges.items(), key=lambda x: x[1][1] - x[1][0], reverse=True)
    for artist, (lo, hi, appearances) in movers[:10]:
        lines.append(f"  {artist:<35s} rank {lo}-{hi} (in {appearances}/{len(variants)} variants)")

    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Tuning experiment: compare scoring variants"
    )
    parser.add_argument("--refresh-apple", action="store_true",
                        help="Re-fetch all Apple Music data (ignore cache)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    load_dotenv()
    paths = _build_paths()

    # 1. Parse library
    print("Reading library via JXA...")
    library_artists = parse_library_jxa()
    print(f"Found {len(library_artists)} artists with loved/favorited tracks.")

    # 2. Load existing caches (read-only)
    cache = load_cache(paths["cache"])
    filter_cache_data = load_cache(paths["filter_cache"])
    user_blocklist_path = pathlib.Path(__file__).parent / "blocklist.txt"
    user_blocklist = load_user_blocklist(user_blocklist_path)
    bl_cache = load_cache(paths["blocklist_scrape"])

    # 3. Prefetch Apple Music data
    apple_cache_path = paths["cache"].parent / "apple_music_cache.json"
    if args.refresh_apple and apple_cache_path.exists():
        apple_cache_path.unlink()

    key_id = os.environ.get("APPLE_MUSIC_KEY_ID", "")
    team_id = os.environ.get("APPLE_MUSIC_TEAM_ID", "")
    key_path = os.environ.get("APPLE_MUSIC_KEY_PATH", "")

    if key_id and team_id and key_path:
        print("\nGenerating Apple Music API token...")
        token = generate_apple_music_token(key_id, team_id, key_path)
        client = AppleMusicClient(token)
        print("Prefetching Apple Music similar artists...")
        apple_cache = prefetch_apple_data(client, library_artists, apple_cache_path)
        print(f"Apple Music cache: {len(apple_cache)} artists.")
    else:
        print("\nApple Music API credentials not configured. "
              "Apple weight variants will use empty data.")
        apple_cache = {}

    # 4. Run all scoring variants
    print(f"\nRunning {len(APPLE_WEIGHTS) * len(NEG_PENALTIES)} scoring variants...")
    variants = {}
    for aw in APPLE_WEIGHTS:
        for np_ in NEG_PENALTIES:
            scored = score_artists_tunable(
                cache, library_artists,
                apple_cache=apple_cache,
                blocklist_cache=bl_cache,
                user_blocklist=user_blocklist,
                apple_weight=aw,
                neg_penalty=np_,
            )
            ranked = filter_candidates(scored, filter_cache_data, user_blocklist)
            variants[(aw, np_)] = ranked

    # 5. Generate and output report
    report = generate_report(variants, top_n=TOP_N,
                             library_count=len(library_artists))
    print(report)

    # Save to file
    out_path = OUTPUT_DIR / "tuning_results.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("```\n")
        f.write(report)
        f.write("\n```\n")
    print(f"\nSaved to: {out_path}")


if __name__ == "__main__":
    main()
