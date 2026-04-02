#!/usr/bin/env python3
"""
Adaptive Music Discovery Engine

CLI entry point and scoring orchestration. Combines a logistic regression model
(from weight_learner.py) with an affinity graph (from affinity_graph.py) for
two-channel recommendation scoring.

Modes:
  --seed   Initialise the engine: collect signals, build graph, bootstrap model
  --build  Score candidates and generate a playlist (stub — Task 8)
  --feedback  Process listening feedback (stub — Task 9)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from affinity_graph import AffinityGraph
from weight_learner import (
    WeightLearner,
    compute_candidate_features,
    ALL_SIGNAL_NAMES,
    SEED_AGGREGATE_SIGNALS,
    DIRECT_SIGNALS,
)
from feedback import load_feedback_history

log = logging.getLogger("adaptive_engine")

# ── Defaults ─────────────────────────────────────────────────────────────────

DEFAULT_ALPHA = 0.5
DEFAULT_COOLDOWN_ROUNDS = 3
DEFAULT_PLAYLIST_ARTISTS = 50
DEFAULT_TRACKS_PER_ARTIST = 2


# ── Pure scoring functions ───────────────────────────────────────────────────

def compute_final_score(
    model_score: float,
    affinity_mm: float,
    affinity_lfm: float,
    w_mm: float = 1.0,
    w_lfm: float = 1.0,
    alpha: float = DEFAULT_ALPHA,
) -> float:
    """Two-channel: alpha * model + (1-alpha) * weighted_affinity.

    Affinity values are expected in [-1, 1] (or will be clamped).
    The affinity term is mapped from [-1, 1] to [0, 1] before blending.
    """
    affinity = w_mm * affinity_mm + w_lfm * affinity_lfm
    aff_combined = max(-1.0, min(1.0, affinity))
    return alpha * model_score + (1.0 - alpha) * ((aff_combined + 1) / 2)


def apply_overrides(scores: dict, overrides: dict) -> dict:
    """Apply manual pin overrides. Returns new dict.

    overrides["pins"] maps artist names to floats:
      - positive pin (e.g. 1.0) forces that score
      - negative pin (e.g. -1.0) suppresses to 0.0
    """
    pins = overrides.get("pins", {})
    result = dict(scores)
    for artist, pin_value in pins.items():
        artist_lower = artist.strip().lower()
        if pin_value < 0:
            result[artist_lower] = 0.0
        else:
            result[artist_lower] = pin_value
    return result


def check_cooldown(
    artist: str,
    history_rounds: list,
    current_round: int,
    cooldown_rounds: int = DEFAULT_COOLDOWN_ROUNDS,
) -> bool:
    """Returns True if artist should be skipped (offered recently, not favorited).

    An artist is cooled down if it appeared in a recent round (within
    cooldown_rounds of current_round) and was NOT favorited in that round.
    """
    for rnd in history_rounds:
        round_id = rnd.get("round_id", 0)
        try:
            round_num = int(round_id)
        except (ValueError, TypeError):
            continue
        if current_round - round_num > cooldown_rounds:
            continue
        if current_round - round_num <= 0:
            continue
        artist_fb = rnd.get("artist_feedback", {})
        fb = artist_fb.get(artist)
        if fb is not None:
            # Artist was offered in this round
            if fb.get("fave_tracks", 0) > 0:
                # Favorited — do NOT cool down
                return False
            else:
                # Offered but not favorited — cool down
                return True
    return False


def load_overrides(path: str | pathlib.Path) -> dict:
    """Load artist_overrides.json. Returns {"pins": {}, "expunged_feedback": []}.

    Returns default empty structure if file is missing or invalid.
    """
    p = pathlib.Path(path)
    if not p.exists():
        return {"pins": {}, "expunged_feedback": []}
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
        return {
            "pins": data.get("pins", {}),
            "expunged_feedback": data.get("expunged_feedback", []),
        }
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Failed to load overrides from %s: %s", p, exc)
        return {"pins": {}, "expunged_feedback": []}


def generate_explanation(
    artist: str,
    final_score: float,
    model_score: float,
    affinity_mm: float,
    affinity_lfm: float,
    feature_dict: dict,
    weights: list,
    affinity_path: str = "",
) -> str:
    """Human-readable explanation string for why an artist was recommended.

    Includes the final score, model score, affinity scores, and top contributing
    signals sorted by absolute weight contribution.
    """
    lines = [f"Artist: {artist}"]
    lines.append(f"  Final score: {final_score:.4f}")
    lines.append(f"  Model score: {model_score:.4f}")
    lines.append(f"  Affinity — music-map: {affinity_mm:.4f}, last.fm: {affinity_lfm:.4f}")

    # Rank signals by |weight * feature_value|
    signal_contribs = []
    signal_names_list = list(feature_dict.keys())
    for i, sig in enumerate(signal_names_list):
        w = weights[i] if i < len(weights) else 0.0
        val = feature_dict.get(sig, 0.0)
        contrib = abs(w * val)
        signal_contribs.append((sig, val, w, contrib))

    signal_contribs.sort(key=lambda x: x[3], reverse=True)

    lines.append("  Top signals:")
    for sig, val, w, contrib in signal_contribs[:5]:
        direction = "+" if w * val >= 0 else "-"
        lines.append(f"    {sig}: value={val:.3f}, weight={w:.3f} ({direction})")

    if affinity_path:
        lines.append(f"  Affinity path: {affinity_path}")

    return "\n".join(lines)


def rank_candidates(
    scores: dict,
    *,
    blocklist: set | None = None,
    overrides: dict | None = None,
    history_rounds: list | None = None,
    current_round: int = 1,
    cooldown_rounds: int = DEFAULT_COOLDOWN_ROUNDS,
) -> list:
    """Rank after applying blocklist, overrides, cooldown. Returns [(score, name)] desc."""
    if blocklist is None:
        blocklist = set()
    if overrides is None:
        overrides = {"pins": {}, "expunged_feedback": []}
    if history_rounds is None:
        history_rounds = []

    # Apply overrides first
    working = apply_overrides(scores, overrides)

    # Filter and rank
    ranked = []
    for artist, score in working.items():
        if artist in blocklist:
            continue
        if score <= 0.0:
            continue
        if check_cooldown(artist, history_rounds, current_round, cooldown_rounds):
            continue
        ranked.append((score, artist))

    ranked.sort(key=lambda x: (-x[0], x[1]))
    return ranked


# ── Seed mode ─────────────────────────────────────────────────────────────────

def _run_seed(cache_dir: pathlib.Path, args):
    """Full seed implementation: collect signals, build graph, bootstrap model."""
    from music_discovery import (
        load_dotenv,
        parse_library_jxa,
        load_cache,
        save_cache,
        fetch_filter_data,
        check_ai_artist,
        load_ai_blocklist,
        load_ai_allowlist,
        load_user_blocklist,
        load_blocklist,
        _build_paths,
    )
    from signal_collectors import (
        collect_playcounts_jxa,
        collect_user_playlists_jxa,
        collect_ratings_jxa,
        collect_lastfm_loved,
    )
    from signal_experiment import (
        load_manifest,
        load_post_listen_history,
    )

    load_dotenv()

    api_key = os.environ.get("LASTFM_API_KEY", "").strip()
    lastfm_user = os.environ.get("LASTFM_USERNAME", "").strip() or None
    if not api_key:
        log.error("LASTFM_API_KEY not set in .env — cannot proceed.")
        sys.exit(1)

    paths = _build_paths()
    cache_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Collect library signals ──────────────────────────────────────
    log.info("Step 1: Collecting library signals...")

    log.info("  Reading favorited tracks from Music.app...")
    favorites = parse_library_jxa()
    log.info("  Found %d favorited artists.", len(favorites))

    log.info("  Reading play counts...")
    playcounts = collect_playcounts_jxa()
    log.info("  Found %d artists with plays.", len(playcounts))

    log.info("  Reading playlist membership...")
    playlists = collect_user_playlists_jxa()
    log.info("  Found %d artists in user playlists.", len(playlists))

    log.info("  Reading star ratings...")
    ratings_raw = collect_ratings_jxa()
    # Convert to simple {artist: avg_centered} for signal use
    ratings = {a: d["avg_centered"] for a, d in ratings_raw.items()}
    log.info("  Found %d artists with ratings.", len(ratings))

    # All library artists (union of all signal sources)
    library_artists = set(favorites.keys()) | set(playcounts.keys()) | set(playlists.keys()) | set(ratings.keys())
    log.info("  Total library artists: %d", len(library_artists))

    # Build seed signals dict for compute_candidate_features
    seed_signals = {
        "favorites": {a: float(v) for a, v in favorites.items()},
        "playcount": {a: float(v) for a, v in playcounts.items()},
        "playlists": {a: float(v) for a, v in playlists.items()},
        "ratings": ratings,
    }

    # ── Step 2: Build similarity graph ───────────────────────────────────────
    log.info("Step 2: Building similarity graph...")

    scrape_cache = load_cache(paths["cache"])
    filter_cache = load_cache(paths["filter_cache"])
    log.info("  Loaded %d music-map cache entries, %d filter cache entries.",
             len(scrape_cache), len(filter_cache))

    graph = AffinityGraph()

    # Add music-map edges
    mm_edges = 0
    for artist, neighbors in scrape_cache.items():
        for neighbor, weight in neighbors.items():
            graph.add_edge_musicmap(artist.lower(), neighbor.lower(), weight)
            mm_edges += 1
    log.info("  Added %d music-map edges.", mm_edges)

    # ── Step 3: Collect Last.fm similar for library artists if not cached ────
    log.info("Step 3: Collecting Last.fm similar artists for library artists...")

    lfm_edges = 0
    fetched = 0
    for artist in library_artists:
        # Check if we already have similar data in filter_cache
        entry = filter_cache.get(artist, {})
        similar = entry.get("similar_artists")

        if similar is None and not args.skip_fetch:
            # Fetch from Last.fm
            log.info("  Fetching filter data for '%s'...", artist)
            new_entry = fetch_filter_data(artist, api_key)
            if new_entry:
                filter_cache[artist] = new_entry
                similar = new_entry.get("similar_artists", [])
                fetched += 1
                time.sleep(1.2)  # Rate limiting

        if similar:
            for sim in similar:
                sim_name = sim.get("name", "").strip().lower()
                match_score = float(sim.get("match", 0))
                if sim_name and match_score > 0:
                    graph.add_edge_lastfm(artist, sim_name, match_score)
                    lfm_edges += 1

    if fetched > 0:
        log.info("  Fetched filter data for %d new artists.", fetched)
        save_cache(filter_cache, paths["filter_cache"])
    log.info("  Added %d Last.fm similar edges.", lfm_edges)

    # Save graph
    graph_path = cache_dir / "affinity_graph.json"
    graph.save(graph_path)
    log.info("  Saved affinity graph to %s", graph_path)

    # ── Step 4: Bootstrap model from wargaming data ──────────────────────────
    log.info("Step 4: Bootstrapping model from wargaming data...")

    manifest_path = cache_dir / "eval_manifest.json"
    history_path = cache_dir / "post_listen_history.json"

    manifest = load_manifest(manifest_path)
    post_history = load_post_listen_history(history_path)

    # Collect all offered artists from manifest sessions
    offered_artists = {}
    for session in manifest.get("sessions", []):
        for entry in session.get("artists", []):
            name = entry.get("name", "").strip().lower()
            if name:
                offered_artists[name] = entry

    # Collect all favorited artists from post-listen history
    all_favorites = set()
    for rnd in post_history.get("rounds", []):
        for fav in rnd.get("new_favorites", []):
            all_favorites.add(fav.strip().lower())

    log.info("  Manifest: %d offered artists, %d favorited.",
             len(offered_artists), len(all_favorites))

    # Determine signal names (exclude lastfm_loved if no username)
    signal_names = list(ALL_SIGNAL_NAMES)
    if not lastfm_user:
        signal_names = [s for s in signal_names if s != "lastfm_loved"]
        log.info("  No Last.fm username — excluding lastfm_loved signal.")

    # Collect Last.fm loved tracks if username is available
    lastfm_loved_artists = set()
    if lastfm_user:
        log.info("  Collecting Last.fm loved tracks for %s...", lastfm_user)
        try:
            lastfm_loved_artists = collect_lastfm_loved(lastfm_user, api_key)
            log.info("  Found %d Last.fm loved artists.", len(lastfm_loved_artists))
        except Exception as exc:
            log.warning("  Failed to collect Last.fm loved tracks: %s", exc)

    # Load AI lists
    project_dir = pathlib.Path(__file__).parent
    ai_blocklist = load_ai_blocklist(project_dir / "ai_blocklist.txt")
    ai_allowlist = load_ai_allowlist(project_dir / "ai_allowlist.txt")

    # Build training examples
    feature_dicts = []
    labels = []

    for artist_name, entry in offered_artists.items():
        # Compute proximities for this candidate: {seed_artist: {candidate: proximity}}
        proximities = {}
        for seed in library_artists:
            seed_data = scrape_cache.get(seed, {})
            prox = seed_data.get(artist_name, 0.0)
            if prox > 0:
                proximities[seed] = {artist_name: prox}

        # Direct signals
        direct = {
            "heavy_rotation": 0.0,
            "recommendations": 0.0,
            "lastfm_similar": 0.0,
            "lastfm_loved": 1.0 if artist_name in lastfm_loved_artists else 0.0,
            "ai_heuristic": 0.0,  # spec requirement: 0.0 for bootstrap
        }

        features = compute_candidate_features(
            candidate=artist_name,
            seed_signals=seed_signals,
            proximities=proximities,
            direct_signals=direct,
            signal_names=signal_names,
        )

        label = 1 if artist_name in all_favorites else 0
        feature_dicts.append(features)
        labels.append(label)

    if not feature_dicts:
        log.warning("  No training examples found. Cannot bootstrap model.")
        log.warning("  Run signal_experiment.py first to generate eval data.")
        return

    pos_count = sum(labels)
    neg_count = len(labels) - pos_count
    log.info("  Training examples: %d total (%d positive, %d negative).",
             len(labels), pos_count, neg_count)

    if pos_count == 0 or neg_count == 0:
        log.warning("  Need both positive and negative examples to train.")
        log.warning("  Skipping model training.")
        return

    learner = WeightLearner(signal_names=signal_names)
    learner.fit(feature_dicts, labels)

    model_path = cache_dir / "weight_model.json"
    learner.save(model_path)
    log.info("  Saved model to %s", model_path)

    # Log model weights
    for i, sig in enumerate(signal_names):
        log.info("    %s: weight=%.4f", sig, learner._weights[i])

    # ── Step 5: Sanity check — score top 50 candidates ───────────────────────
    log.info("Step 5: Sanity check — scoring top candidates...")

    # Collect all candidate artists (from scrape cache, not in library)
    all_candidates = set()
    for artist, neighbors in scrape_cache.items():
        all_candidates.update(n.lower() for n in neighbors.keys())
    all_candidates -= library_artists

    # Load blocklists for filtering
    user_blocklist = load_user_blocklist(project_dir / "blocklist.txt")
    file_blocklist = load_blocklist(paths["blocklist"])
    full_blocklist = user_blocklist | file_blocklist | ai_blocklist

    # Propagate affinity (inject library favorites as positive signal)
    graph.reset_injections()
    for artist, fav_count in favorites.items():
        graph.inject_feedback(artist, fave_count=fav_count)
    propagated = graph.propagate()
    aff_mm = propagated.get("musicmap", {})
    aff_lfm = propagated.get("lastfm", {})

    # Normalize affinity to [-1, 1] range
    def _normalize_affinity(scores_dict):
        if not scores_dict:
            return {}
        max_abs = max(abs(v) for v in scores_dict.values()) or 1.0
        return {k: v / max_abs for k, v in scores_dict.items()}

    aff_mm_norm = _normalize_affinity(aff_mm)
    aff_lfm_norm = _normalize_affinity(aff_lfm)

    # Score candidates
    candidate_scores = {}
    for candidate in all_candidates:
        if candidate in full_blocklist:
            continue

        # Build proximities for this candidate
        proximities = {}
        for seed in library_artists:
            seed_data = scrape_cache.get(seed, {})
            prox = seed_data.get(candidate, 0.0)
            if prox > 0:
                proximities[seed] = {candidate: prox}

        # Compute AI heuristic score where filter data exists
        ai_score = 0.0
        filter_entry = filter_cache.get(candidate, {})
        if filter_entry:
            blocked, reason = check_ai_artist(
                candidate, filter_entry, ai_blocklist, ai_allowlist
            )
            if blocked:
                continue  # Skip AI-detected artists
            # Use a simple heuristic: higher listeners = lower AI risk
            listeners = filter_entry.get("listeners", 0)
            if listeners > 0:
                import math
                # Scale: 0 at 100 listeners, 1.0 at 100k+
                ai_score = min(1.0, max(0.0, (math.log10(max(listeners, 1)) - 2) / 3))

        direct = {
            "heavy_rotation": 0.0,
            "recommendations": 0.0,
            "lastfm_similar": 0.0,
            "lastfm_loved": 1.0 if candidate in lastfm_loved_artists else 0.0,
            "ai_heuristic": ai_score,
        }

        features = compute_candidate_features(
            candidate=candidate,
            seed_signals=seed_signals,
            proximities=proximities,
            direct_signals=direct,
            signal_names=signal_names,
        )

        model_score = learner.predict_proba(features)
        mm_aff = aff_mm_norm.get(candidate, 0.0)
        lfm_aff = aff_lfm_norm.get(candidate, 0.0)
        final = compute_final_score(model_score, mm_aff, lfm_aff, alpha=args.alpha)
        candidate_scores[candidate] = final

    ranked = rank_candidates(candidate_scores, blocklist=full_blocklist)

    log.info("\n  Top %d candidates:", args.playlist_size)
    log.info("  %-4s  %-40s  %s", "Rank", "Artist", "Score")
    log.info("  %s", "-" * 55)
    for i, (score, name) in enumerate(ranked[:args.playlist_size], 1):
        log.info("  %-4d  %-40s  %.4f", i, name, score)

    log.info("\nSeed complete. Model and graph saved to %s", cache_dir)


# ── Build and feedback stubs ─────────────────────────────────────────────────

def _run_build(cache_dir: pathlib.Path, args):
    """Build mode stub. Full implementation in Task 8."""
    log.info("--build mode: Full implementation in Task 8.")
    log.info("This will score all candidates and generate a playlist.")


def _run_feedback(cache_dir: pathlib.Path, args):
    """Feedback mode stub. Full implementation in Task 9."""
    log.info("--feedback mode: Full implementation in Task 9.")
    log.info("This will process listening feedback and update the model.")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Adaptive music discovery engine"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--seed",
        action="store_true",
        help="Initialise: collect signals, build graph, bootstrap model",
    )
    group.add_argument(
        "--build",
        action="store_true",
        help="Score candidates and generate a playlist",
    )
    group.add_argument(
        "--feedback",
        action="store_true",
        help="Process listening feedback and retrain",
    )
    parser.add_argument(
        "--rescan",
        action="store_true",
        help="Force re-collection of library signals",
    )
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Skip fetching new Last.fm data (use cached only)",
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=DEFAULT_ALPHA,
        help=f"Model vs affinity blend (default: {DEFAULT_ALPHA})",
    )
    parser.add_argument(
        "--playlist-size",
        type=int,
        default=DEFAULT_PLAYLIST_ARTISTS,
        help=f"Number of artists in playlist (default: {DEFAULT_PLAYLIST_ARTISTS})",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )

    cache_dir = pathlib.Path(
        os.environ.get("CACHE_DIR", "~/.cache/music_discovery")
    ).expanduser().resolve()

    if args.seed:
        _run_seed(cache_dir, args)
    elif args.build:
        _run_build(cache_dir, args)
    elif args.feedback:
        _run_feedback(cache_dir, args)


if __name__ == "__main__":
    main()
