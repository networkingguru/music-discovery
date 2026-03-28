#!/usr/bin/env python3
"""
Signal Wargaming Experiment

Collects all available preference signals, analyzes their individual
and combined effects on discovery rankings, and recommends weight
configurations for evaluation by listening.

Usage:
    python signal_experiment.py                  # full run
    python signal_experiment.py --skip-api       # skip API signals (no user token)
    python signal_experiment.py --refresh        # re-collect all data (ignore caches)
    python signal_experiment.py --post-listen    # score configs against new favorites
"""

import argparse
import json
import logging
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from music_discovery import (
    _build_paths, load_dotenv, load_cache, load_user_blocklist, load_blocklist,
    parse_library_jxa,
)
from compare_similarity import generate_apple_music_token, AppleMusicClient
from signal_collectors import (
    collect_playcounts_jxa, collect_user_playlists_jxa,
    collect_heavy_rotation, collect_recommendations, _make_user_session,
)
from signal_scoring import score_candidates_multisignal
from signal_analysis import run_phase_a, run_phase_b, run_phase_c, run_phase_d
from signal_report import generate_wargaming_report

log = logging.getLogger("signal_experiment")

TOP_N = 25
REPORT_FILENAME = "signal_wargaming_results.md"


def collect_all_signals(cache_dir, api_session=None, refresh=False):
    """Collect all signals, using caches where available."""
    cache_dir = pathlib.Path(cache_dir)

    log.info("Reading favorited tracks from Music.app...")
    favorites = parse_library_jxa()
    log.info(f"  {len(favorites)} artists with favorited tracks.")

    pc_cache = cache_dir / "playcount_cache.json"
    if pc_cache.exists() and not refresh:
        log.info("Loading play counts from cache...")
        playcount = json.loads(pc_cache.read_text())
    else:
        log.info("Reading play counts from Music.app...")
        playcount = collect_playcounts_jxa()
        pc_cache.write_text(json.dumps(playcount, indent=2))
        log.info(f"  {len(playcount)} artists with plays.")

    pl_cache = cache_dir / "playlist_membership_cache.json"
    if pl_cache.exists() and not refresh:
        log.info("Loading playlist membership from cache...")
        playlists = json.loads(pl_cache.read_text())
    else:
        log.info("Reading user playlists from Music.app...")
        playlists = collect_user_playlists_jxa()
        pl_cache.write_text(json.dumps(playlists, indent=2))
        log.info(f"  {len(playlists)} artists across user playlists.")

    hr_cache = cache_dir / "heavy_rotation_cache.json"
    if hr_cache.exists() and not refresh:
        log.info("Loading heavy rotation from cache...")
        heavy_rotation = set(json.loads(hr_cache.read_text()))
    elif api_session is not None:
        log.info("Fetching heavy rotation from Apple Music API...")
        heavy_rotation = collect_heavy_rotation(api_session)
        hr_cache.write_text(json.dumps(sorted(heavy_rotation), indent=2))
        log.info(f"  {len(heavy_rotation)} heavy rotation artists.")
    else:
        log.info("No API session — skipping heavy rotation.")
        heavy_rotation = set()

    rec_cache = cache_dir / "recommendations_cache.json"
    if rec_cache.exists() and not refresh:
        log.info("Loading recommendations from cache...")
        recommendations = set(json.loads(rec_cache.read_text()))
    elif api_session is not None:
        log.info("Fetching personal recommendations from Apple Music API...")
        recommendations = collect_recommendations(api_session)
        rec_cache.write_text(json.dumps(sorted(recommendations), indent=2))
        log.info(f"  {len(recommendations)} recommended artists.")
    else:
        log.info("No API session — skipping recommendations.")
        recommendations = set()

    return {
        "favorites": favorites,
        "playcount": playcount,
        "playlists": playlists,
        "heavy_rotation": heavy_rotation,
        "recommendations": recommendations,
    }


def score_post_listen(saved_recs, new_fav_artists, top_n=10):
    """Score each recommended config against the user's new favorites."""
    results = []
    for rec in saved_recs:
        top_names = [name for _, name in rec["ranked"][:top_n]]
        hits = [n for n in top_names if n in new_fav_artists]
        precision = len(hits) / len(top_names) * 100 if top_names else 0
        results.append({
            "name": rec["name"],
            "hits": len(hits),
            "precision": precision,
            "matched": hits,
        })
    return results


