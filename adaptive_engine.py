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


# ── Offered tracks persistence ───────────────────────────────────────────────

def _load_offered_tracks(path: pathlib.Path) -> tuple[set, list]:
    """Load previously offered tracks. Returns (set of (artist, track), raw entries list)."""
    if not path.exists():
        return set(), []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data.get("tracks", [])
        track_set = {(t["artist"], t["track"]) for t in entries}
        return track_set, entries
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        log.warning("Corrupt offered_tracks.json, starting fresh: %s", e)
        return set(), []


def _save_offered_tracks(path: pathlib.Path, entries: list):
    """Save offered tracks to JSON with atomic write."""
    data = {"version": 1, "tracks": entries}
    tmp = pathlib.Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


# ── Search strikes persistence ───────────────────────────────────────────────

STRIKE_THRESHOLD = 3


def _load_search_strikes(path: pathlib.Path) -> dict:
    """Load search strike counters. Returns dict of artist -> {count, last_round, last_recheck}."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("strikes", {})
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        log.warning("Corrupt search_strikes.json, starting fresh: %s", e)
        return {}


def _save_search_strikes(path: pathlib.Path, strikes: dict):
    """Save search strikes with atomic write."""
    data = {"version": 1, "strikes": strikes}
    tmp = pathlib.Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _evaluate_artist_strikes(strikes: dict, artist: str,
                              search_results: list, current_round: int) -> bool:
    """Evaluate search results for an artist and update strike counter.
    Returns True if artist should be auto-blocklisted (hit threshold)."""
    entry = strikes.get(artist, {"count": 0, "last_round": 0, "last_recheck": 0})

    any_found = any(r.store_id is not None for r in search_results)
    any_searched_ok = any(r.searched_ok for r in search_results)
    all_errored = not any_searched_ok

    if any_found:
        entry["count"] = 0
        entry["last_round"] = current_round
        strikes[artist] = entry
        return False

    if all_errored:
        return False

    # All searched OK but none found
    if entry["last_round"] > 0 and current_round - entry["last_round"] > 1:
        entry["count"] = 0  # reset stale counter

    entry["count"] += 1
    entry["last_round"] = current_round
    strikes[artist] = entry

    return entry["count"] >= STRIKE_THRESHOLD


# ── Auto-blocklist write and on-demand re-check ──────────────────────────────

RECHECK_COOLDOWN = 10


def _auto_blocklist_artist(blocklist_path: pathlib.Path, artist: str, round_num: int):
    """Append an artist to ai_blocklist.txt if not already present."""
    existing = set()
    if blocklist_path.exists():
        for line in blocklist_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                existing.add(stripped.lower())

    if artist.lower() in existing:
        return

    with open(blocklist_path, "a", encoding="utf-8") as f:
        f.write(f"# auto-blocklisted round {round_num}:\n")
        f.write(f"{artist}\n")
    log.warning("Auto-blocklisted \"%s\" — not found on Apple Music for %d consecutive rounds",
                artist, STRIKE_THRESHOLD)


def _should_recheck_artist(strikes: dict, artist: str, current_round: int) -> bool:
    """Check if a blocklisted artist should be re-tested."""
    entry = strikes.get(artist)
    if not entry:
        return False
    last_recheck = entry.get("last_recheck", 0)
    return current_round - last_recheck >= RECHECK_COOLDOWN


def _remove_from_blocklist(blocklist_path: pathlib.Path, artist: str):
    """Remove an auto-blocklisted artist and its comment from the blocklist file."""
    if not blocklist_path.exists():
        return
    lines = blocklist_path.read_text(encoding="utf-8").splitlines()
    new_lines = []
    for line in lines:
        if line.strip().lower() == artist.lower():
            if new_lines and new_lines[-1].strip().startswith("# auto-blocklisted"):
                new_lines.pop()
            continue
        new_lines.append(line)
    blocklist_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    log.info("Re-checked \"%s\" — now available on Apple Music, removed from auto-blocklist", artist)


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


def _normalize_affinity(raw_scores: dict) -> dict:
    """Symmetric normalization: maps scores to [-1, 1] preserving sign.

    Uses max(abs(v)) as the divisor so negative scores are preserved,
    not clamped to zero.
    """
    if not raw_scores:
        return {}
    max_abs = max(abs(v) for v in raw_scores.values())
    if max_abs == 0:
        return {k: 0.0 for k in raw_scores}
    return {k: v / max_abs for k, v in raw_scores.items()}


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
    from affinity_graph import LIBRARY_HALF_LIFE_DAYS, DISCOVERY_HALF_LIFE_DAYS

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
    # Apply log1p scaling to compress large ranges (playcount can be 10000+)
    # before proximity-weighted aggregation. This prevents numerical overflow
    # in the logistic regression solver.
    import math as _math
    seed_signals = {
        "favorites": {a: _math.log1p(float(v)) for a, v in favorites.items()},
        "playcount": {a: _math.log1p(float(v)) for a, v in playcounts.items()},
        "playlists": {a: _math.log1p(float(v)) for a, v in playlists.items()},
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

    # Propagate affinity:
    # 1. Library favorites as background positive signal (decayed as library data)
    # 2. Wargaming favorites as strong discovery feedback (recent, high signal)
    graph.reset_injections()
    for artist, fav_count in favorites.items():
        graph.inject_feedback(
            artist, fave_count=fav_count, tracks_offered=3,
            half_life_days=LIBRARY_HALF_LIFE_DAYS,
        )
    # Inject wargaming favorites as recent discovery feedback
    for fav in all_favorites:
        graph.inject_feedback(
            fav, fave_count=1, tracks_offered=2,
            days_ago=7, half_life_days=DISCOVERY_HALF_LIFE_DAYS,
        )
    propagated = graph.propagate()
    aff_mm = propagated.get("musicmap", {})
    aff_lfm = propagated.get("lastfm", {})

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
    """Build mode: score all candidates, build playlist, save snapshot for feedback."""
    import math
    from datetime import datetime, timezone

    from music_discovery import (
        load_dotenv,
        parse_library_jxa,
        collect_track_metadata_jxa,
        load_cache,
        fetch_filter_data,
        fetch_top_tracks,
        fetch_artist_catalog,
        search_itunes,
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
        collect_heavy_rotation,
        collect_recommendations,
        collect_lastfm_loved,
        _make_user_session,
    )
    from signal_experiment import _add_track_to_named_playlist
    from feedback import create_snapshot, save_snapshot

    load_dotenv()

    api_key = os.environ.get("LASTFM_API_KEY", "").strip()
    lastfm_user = os.environ.get("LASTFM_USERNAME", "").strip() or None
    if not api_key:
        log.error("LASTFM_API_KEY not set in .env — cannot proceed.")
        sys.exit(1)

    paths = _build_paths()
    cache_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Load model and graph ─────────────────────────────────────────
    log.info("Step 1: Loading model and graph...")

    model_path = cache_dir / "weight_model.json"
    graph_path = cache_dir / "affinity_graph.json"

    if not model_path.exists():
        log.error("No model found at %s. Run --seed first.", model_path)
        sys.exit(1)

    learner = WeightLearner.load(model_path)
    graph = AffinityGraph.load(graph_path)
    log.info("  Loaded model (%d signals) and graph.", len(learner.signal_names))

    signal_names = learner.signal_names

    # ── Step 2: Collect library signals ──────────────────────────────────────
    log.info("Step 2: Collecting library signals...")

    favorites = parse_library_jxa()
    log.info("  %d favorited artists.", len(favorites))

    playcounts = collect_playcounts_jxa()
    log.info("  %d artists with plays.", len(playcounts))

    playlists = collect_user_playlists_jxa()
    log.info("  %d artists in playlists.", len(playlists))

    ratings_raw = collect_ratings_jxa()
    ratings = {a: d["avg_centered"] for a, d in ratings_raw.items()}
    log.info("  %d artists with ratings.", len(ratings))

    library_artists = (
        set(favorites.keys()) | set(playcounts.keys())
        | set(playlists.keys()) | set(ratings.keys())
    )

    import math as _math
    seed_signals = {
        "favorites": {a: _math.log1p(float(v)) for a, v in favorites.items()},
        "playcount": {a: _math.log1p(float(v)) for a, v in playcounts.items()},
        "playlists": {a: _math.log1p(float(v)) for a, v in playlists.items()},
        "ratings": ratings,  # Already centered [-1, 1], no scaling needed
    }

    # ── Step 3: Optional API signals ─────────────────────────────────────────
    log.info("Step 3: Collecting optional API signals...")

    heavy_rotation_artists: set = set()
    recommendation_artists: set = set()
    lastfm_loved_artists: set = set()

    apple_dev_token = os.environ.get("APPLE_MUSIC_DEV_TOKEN", "").strip()
    apple_user_token = os.environ.get("APPLE_MUSIC_USER_TOKEN", "").strip()
    if apple_dev_token and apple_user_token:
        try:
            session = _make_user_session(apple_dev_token, apple_user_token)
            heavy_rotation_artists = collect_heavy_rotation(session)
            log.info("  %d heavy rotation artists.", len(heavy_rotation_artists))
            recommendation_artists = collect_recommendations(session)
            log.info("  %d recommendation artists.", len(recommendation_artists))
        except Exception as exc:
            log.warning("  Apple Music API failed: %s", exc)
    else:
        log.info("  Apple Music tokens not set — skipping heavy_rotation/recommendations.")

    if lastfm_user:
        try:
            lastfm_loved_artists = collect_lastfm_loved(lastfm_user, api_key)
            log.info("  %d Last.fm loved artists.", len(lastfm_loved_artists))
        except Exception as exc:
            log.warning("  Last.fm loved failed: %s", exc)

    # ── Step 4: Load blocklist, overrides, feedback history ──────────────────
    log.info("Step 4: Loading blocklist, overrides, feedback history...")

    project_dir = pathlib.Path(__file__).parent
    ai_blocklist = load_ai_blocklist(project_dir / "ai_blocklist.txt")
    ai_allowlist = load_ai_allowlist(project_dir / "ai_allowlist.txt")
    user_blocklist = load_user_blocklist(project_dir / "blocklist.txt")
    file_blocklist = load_blocklist(paths["blocklist"])
    full_blocklist = user_blocklist | file_blocklist | ai_blocklist

    overrides = load_overrides(cache_dir / "artist_overrides.json")
    history_rounds = load_feedback_history(cache_dir / "feedback_history.json")
    current_round = len(history_rounds) + 1
    log.info("  Round %d. %d history rounds, %d blocklisted.",
             current_round, len(history_rounds), len(full_blocklist))

    # ── Step 5: Inject into graph and propagate ──────────────────────────────
    log.info("Step 5: Injecting signals and propagating graph...")

    # Collect track metadata for dateAdded recency
    track_metadata = collect_track_metadata_jxa()
    # Build artist → earliest dateAdded mapping
    now = datetime.now(timezone.utc)
    artist_date_added: dict[str, float] = {}  # artist → days_ago
    for track in track_metadata:
        artist = (track.get("artist") or "").lower().strip()
        date_str = track.get("dateAdded", "")
        if not artist or not date_str:
            continue
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            days_ago = max(0.0, (now - dt).total_seconds() / 86400)
        except (ValueError, TypeError):
            continue
        # Use the earliest (smallest days_ago) for the artist
        if artist not in artist_date_added or days_ago < artist_date_added[artist]:
            artist_date_added[artist] = days_ago

    graph.reset_injections()

    # Inject library favorites with actual dateAdded recency
    for artist, fav_count in favorites.items():
        days_ago = artist_date_added.get(artist, 180.0)  # fallback to half-life
        graph.inject_feedback(artist, fave_count=fav_count, days_ago=days_ago)

    # Replay feedback history
    for rnd in history_rounds:
        round_id = rnd.get("round_id", "0")
        try:
            rnd_num = int(round_id)
            rnd_days_ago = max(0.0, (current_round - rnd_num) * 14)  # ~2 weeks per round
        except (ValueError, TypeError):
            rnd_days_ago = 90.0

        from affinity_graph import DISCOVERY_HALF_LIFE_DAYS
        for artist, fb in rnd.get("artist_feedback", {}).items():
            graph.inject_feedback(
                artist,
                fave_count=fb.get("fave_tracks", 0),
                skip_count=fb.get("skip_tracks", 0),
                listen_count=fb.get("listen_tracks", 0),
                tracks_offered=fb.get("tracks_offered", 1),
                days_ago=rnd_days_ago,
                half_life_days=DISCOVERY_HALF_LIFE_DAYS,
            )

    propagated = graph.propagate()
    aff_mm = propagated.get("musicmap", {})
    aff_lfm = propagated.get("lastfm", {})

    # ── Step 6: Normalize affinity (symmetric, preserving negatives) ─────────
    aff_mm_norm = _normalize_affinity(aff_mm)
    aff_lfm_norm = _normalize_affinity(aff_lfm)
    log.info("  Propagated: %d musicmap scores, %d lastfm scores.",
             len(aff_mm_norm), len(aff_lfm_norm))

    # ── Step 7: Score all candidates ─────────────────────────────────────────
    log.info("Step 6: Scoring candidates...")

    scrape_cache = load_cache(paths["cache"])
    filter_cache = load_cache(paths["filter_cache"])

    all_candidates = set()
    for artist, neighbors in scrape_cache.items():
        all_candidates.update(n.lower() for n in neighbors.keys())
    # Don't exclude library artists — they may have deep cuts worth discovering.
    # Blocklists are applied in the scoring loop below.

    candidate_scores: dict = {}
    candidate_features: dict = {}
    candidate_details: dict = {}  # for explanation generation

    for candidate in all_candidates:
        if candidate in full_blocklist:
            continue

        # Build proximities
        proximities = {}
        for seed in library_artists:
            seed_data = scrape_cache.get(seed, {})
            prox = seed_data.get(candidate, 0.0)
            if prox > 0:
                proximities[seed] = {candidate: prox}

        # Compute AI heuristic score
        ai_score = 0.0
        filter_entry = filter_cache.get(candidate, {})
        if filter_entry:
            blocked, reason = check_ai_artist(
                candidate, filter_entry, ai_blocklist, ai_allowlist
            )
            if blocked:
                continue
            listeners = filter_entry.get("listeners", 0)
            if listeners > 0:
                ai_score = min(1.0, max(0.0, (math.log10(max(listeners, 1)) - 2) / 3))

        direct = {
            "heavy_rotation": 1.0 if candidate in heavy_rotation_artists else 0.0,
            "recommendations": 1.0 if candidate in recommendation_artists else 0.0,
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
        candidate_features[candidate] = features
        candidate_details[candidate] = {
            "model_score": model_score,
            "affinity_mm": mm_aff,
            "affinity_lfm": lfm_aff,
        }

    log.info("  Scored %d candidates.", len(candidate_scores))

    # ── Step 7b: On-demand re-check for auto-blocklisted candidates ────────
    strikes_path = cache_dir / "search_strikes.json"
    strikes = _load_search_strikes(strikes_path)
    blocklist_path = pathlib.Path(__file__).parent / "ai_blocklist.txt"

    rechecked = 0
    for candidate in list(candidate_scores.keys()):
        if candidate not in full_blocklist:
            continue
        if not _should_recheck_artist(strikes, candidate, current_round):
            continue
        # Eligible for re-check
        catalog = fetch_artist_catalog(candidate)
        strikes.setdefault(candidate, {"count": 3, "last_round": 0, "last_recheck": 0})
        if catalog:
            _remove_from_blocklist(blocklist_path, candidate)
            full_blocklist.discard(candidate)
            rechecked += 1
            log.info("  Re-check passed for %s, re-entering candidate pool", candidate)
        else:
            strikes[candidate]["last_recheck"] = current_round
    if rechecked:
        log.info("  Re-checked blocklist: %d artists recovered.", rechecked)
    _save_search_strikes(strikes_path, strikes)

    # ── Step 8: Rank and filter ──────────────────────────────────────────────
    ranked = rank_candidates(
        candidate_scores,
        blocklist=full_blocklist,
        overrides=overrides,
        history_rounds=history_rounds,
        current_round=current_round,
    )

    playlist_size = args.playlist_size
    top_artists = ranked[:playlist_size]  # preserve for explanation report below

    log.info("\n  Top %d candidates:", len(top_artists))
    log.info("  %-4s  %-40s  %s", "Rank", "Artist", "Score")
    log.info("  %s", "-" * 55)
    for i, (score, name) in enumerate(top_artists, 1):
        log.info("  %-4d  %-40s  %.4f", i, name, score)

    # ── Step 9: Build playlist ───────────────────────────────────────────────
    log.info("\nStep 7: Building playlist...")

    playlist_name = f"Adaptive Discovery R{current_round}"
    tracks_per_artist = DEFAULT_TRACKS_PER_ARTIST

    # Load cross-round state
    offered_path = cache_dir / "offered_tracks.json"
    offered_set, offered_entries = _load_offered_tracks(offered_path)

    offered_tracks: set = set()  # (artist, track_name) for this round's snapshot
    artist_idx = 0
    slots_filled = 0

    while slots_filled < playlist_size and artist_idx < len(ranked):
        _score, artist = ranked[artist_idx]
        artist_idx += 1

        # Tiered track sourcing: Last.fm top 50 first, then iTunes catalog
        lastfm_tracks = fetch_top_tracks(artist, api_key, limit=50) if api_key else []
        catalog_tracks = fetch_artist_catalog(artist)

        # Deduplicate catalog against Last.fm (by lowercased track name)
        lastfm_names = {t["name"].lower() for t in lastfm_tracks}
        unique_catalog = [t for t in catalog_tracks if t["name"].lower() not in lastfm_names]

        all_tracks = lastfm_tracks + unique_catalog
        artist_search_results = []
        added_count = 0
        search_attempts = 0
        max_attempts = tracks_per_artist * 3  # cap to avoid spending minutes per artist

        for track in all_tracks:
            if added_count >= tracks_per_artist:
                break
            if search_attempts >= max_attempts:
                break
            track_name = track.get("name", "")
            if not track_name:
                continue

            # Cross-round dedup
            key = (artist.lower(), track_name.lower())
            if key in offered_set:
                continue

            # Search iTunes
            result = search_itunes(artist, track_name)
            artist_search_results.append(result)
            search_attempts += 1

            if not result:
                continue

            # Try to add to playlist
            if _add_track_to_named_playlist(artist, track_name, playlist_name,
                                             search_result=result):
                offered_tracks.add(key)
                offered_set.add(key)
                offered_entries.append({
                    "artist": artist.lower(),
                    "track": track_name.lower(),
                    "round": current_round,
                })
                added_count += 1

            time.sleep(0.3)  # Rate limiting

        # Evaluate strikes for this artist
        if artist_search_results:
            should_block = _evaluate_artist_strikes(
                strikes, artist.lower(), artist_search_results, current_round
            )
            if should_block:
                _auto_blocklist_artist(blocklist_path, artist, current_round)

        if added_count > 0:
            log.info("  Added %d tracks for %s", added_count, artist)
            slots_filled += 1
        else:
            log.warning("  No tracks added for %s", artist)

        time.sleep(0.5)  # Rate limiting between artists

    # Save cross-round state
    _save_offered_tracks(offered_path, offered_entries)
    _save_search_strikes(strikes_path, strikes)

    log.info("  Playlist '%s': %d tracks for %d artists (of %d ranked).",
             playlist_name, len(offered_tracks), slots_filled, len(ranked))

    # ── Step 10: Save pre-listen snapshot ────────────────────────────────────
    log.info("Step 8: Saving pre-listen snapshot...")

    snapshot = create_snapshot(track_metadata, offered_tracks)
    save_snapshot(cache_dir / "pre_listen_snapshot.json", snapshot)
    log.info("  Saved snapshot with %d tracks.", len(snapshot))

    # ── Step 11: Save offered features ───────────────────────────────────────
    # offered_tracks contains lowercased keys, but candidate_features uses
    # original casing. Build a lowercase->original mapping from ranked.
    lower_to_original = {name.lower(): name for _, name in ranked}
    offered_artist_names = {a for a, _ in offered_tracks}
    offered_features = {}
    for artist_lower in offered_artist_names:
        original = lower_to_original.get(artist_lower, artist_lower)
        if original in candidate_features:
            offered_features[original] = candidate_features[original]

    features_path = cache_dir / "offered_features.json"
    with open(features_path, "w", encoding="utf-8") as fh:
        json.dump({"round": current_round, "features": offered_features}, fh, indent=2)
    log.info("  Saved features for %d artists to %s", len(offered_features), features_path)

    # ── Step 12: Write explanation report ────────────────────────────────────
    log.info("Step 9: Writing explanation report...")

    explanation_lines = [
        f"Adaptive Discovery — Round {current_round}",
        f"Playlist: {playlist_name}",
        f"Alpha: {args.alpha}",
        f"Candidates scored: {len(candidate_scores)}",
        f"Playlist size: {len(top_artists)} artists",
        "",
    ]

    model_weights = learner._weights

    for i, (score, artist) in enumerate(top_artists, 1):
        details = candidate_details.get(artist, {})
        features = candidate_features.get(artist, {})
        explanation = generate_explanation(
            artist=artist,
            final_score=score,
            model_score=details.get("model_score", 0.0),
            affinity_mm=details.get("affinity_mm", 0.0),
            affinity_lfm=details.get("affinity_lfm", 0.0),
            feature_dict=features,
            weights=model_weights,
        )
        explanation_lines.append(f"#{i}")
        explanation_lines.append(explanation)
        explanation_lines.append("")

    explanation_path = cache_dir / "playlist_explanation.txt"
    with open(explanation_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(explanation_lines))
    log.info("  Saved explanation to %s", explanation_path)

    log.info("\nBuild complete. Round %d playlist ready for listening.", current_round)


def _collect_feedback_round(round_id, before_snapshot, after_snapshot,
                            raw_features, all_offered_tracks):
    """Process snapshot diffs into a FeedbackRound.

    Args:
        round_id: Identifier for this feedback round (e.g. date string).
        before_snapshot: Pre-listen snapshot dict.
        after_snapshot: Post-listen snapshot dict.
        raw_features: {artist: {signal: value}} feature vectors from build phase.
        all_offered_tracks: List of (artist, track) tuples offered this session.

    Returns:
        FeedbackRound with artist_feedback and raw_features for artists with feedback.
    """
    from feedback import diff_snapshot, aggregate_artist_feedback, FeedbackRound

    diffs = diff_snapshot(before_snapshot, after_snapshot)
    artist_feedback = aggregate_artist_feedback(diffs, all_offered_tracks)
    # Only include features for artists that had feedback
    round_features = {}
    for artist in artist_feedback:
        if artist in raw_features:
            round_features[artist] = raw_features[artist]
    return FeedbackRound(
        round_id=round_id,
        artist_feedback=artist_feedback,
        raw_features=round_features,
    )


def _run_feedback(cache_dir: pathlib.Path, args):
    """Feedback mode: collect listening feedback, update graph, refit model."""
    from datetime import datetime, timezone

    from music_discovery import parse_library_jxa, collect_track_metadata_jxa
    from feedback import (
        load_snapshot, create_snapshot, save_snapshot,
        diff_snapshot, aggregate_artist_feedback, FeedbackRound,
        load_feedback_history, save_feedback_history,
    )
    from affinity_graph import AffinityGraph, DISCOVERY_HALF_LIFE_DAYS, LIBRARY_HALF_LIFE_DAYS

    log.info("=== Feedback Mode ===")

    # ── 1. Load pre-listen snapshot ──────────────────────────────────────────
    snapshot_path = cache_dir / "pre_listen_snapshot.json"
    before_snapshot = load_snapshot(snapshot_path)
    if not before_snapshot:
        log.error("No pre-listen snapshot found at %s. Run --build first.", snapshot_path)
        return
    log.info("Loaded pre-listen snapshot: %d tracks.", len(before_snapshot))

    # ── 2. Collect current track metadata ────────────────────────────────────
    log.info("Collecting current track metadata from Apple Music...")
    track_metadata = collect_track_metadata_jxa()
    log.info("  Got %d tracks.", len(track_metadata))

    # ── 3. Build "after" snapshot scoped to offered tracks ───────────────────
    offered_keys = set(before_snapshot.keys())
    after_snapshot = create_snapshot(track_metadata, offered_keys)
    log.info("  After snapshot: %d tracks matched.", len(after_snapshot))

    # ── 4–5. Diff and aggregate ──────────────────────────────────────────────
    all_offered_tracks = list(before_snapshot.keys())

    # ── 6. Load raw features ─────────────────────────────────────────────────
    features_path = cache_dir / "offered_features.json"
    raw_features: dict = {}
    if features_path.exists():
        with open(features_path, encoding="utf-8") as fh:
            features_payload = json.load(fh)
        raw_features = features_payload.get("features", {})
    log.info("  Loaded features for %d artists.", len(raw_features))

    # ── 7. Determine round_id ────────────────────────────────────────────────
    round_id = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if getattr(args, "rescan", False):
        # rescan flag can optionally carry a date; if just True, use today
        round_id = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    feedback_round = _collect_feedback_round(
        round_id, before_snapshot, after_snapshot, raw_features, all_offered_tracks
    )

    # ── 8. Save to feedback history (idempotent) ─────────────────────────────
    history_path = cache_dir / "feedback_history.json"
    history = load_feedback_history(history_path)
    history = save_feedback_history(history_path, history, feedback_round)
    log.info("  Saved feedback round '%s' (%d rounds total).", round_id, len(history))

    # ── 9. Log summary ───────────────────────────────────────────────────────
    for artist, fb in sorted(feedback_round.artist_feedback.items()):
        faves = fb.get("fave_tracks", 0)
        skips = fb.get("skip_tracks", 0)
        listens = fb.get("listen_tracks", 0)
        offered = fb.get("tracks_offered", 0)
        log.info("  %s: %d fav, %d skip, %d listen (of %d offered)",
                 artist, faves, skips, listens, offered)

    # ── 10. Update affinity graph ────────────────────────────────────────────
    log.info("Updating affinity graph...")
    overrides = load_overrides(cache_dir / "artist_overrides.json")
    expunged = set()
    for entry in overrides.get("expunged_feedback", []):
        # Entries are "round_id:artist" strings
        if isinstance(entry, str) and ":" in entry:
            expunged.add(entry)

    graph = AffinityGraph.load(cache_dir / "affinity_graph.json")
    graph.reset_injections()

    # Inject library favorites
    favorites = parse_library_jxa()
    for artist, fav_count in favorites.items():
        graph.inject_feedback(artist, fave_count=fav_count, days_ago=0.0,
                              half_life_days=LIBRARY_HALF_LIFE_DAYS)

    # Replay ALL feedback rounds, skipping expunged entries
    current_round = len(history)
    for rnd_idx, rnd in enumerate(history):
        rnd_id = rnd.get("round_id", "0")
        try:
            rnd_num = int(rnd_id)
            rnd_days_ago = max(0.0, (current_round - rnd_num) * 14)
        except (ValueError, TypeError):
            # Date-based round IDs: compute days from today
            try:
                rnd_date = datetime.fromisoformat(rnd_id).replace(
                    tzinfo=timezone.utc
                )
                rnd_days_ago = max(
                    0.0,
                    (datetime.now(timezone.utc) - rnd_date).total_seconds() / 86400,
                )
            except (ValueError, TypeError):
                rnd_days_ago = 90.0

        for artist, fb in rnd.get("artist_feedback", {}).items():
            expunge_key = f"{rnd_id}:{artist}"
            if expunge_key in expunged:
                log.debug("  Skipping expunged: %s", expunge_key)
                continue
            graph.inject_feedback(
                artist,
                fave_count=fb.get("fave_tracks", 0),
                skip_count=fb.get("skip_tracks", 0),
                listen_count=fb.get("listen_tracks", 0),
                tracks_offered=fb.get("tracks_offered", 1),
                days_ago=rnd_days_ago,
                half_life_days=DISCOVERY_HALF_LIFE_DAYS,
            )

    graph.propagate()
    graph.prune()
    graph.save(cache_dir / "affinity_graph.json")
    log.info("  Affinity graph updated and saved.")

    # ── 11. Refit model on ALL accumulated training data ─────────────────────
    log.info("Refitting model on accumulated feedback...")
    all_features = []
    all_labels = []

    for rnd in history:
        rnd_id = rnd.get("round_id", "0")
        rnd_features = rnd.get("raw_features", {})
        for artist, fb in rnd.get("artist_feedback", {}).items():
            expunge_key = f"{rnd_id}:{artist}"
            if expunge_key in expunged:
                continue
            if artist not in rnd_features or not rnd_features[artist]:
                continue
            all_features.append(rnd_features[artist])
            label = 1 if fb.get("fave_tracks", 0) > 0 else 0
            all_labels.append(label)

    if all_features:
        learner_path = cache_dir / "model_weights.json"
        try:
            learner = WeightLearner.load(learner_path)
        except (FileNotFoundError, ValueError):
            learner = WeightLearner()
        learner.fit(all_features, all_labels)
        learner.save(learner_path)
        log.info("  Model refit on %d examples (%d positive, %d negative).",
                 len(all_labels), sum(all_labels), len(all_labels) - sum(all_labels))
    else:
        log.info("  No training data available — model not updated.")

    # ── 12. Diff library-wide favorites ──────────────────────────────────────
    log.info("Checking for new library-wide favorites...")
    lib_faves_path = cache_dir / "library_faves_snapshot.json"
    old_lib_faves: dict = {}
    if lib_faves_path.exists():
        with open(lib_faves_path, encoding="utf-8") as fh:
            old_lib_faves = json.load(fh)

    current_lib_faves = favorites  # already collected above
    # Detect new favorites (artists with higher counts, or newly appeared)
    discovery_artists = set()
    for rnd in history:
        discovery_artists.update(rnd.get("artist_feedback", {}).keys())

    new_lib_faves_injected = 0
    for artist, count in current_lib_faves.items():
        old_count = old_lib_faves.get(artist, 0)
        if count > old_count and artist not in discovery_artists:
            delta = count - old_count
            graph.inject_feedback(
                artist, fave_count=delta, days_ago=0.0,
                half_life_days=LIBRARY_HALF_LIFE_DAYS,
            )
            new_lib_faves_injected += 1

    if new_lib_faves_injected > 0:
        graph.propagate()
        graph.save(cache_dir / "affinity_graph.json")
        log.info("  Injected %d new library favorites into graph.", new_lib_faves_injected)
    else:
        log.info("  No new library favorites detected.")

    # Save current library faves snapshot
    with open(lib_faves_path, "w", encoding="utf-8") as fh:
        json.dump(current_lib_faves, fh, indent=2)

    # ── 13. Replace pre-listen snapshot with current state ───────────────────
    save_snapshot(snapshot_path, after_snapshot)
    log.info("  Updated pre-listen snapshot with current state.")

    log.info("\nFeedback processing complete.")


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

    # Configure only our logger — avoid duplicating handlers from music_discovery
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False

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
