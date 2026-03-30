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
    collect_ratings_jxa,
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

    rat_cache = cache_dir / "ratings_cache.json"
    if rat_cache.exists() and not refresh:
        log.info("Loading ratings from cache...")
        ratings = json.loads(rat_cache.read_text())
    else:
        log.info("Reading star ratings from Music.app...")
        ratings = collect_ratings_jxa()
        rat_cache.write_text(json.dumps(ratings, indent=2))
        log.info(f"  {len(ratings)} artists with ratings.")

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
        "ratings": ratings,
        "heavy_rotation": heavy_rotation,
        "recommendations": recommendations,
    }


def score_post_listen(saved_recs, new_fav_artists, top_n=80):
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


def build_stratified_artist_list(phase_a, phase_d, target_total=105,
                                  exclude=None, prior_artists=None):
    """Build a stratified artist list for the eval playlist.

    Stratum 1: Equal slots per signal from Phase A solo rankings (~75%).
    Stratum 2: Remaining slots from Phase D blended configs (round-robin).

    Returns list of {"name": str, "stratum": str, "rank": int}
    """
    if exclude is None:
        exclude = set()
    if prior_artists is None:
        prior_artists = set()
    skip = exclude | prior_artists
    used = set()
    result = []

    # Stratum 1: signal-fair solo slots
    signals = list(phase_a.keys())
    n_signals = len(signals)
    stratum1_total = int(target_total * 0.75)
    per_signal = stratum1_total // n_signals

    signal_iters = {}
    for sig in signals:
        ranked = phase_a[sig].get("ranked", [])
        signal_iters[sig] = iter(
            (rank, name) for rank, (_, name) in enumerate(ranked, 1)
            if name not in skip
        )

    signal_counts = {sig: 0 for sig in signals}
    filled = True
    while filled:
        filled = False
        for sig in signals:
            if signal_counts[sig] >= per_signal:
                continue
            for rank, name in signal_iters[sig]:
                if name not in used:
                    result.append({"name": name, "stratum": f"solo:{sig}", "rank": rank})
                    used.add(name)
                    signal_counts[sig] += 1
                    filled = True
                    break

    # Stratum 2: blended config slots (round-robin)
    if phase_d and len(result) < target_total:
        config_iters = []
        for rec in phase_d:
            config_iters.append((
                rec["name"],
                iter(
                    (rank, name) for rank, (_, name) in enumerate(rec["ranked"], 1)
                    if name not in skip
                ),
            ))
        added = True
        while len(result) < target_total and added:
            added = False
            for config_name, it in config_iters:
                if len(result) >= target_total:
                    break
                for rank, name in it:
                    if name not in used:
                        result.append({
                            "name": name,
                            "stratum": f"blend:{config_name}",
                            "rank": rank,
                        })
                        used.add(name)
                        added = True
                        break

    return result


def load_manifest(path):
    """Load eval playlist manifest, or return empty structure."""
    path = pathlib.Path(path)
    if path.exists():
        return json.loads(path.read_text())
    return {"sessions": []}


def get_prior_artists(manifest):
    """Extract all artist names from prior manifest sessions."""
    artists = set()
    for session in manifest.get("sessions", []):
        for entry in session.get("artists", []):
            artists.add(entry["name"])
    return artists


def save_manifest_session(path, manifest, artists):
    """Append a new session to the manifest and write to disk."""
    import datetime
    session_id = len(manifest.get("sessions", [])) + 1
    manifest["sessions"].append({
        "date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "session_id": session_id,
        "artists": artists,
    })
    pathlib.Path(path).write_text(json.dumps(manifest, indent=2))


def load_post_listen_history(path):
    """Load post-listen history, or return empty structure."""
    path = pathlib.Path(path)
    if path.exists():
        return json.loads(path.read_text())
    return {"rounds": [], "cumulative": {}}


def accumulate_post_listen_round(history, round_data):
    """Add a round's results to the cumulative history."""
    import datetime
    round_entry = {"date": datetime.datetime.now().strftime("%Y-%m-%d"), **round_data}
    history["rounds"].append(round_entry)
    cum = history.get("cumulative", {})
    cum["total_new_favorites"] = cum.get("total_new_favorites", 0) + len(round_data["new_favorites"])
    cum_config = cum.get("per_config", {})
    for config_name, data in round_data.get("per_config_hits", {}).items():
        if config_name not in cum_config:
            cum_config[config_name] = {"hits": 0, "pool_size": 0}
        cum_config[config_name]["hits"] += data["hits"]
        cum_config[config_name]["pool_size"] += data["pool_size"]
    cum["per_config"] = cum_config
    cum_solo = cum.get("per_signal_solo", {})
    for sig, data in round_data.get("per_signal_solo_hits", {}).items():
        if sig not in cum_solo:
            cum_solo[sig] = {"hits": 0, "pool_size": 0}
        cum_solo[sig]["hits"] += data["hits"]
        cum_solo[sig]["pool_size"] += data["pool_size"]
    cum["per_signal_solo"] = cum_solo
    history["cumulative"] = cum
    return history