def run_experiment(signals, scrape_cache, apple_cache, rejected_cache,
                   user_blocklist, top_n=TOP_N,
                   filter_cache=None, file_blocklist=frozenset()):
    """Run all four analysis phases and generate the report."""
    scoring_kwargs = {
        "apple_cache": apple_cache,
        "apple_weight": 0.2,
        "blocklist_cache": rejected_cache,
        "user_blocklist": user_blocklist,
        "filter_cache": filter_cache,
        "file_blocklist": file_blocklist,
    }

    log.info("\n--- Phase A: Individual Signal Profiling ---")
    phase_a = run_phase_a(scrape_cache, signals, top_n=top_n, **scoring_kwargs)

    log.info("--- Phase B: Ablation ---")
    phase_b = run_phase_b(scrape_cache, signals, top_n=top_n, **scoring_kwargs)

    log.info("--- Phase C: Degraded Scenarios ---")
    phase_c = run_phase_c(scrape_cache, signals, top_n=top_n, **scoring_kwargs)

    log.info("--- Phase D: Recommendations ---")
    phase_d = run_phase_d(scrape_cache, signals, top_n=top_n, **scoring_kwargs)

    library_count = len(set().union(
        signals["favorites"].keys(),
        signals["playcount"].keys(),
        signals["playlists"].keys(),
    ))
    report = generate_wargaming_report(phase_a, phase_b, phase_c, phase_d,
                                        library_count=library_count, top_n=top_n)

    return report, phase_d


def get_evaluation_artists(phase_d, top_n=10, exclude=None):
    """Get the union of top-N artists from all recommended configs.

    Args:
        phase_d: list of recommendation dicts with "ranked" lists.
        top_n: how many artists per config to consider.
        exclude: set of lowercase artist names to skip (library, blocklists).

    Returns:
        sorted list of unique artist names not in exclude set.
    """
    if exclude is None:
        exclude = set()
    artists = set()
    for rec in phase_d:
        count = 0
        for _, name in rec["ranked"]:
            if name not in exclude:
                artists.add(name)
                count += 1
            if count >= top_n:
                break
    return sorted(artists)


