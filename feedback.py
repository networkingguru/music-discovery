# feedback.py
"""
Feedback module: pre/post-listen snapshots, diff, per-artist aggregation, and history.

Used by the adaptive music discovery engine to detect what the user liked, skipped,
or ignored after a listening session.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

log = logging.getLogger("feedback")

# ── Types ──────────────────────────────────────────────────────────────────────

# (artist_lower, track_lower) → {played, skipped, favorited}
Snapshot = Dict[Tuple[str, str], Dict]

# (artist_lower, track_lower) → {outcome, ...}
DiffResult = Dict[Tuple[str, str], Dict]

_SNAPSHOT_SEP = "|||"
_SCHEMA_VERSION = 1


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class FeedbackRound:
    round_id: str
    artist_feedback: Dict  # {artist: {fave_tracks, skip_tracks, listen_tracks, tracks_offered}}
    raw_features: Dict = field(default_factory=dict)


# ── Snapshot helpers ───────────────────────────────────────────────────────────

def create_snapshot(
    track_metadata: List[Dict],
    offered_tracks: Set[Tuple[str, str]],
) -> Snapshot:
    """Build a snapshot dict from JXA track metadata, filtered to offered tracks only.

    Args:
        track_metadata: list of dicts from collect_track_metadata_jxa()
        offered_tracks: set of (artist, track_name) tuples that were offered this session.
                        Both values are lowercased before comparison.

    Returns:
        Dict keyed by (artist_lower, track_lower) with {played, skipped, favorited}.
    """
    # Normalise offered set to lowercase
    normalised_offered: Set[Tuple[str, str]] = {
        (a.lower().strip(), t.lower().strip()) for a, t in offered_tracks
    }

    snapshot: Snapshot = {}
    for track in track_metadata:
        artist = (track.get("artist") or "").lower().strip()
        name = (track.get("name") or "").lower().strip()
        if not artist or not name:
            continue
        key = (artist, name)
        if key not in normalised_offered:
            continue
        snapshot[key] = {
            "played": int(track.get("playedCount") or 0),
            "skipped": int(track.get("skippedCount") or 0),
            "favorited": bool(track.get("favorited") or False),
        }
    return snapshot


def save_snapshot(path: str | Path, snapshot: Snapshot) -> None:
    """Persist a snapshot to JSON.  Keys serialised as 'artist|||track'.

    Args:
        path: file path to write.
        snapshot: dict from create_snapshot().
    """
    serialisable = {
        f"{a}{_SNAPSHOT_SEP}{t}": v
        for (a, t), v in snapshot.items()
    }
    payload = {"schema_version": _SCHEMA_VERSION, "tracks": serialisable}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def load_snapshot(path: str | Path) -> Snapshot:
    """Load a snapshot previously saved by save_snapshot().

    Returns:
        Snapshot dict.  Empty dict if file does not exist.
    """
    p = Path(path)
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as fh:
        payload = json.load(fh)
    tracks = payload.get("tracks", {})
    snapshot: Snapshot = {}
    for composite_key, v in tracks.items():
        parts = composite_key.split(_SNAPSHOT_SEP, 1)
        if len(parts) != 2:
            log.warning("Skipping malformed snapshot key: %r", composite_key)
            continue
        artist, track = parts
        snapshot[(artist, track)] = v
    return snapshot


# ── Diff ──────────────────────────────────────────────────────────────────────

def diff_snapshot(before: Snapshot, after: Snapshot) -> DiffResult:
    """Diff two snapshots taken around a listening session.

    Rules (in priority order):
      1. Newly favorited → "favorite"  (trumps all other signals)
      2. Skip count increased → "skip" with skip_delta
      3. Play count increased (not faved, not skipped) → "listen"
      4. No change → "presumed_skip" (Apple Music doesn't track counts
         for streaming-only playlist tracks, so silence ≈ skip)

    Args:
        before: snapshot taken before the session.
        after: snapshot taken after the session.

    Returns:
        Dict keyed by (artist, track) containing outcome dicts.
    """
    result: DiffResult = {}

    # Only examine tracks present in both snapshots (offered = in before)
    for key, before_state in before.items():
        after_state = after.get(key)
        if after_state is None:
            # Track disappeared from library — skip
            continue

        newly_faved = after_state["favorited"] and not before_state["favorited"]
        skip_delta = after_state["skipped"] - before_state["skipped"]
        play_delta = after_state["played"] - before_state["played"]

        if newly_faved:
            result[key] = {"outcome": "favorite"}
        elif skip_delta > 0:
            result[key] = {"outcome": "skip", "skip_delta": skip_delta}
        elif play_delta > 0:
            result[key] = {"outcome": "listen"}
        else:
            # No change detected — Apple Music doesn't reliably track
            # play/skip counts for streaming-only ("shared") tracks added
            # to playlists.  Treat as a presumed skip so we don't lose
            # half the feedback signal.
            result[key] = {"outcome": "presumed_skip"}

    return result


# ── Aggregation ───────────────────────────────────────────────────────────────

def aggregate_artist_feedback(
    diffs: DiffResult,
    all_offered_tracks: Optional[List[Tuple[str, str]]] = None,
) -> Dict[str, Dict]:
    """Aggregate per-track diffs into per-artist feedback summary.

    Args:
        diffs: output of diff_snapshot().
        all_offered_tracks: ALL (artist, track) tuples offered this session
            (including unplayed ones).  Used to compute correct tracks_offered count.
            If None, falls back to counting only tracks present in diffs.

    Returns:
        {artist: {fave_tracks, skip_tracks, listen_tracks, presumed_skip_tracks, tracks_offered}}
    """
    aggregated: Dict[str, Dict] = {}

    def _ensure(artist: str) -> None:
        if artist not in aggregated:
            aggregated[artist] = {
                "fave_tracks": 0,
                "skip_tracks": 0,
                "listen_tracks": 0,
                "presumed_skip_tracks": 0,
                "tracks_offered": 0,
            }

    # Count outcomes from diffs
    for (artist, _track), info in diffs.items():
        _ensure(artist)
        outcome = info.get("outcome")
        if outcome == "favorite":
            aggregated[artist]["fave_tracks"] += 1
        elif outcome == "skip":
            aggregated[artist]["skip_tracks"] += 1
        elif outcome == "listen":
            aggregated[artist]["listen_tracks"] += 1
        elif outcome == "presumed_skip":
            aggregated[artist]["presumed_skip_tracks"] += 1

    # Compute tracks_offered from all_offered_tracks (authoritative)
    if all_offered_tracks is not None:
        offered_counts: Dict[str, int] = {}
        for artist, _track in all_offered_tracks:
            artist_lower = artist.lower().strip()
            offered_counts[artist_lower] = offered_counts.get(artist_lower, 0) + 1
        # Ensure every offered artist has an entry
        for artist_lower in offered_counts:
            _ensure(artist_lower)
        for artist_lower, cnt in offered_counts.items():
            aggregated[artist_lower]["tracks_offered"] = cnt
    else:
        # Fallback: count offered from diffs only (undercount if unplayed exist)
        for (artist, _track) in diffs:
            aggregated[artist]["tracks_offered"] += 1

    return aggregated


# ── History persistence ────────────────────────────────────────────────────────

def load_feedback_history(path: str | Path) -> List[Dict]:
    """Load feedback history from JSON.

    Returns:
        List of round dicts.  Empty list if file does not exist.
    """
    p = Path(path)
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as fh:
        content = fh.read().strip()
    if not content:
        return []
    payload = json.loads(content)
    return payload.get("rounds", [])


def save_feedback_history(
    path: str | Path,
    history: List[Dict],
    round_data: FeedbackRound,
) -> List[Dict]:
    """Append round_data to history and persist.

    Idempotency: if round_data.round_id already exists in history, skip silently.

    Args:
        path: file path to write.
        history: current history list (from load_feedback_history).
        round_data: FeedbackRound to append.

    Returns:
        Updated history list (same object, mutated in place if appended).
    """
    existing_ids = {r.get("round_id") for r in history}
    if round_data.round_id in existing_ids:
        log.debug("round_id %r already in history — skipping duplicate save", round_data.round_id)
        return history

    entry = {
        "round_id": round_data.round_id,
        "artist_feedback": round_data.artist_feedback,
        "raw_features": round_data.raw_features,
    }
    history.append(entry)

    payload = {"schema_version": _SCHEMA_VERSION, "rounds": history}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

    return history