def run_statistical_test(cumulative, min_n=30):
    """Run Fisher's exact test on cumulative config hit rates.
    Returns None if total_new_favorites < min_n.
    Returns {"best_config", "p_value", "significant", "all_rates"} otherwise.
    """
    if cumulative.get("total_new_favorites", 0) < min_n:
        return None
    from scipy.stats import fisher_exact
    configs = cumulative.get("per_config", {})
    if len(configs) < 2:
        return None
    sorted_configs = sorted(configs.items(),
                            key=lambda x: x[1]["hits"] / x[1]["pool_size"] if x[1]["pool_size"] > 0 else 0,
                            reverse=True)
    best_name = sorted_configs[0][0]
    best = sorted_configs[0][1]
    second = sorted_configs[1][1]
    table = [
        [best["hits"], best["pool_size"] - best["hits"]],
        [second["hits"], second["pool_size"] - second["hits"]],
    ]
    _, p_value = fisher_exact(table)
    p_value = float(p_value)
    return {
        "best_config": best_name,
        "p_value": p_value,
        "significant": bool(p_value < 0.05),
        "all_rates": {
            name: {"rate": data["hits"] / data["pool_size"] * 100 if data["pool_size"] > 0 else 0,
                   "hits": data["hits"], "pool_size": data["pool_size"]}
            for name, data in configs.items()
        },
    }


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

    return report, phase_a, phase_d


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


def _setup_named_playlist(name):
    """Create or reset a named playlist. Returns True on success."""
    from music_discovery import _run_applescript
    safe_name = name.replace('"', '\\"')
    count_script = f'''
tell application "Music"
    if (exists user playlist "{safe_name}") then
        return count of tracks of user playlist "{safe_name}"
    else
        return -1
    end if
end tell
'''
    out, code = _run_applescript(count_script)
    if code != 0:
        return False
    try:
        track_count = int(out)
    except ValueError:
        return False

    if track_count == -1:
        _, code = _run_applescript(f'''
tell application "Music"
    make new user playlist with properties {{name:"{safe_name}"}}
end tell
''')
        return code == 0

    if track_count > 0:
        import time
        log.info(f"Existing playlist '{name}' has {track_count} tracks — deleting and recreating.")
        _, code = _run_applescript(f'''
tell application "Music"
    delete user playlist "{safe_name}"
end tell
''')
        if code != 0:
            return False
        time.sleep(1)
        _, code = _run_applescript(f'''
tell application "Music"
    make new user playlist with properties {{name:"{safe_name}"}}
end tell
''')
        return code == 0

    return True