def main():
    parser = argparse.ArgumentParser(description="Signal Wargaming Experiment")
    parser.add_argument("--skip-api", action="store_true",
                        help="Skip API signals (no user token required)")
    parser.add_argument("--refresh", action="store_true",
                        help="Re-collect all data, ignoring caches")
    parser.add_argument("--post-listen", action="store_true",
                        help="Score configs against new favorites after listening")
    parser.add_argument("--build-playlist", action="store_true",
                        help="Build evaluation playlist from recommended configs' top artists")
    parser.add_argument("--top-n", type=int, default=TOP_N,
                        help=f"Number of top artists per analysis (default: {TOP_N})")
    args = parser.parse_args()

    if args.post_listen and args.build_playlist:
        parser.error("Cannot use --post-listen and --build-playlist together")

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    load_dotenv()
    paths = _build_paths()

    api_session = None
    if not args.skip_api:
        user_token = os.environ.get("APPLE_MUSIC_USER_TOKEN")
        if user_token:
            dev_token = generate_apple_music_token(
                os.environ.get("APPLE_MUSIC_KEY_ID"),
                os.environ.get("APPLE_MUSIC_TEAM_ID"),
                os.environ.get("APPLE_MUSIC_KEY_PATH"),
            )
            api_session = _make_user_session(dev_token, user_token)
        else:
            log.info("No APPLE_MUSIC_USER_TOKEN found. Run auth_musickit.py first, "
                     "or use --skip-api.")

    cache_dir = paths["cache"].parent

    signals = collect_all_signals(cache_dir, api_session, refresh=args.refresh)

    scrape_cache = load_cache(paths["cache"])
    apple_cache_path = cache_dir / "apple_similar_cache.json"
    apple_cache = load_cache(apple_cache_path) if apple_cache_path.exists() else {}
    rejected_cache = load_cache(paths["rejected_scrape"])
    user_blocklist = load_user_blocklist(
        pathlib.Path(__file__).parent / "blocklist.txt")
    filter_cache = load_cache(paths["filter_cache"])
    file_blocklist = load_blocklist(paths["blocklist"])
    library_artists = set(signals["favorites"].keys()) | set(signals["playcount"].keys())
    eval_exclude = library_artists | user_blocklist | file_blocklist

    if args.post_listen:
        new_favorites = parse_library_jxa()
        fav_snapshot_path = cache_dir / "favorites_snapshot.json"
        if fav_snapshot_path.exists():
            old_favorites = json.loads(fav_snapshot_path.read_text())
        else:
            log.error("No favorites snapshot found. Run the experiment first.")
            sys.exit(1)
        new_fav_artists = set(new_favorites.keys()) - set(old_favorites.keys())
        log.info(f"\nNew favorites since last run: {len(new_fav_artists)} artists")
        if new_fav_artists:
            log.info(f"  {', '.join(sorted(new_fav_artists))}")

        recs_path = cache_dir / "signal_wargaming_recs.json"
        if not recs_path.exists():
            log.error("No saved recommendations found. Run the experiment first.")
            sys.exit(1)
        saved_recs = json.loads(recs_path.read_text())

        results = score_post_listen(saved_recs, new_fav_artists)
        log.info("\n=== Post-Listen Scoring ===\n")
        for r in results:
            log.info(f"{r['name']}:")
            log.info(f"  Hits: {r['hits']}/10 ({r['precision']:.0f}% precision)")
            if r["matched"]:
                log.info(f"  Matched: {', '.join(r['matched'])}")
        return

    if args.build_playlist:
        recs_path = cache_dir / "signal_wargaming_recs.json"
        if not recs_path.exists():
            log.error("No saved recommendations found. Run the experiment first.")
            sys.exit(1)
        saved_recs = json.loads(recs_path.read_text())
        eval_artists = get_evaluation_artists(saved_recs, top_n=10, exclude=eval_exclude)
        log.info(f"\nBuilding evaluation playlist with {len(eval_artists)} artists...")

        from music_discovery import (
            setup_playlist, search_itunes, add_track_to_playlist,
            fetch_top_tracks, RATE_LIMIT,
        )
        import time

        if not setup_playlist():
            log.error("Could not create playlist — aborting.")
            sys.exit(1)

        api_key = os.environ.get("LASTFM_API_KEY")
        added = 0
        for i, artist in enumerate(eval_artists, 1):
            log.info(f"[{i}/{len(eval_artists)}] {artist}")
            tracks = fetch_top_tracks(artist, api_key) if api_key else []
            artist_added = 0
            for track in tracks[:3]:
                track_id = search_itunes(artist, track["name"])
                if track_id:
                    if add_track_to_playlist(artist, track["name"]):
                        artist_added += 1
                        added += 1
                if artist_added >= 2:
                    break
            time.sleep(RATE_LIMIT)

        log.info(f"\nEvaluation playlist built: {added} tracks from {len(eval_artists)} artists.")
        log.info("Listen, favorite what you like, then run:")
        log.info("  python signal_experiment.py --post-listen")
        return

    report, phase_d = run_experiment(
        signals, scrape_cache, apple_cache, rejected_cache,
        user_blocklist, top_n=args.top_n,
        filter_cache=filter_cache, file_blocklist=file_blocklist)

    report_path = pathlib.Path(__file__).parent / REPORT_FILENAME
    report_path.write_text(report)
    log.info(f"\nReport saved to: {report_path}")

    fav_snapshot_path = cache_dir / "favorites_snapshot.json"
    fav_snapshot_path.write_text(json.dumps(signals["favorites"], indent=2))

    recs_path = cache_dir / "signal_wargaming_recs.json"
    serializable_recs = []
    for rec in phase_d:
        serializable_recs.append({
            "name": rec["name"],
            "rationale": rec["rationale"],
            "weights": rec["weights"],
            "ranked": rec["ranked"][:25],
            "baseline_diff": rec["baseline_diff"],
        })
    recs_path.write_text(json.dumps(serializable_recs, indent=2))

    eval_artists = get_evaluation_artists(phase_d, top_n=10, exclude=eval_exclude)
    log.info(f"\n=== Evaluation Playlist Artists ({len(eval_artists)}) ===")
    for a in eval_artists:
        log.info(f"  {a}")
    log.info(f"\nTo build the evaluation playlist, run:")
    log.info(f"  python signal_experiment.py --build-playlist")
    log.info(f"\nAfter listening and favoriting, run:")
    log.info(f"  python signal_experiment.py --post-listen")


if __name__ == "__main__":
    main()