def _add_track_to_named_playlist(artist, track_name, playlist_name):
    """Search Apple Music for a track and add it to a named playlist.
    Returns True if added, False if not found."""
    from music_discovery import (
        search_itunes, _run_applescript, _run_jxa, _play_store_track,
        _applescript_escape,
    )
    import time

    safe_pl = playlist_name.replace('"', '\\"')
    safe_artist = _applescript_escape(artist)
    safe_track = _applescript_escape(track_name)

    store_id = search_itunes(artist, track_name)
    if not store_id:
        log.info(f"  Not found: {artist} — {track_name}")
        return False

    # Snapshot current track
    snapshot_script = '''
tell application "Music"
    try
        set ct to current track
        return (name of ct) & "|||" & (artist of ct)
    on error
        return ""
    end try
end tell
'''
    prev_track, _ = _run_applescript(snapshot_script)

    # Play via MediaPlayer
    _play_store_track(store_id)

    # Poll until current track changes
    poll_script = '''
tell application "Music"
    try
        set ct to current track
        return (name of ct) & "|||" & (artist of ct)
    on error
        return ""
    end try
end tell
'''
    for _ in range(10):
        time.sleep(0.5)
        out, _ = _run_applescript(poll_script)
        if out and out != prev_track:
            break
    else:
        return False

    # Get current track info
    info_script = '''
tell application "Music"
    try
        set ct to current track
        return (name of ct) & "|||" & (artist of ct)
    on error
        return ""
    end try
end tell
'''
    track_info, _ = _run_applescript(info_script)
    if not track_info or "|||" not in track_info:
        return False
    ct_name, ct_artist = track_info.split("|||", 1)
    safe_ct_name = _applescript_escape(ct_name)
    safe_ct_artist = _applescript_escape(ct_artist)

    # Try to find in library and add to playlist
    lib_script = f'''
tell application "Music"
    try
        set sr to search library playlist 1 for "{safe_ct_name}"
        repeat with t in sr
            if artist of t is "{safe_ct_artist}" then
                duplicate t to user playlist "{safe_pl}"
                return "ok"
            end if
        end repeat
        return "not_in_library"
    on error e
        return "error: " & e
    end try
end tell
'''
    out, code = _run_applescript(lib_script)
    if out.startswith("ok"):
        return True

    # Not in library — add it first
    add_lib_script = '''
tell application "Music"
    try
        set ct to current track
        duplicate ct to source "Library"
        return "lib_ok"
    on error e
        return "lib_error: " & e
    end try
end tell
'''
    lib_out, _ = _run_applescript(add_lib_script)
    if not lib_out.startswith("lib_ok"):
        return False

    # Poll until in library, then add to playlist
    playlist_script = f'''
tell application "Music"
    try
        set sr to search library playlist 1 for "{safe_ct_name}"
        repeat with t in sr
            if artist of t is "{safe_ct_artist}" then
                duplicate t to user playlist "{safe_pl}"
                return "ok"
            end if
        end repeat
        return "notfound"
    on error e
        return "error: " & e
    end try
end tell
'''
    for attempt in range(6):
        time.sleep(2 + attempt)
        out, code = _run_applescript(playlist_script)
        if out.startswith("ok"):
            return True

    return False


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

        phase_a_path = cache_dir / "signal_wargaming_phase_a.json"
        saved_phase_a = json.loads(phase_a_path.read_text()) if phase_a_path.exists() else {}

        manifest_path = cache_dir / "eval_manifest.json"
        manifest = load_manifest(manifest_path)

        # Get offered artists from latest manifest session
        offered_artists = set()
        if manifest.get("sessions"):
            latest = manifest["sessions"][-1]
            for entry in latest.get("artists", []):
                offered_artists.add(entry["name"])

        # Score per-config: which config's ranked list contains each hit
        per_config_hits = {}
        for rec in saved_recs:
            top_names = {name for _, name in rec["ranked"]}
            hits_in_config = [a for a in new_fav_artists if a in top_names and a in offered_artists]
            per_config_hits[rec["name"]] = {
                "hits": len(hits_in_config),
                "pool_size": len([name for _, name in rec["ranked"] if name in offered_artists]),
            }

        # Score per-signal solo: which signal's solo list contains each hit
        per_signal_solo_hits = {}
        for sig, data in saved_phase_a.items():
            ranked_names = {name for _, name in data.get("ranked", [])}
            hits_in_sig = [a for a in new_fav_artists if a in ranked_names and a in offered_artists]
            per_signal_solo_hits[sig] = {
                "hits": len(hits_in_sig),
                "pool_size": len([name for _, name in data.get("ranked", []) if name in offered_artists]),
            }

        # Build round data and accumulate
        round_data = {
            "new_favorites": sorted(new_fav_artists),
            "per_config_hits": per_config_hits,
            "per_signal_solo_hits": per_signal_solo_hits,
        }

        history_path = cache_dir / "post_listen_history.json"
        history = load_post_listen_history(history_path)
        history = accumulate_post_listen_round(history, round_data)
        pathlib.Path(history_path).write_text(json.dumps(history, indent=2))

        # Print current round results
        results = score_post_listen(saved_recs, new_fav_artists)
        log.info("\n=== Post-Listen Scoring (Current Round) ===\n")
        for r in results:
            log.info(f"{r['name']}:")
            pool_size = r.get("pool_size", 80)
            log.info(f"  Hits: {r['hits']}/{pool_size} ({r['precision']:.0f}% precision)")
            if r["matched"]:
                log.info(f"  Matched: {', '.join(r['matched'])}")

        # Print cumulative results
        cum = history.get("cumulative", {})
        log.info(f"\n=== Cumulative Results ({len(history['rounds'])} rounds) ===")
        log.info(f"Total new favorites: {cum.get('total_new_favorites', 0)}")
        if cum.get("per_config"):
            log.info("\nPer-config hit rates:")
            for name, data in cum["per_config"].items():
                rate = data["hits"] / data["pool_size"] * 100 if data["pool_size"] > 0 else 0
                log.info(f"  {name}: {data['hits']}/{data['pool_size']} ({rate:.1f}%)")
        if cum.get("per_signal_solo"):
            log.info("\nPer-signal solo hit rates:")
            for sig, data in cum["per_signal_solo"].items():
                rate = data["hits"] / data["pool_size"] * 100 if data["pool_size"] > 0 else 0
                log.info(f"  {sig}: {data['hits']}/{data['pool_size']} ({rate:.1f}%)")

        # Run statistical test if enough data
        stat_result = run_statistical_test(cum)
        if stat_result:
            log.info(f"\n=== Statistical Test ===")
            log.info(f"Best config: {stat_result['best_config']}")
            log.info(f"p-value: {stat_result['p_value']:.4f}")
            log.info(f"Significant (p < 0.05): {stat_result['significant']}")
        elif cum.get("total_new_favorites", 0) > 0:
            log.info(f"\nNeed {30 - cum.get('total_new_favorites', 0)} more favorites for statistical test.")

        # Update favorites snapshot
        fav_snapshot_path.write_text(json.dumps(new_favorites, indent=2))
        return

    if args.build_playlist:
        recs_path = cache_dir / "signal_wargaming_recs.json"
        if not recs_path.exists():
            log.error("No saved recommendations found. Run the experiment first.")
            sys.exit(1)
        saved_recs = json.loads(recs_path.read_text())

        phase_a_path = cache_dir / "signal_wargaming_phase_a.json"
        if not phase_a_path.exists():
            log.error("No saved phase_a results found. Run the experiment first.")
            sys.exit(1)
        saved_phase_a = json.loads(phase_a_path.read_text())

        manifest_path = cache_dir / "eval_manifest.json"
        manifest = load_manifest(manifest_path)
        prior = get_prior_artists(manifest)

        TARGET_ADDED = 105
        # Request 3x pool to account for artists not found on Apple Music
        stratified = build_stratified_artist_list(
            saved_phase_a, saved_recs, target_total=TARGET_ADDED * 3,
            exclude=eval_exclude, prior_artists=prior)
        log.info(f"\nBuilding evaluation playlist — target: {TARGET_ADDED} tracks added")
        log.info(f"Candidate pool: {len(stratified)} artists")

        from music_discovery import (
            search_itunes, fetch_top_tracks, RATE_LIMIT,
            _run_applescript, _run_jxa, _play_store_track, _applescript_escape,
        )
        import time

        playlist_name = "_TESTING Signal Wargaming"
        if not _setup_named_playlist(playlist_name):
            log.error("Could not create playlist — aborting.")
            sys.exit(1)

        api_key = os.environ.get("LASTFM_API_KEY")
        added_artists = []
        all_attempted = []
        for i, entry in enumerate(stratified, 1):
            if len(added_artists) >= TARGET_ADDED:
                break
            artist = entry["name"]
            added_so_far = len(added_artists)
            log.info(f"[{added_so_far}/{TARGET_ADDED} added] {artist} ({entry['stratum']})")
            tracks = fetch_top_tracks(artist, api_key) if api_key else []
            success = False
            for track in tracks[:3]:
                if _add_track_to_named_playlist(artist, track["name"], playlist_name):
                    entry["added"] = True
                    added_artists.append(entry)
                    success = True
                    break
            if not success:
                entry["added"] = False
            all_attempted.append(entry)
            time.sleep(RATE_LIMIT)

        save_manifest_session(manifest_path, manifest, all_attempted)

        log.info(f"\nEvaluation playlist '{playlist_name}' built: "
                 f"{len(added_artists)} tracks added ({len(all_attempted)} attempted).")
        log.info("Listen, favorite what you like, then run:")
        log.info("  python signal_experiment.py --post-listen")
        return

    report, phase_a, phase_d = run_experiment(
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
            "ranked": rec["ranked"],
            "baseline_diff": rec["baseline_diff"],
        })
    recs_path.write_text(json.dumps(serializable_recs, indent=2))

    phase_a_path = cache_dir / "signal_wargaming_phase_a.json"
    serializable_a = {}
    for sig, data in phase_a.items():
        serializable_a[sig] = {"ranked": data["ranked"]}
    phase_a_path.write_text(json.dumps(serializable_a, indent=2))

    eval_artists = get_evaluation_artists(phase_d, top_n=80, exclude=eval_exclude)
    log.info(f"\n=== Evaluation Playlist Artists ({len(eval_artists)}) ===")
    for a in eval_artists:
        log.info(f"  {a}")
    log.info(f"\nTo build the evaluation playlist, run:")
    log.info(f"  python signal_experiment.py --build-playlist")
    log.info(f"\nAfter listening and favoriting, run:")
    log.info(f"  python signal_experiment.py --post-listen")


if __name__ == "__main__":
    main()
