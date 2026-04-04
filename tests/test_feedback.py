# tests/test_feedback.py
"""Tests for the feedback module (snapshots, diff, aggregation, history)."""

import json
import sys
import pathlib
import tempfile
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import feedback as fb


# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_METADATA = [
    {"name": "Blackwater Park", "artist": "Opeth",  "playedCount": 5, "skippedCount": 1, "favorited": True},
    {"name": "He Is",           "artist": "Ghost",  "playedCount": 3, "skippedCount": 0, "favorited": False},
    {"name": "Other",           "artist": "Tool",   "playedCount": 2, "skippedCount": 0, "favorited": False},
]

OFFERED = {("opeth", "blackwater park"), ("ghost", "he is")}


# ── create_snapshot ────────────────────────────────────────────────────────────

def test_create_snapshot_from_track_metadata():
    snapshot = fb.create_snapshot(SAMPLE_METADATA, OFFERED)
    assert ("opeth", "blackwater park") in snapshot
    assert ("ghost", "he is") in snapshot
    assert snapshot[("opeth", "blackwater park")] == {"played": 5, "skipped": 1, "favorited": True}
    assert snapshot[("ghost", "he is")] == {"played": 3, "skipped": 0, "favorited": False}


def test_create_snapshot_filters_to_offered_only():
    snapshot = fb.create_snapshot(SAMPLE_METADATA, OFFERED)
    assert ("tool", "other") not in snapshot
    assert len(snapshot) == 2


def test_create_snapshot_lowercases_keys():
    """Keys must be lowercase even when metadata has mixed-case artist/name."""
    metadata = [{"name": "TOOL TRACK", "artist": "TOOL", "playedCount": 1,
                 "skippedCount": 0, "favorited": False}]
    offered = {("tool", "tool track")}
    snapshot = fb.create_snapshot(metadata, offered)
    assert ("tool", "tool track") in snapshot


# ── diff_snapshot ─────────────────────────────────────────────────────────────

def _make_before_after(
    played_delta=0, skip_delta=0, newly_faved=False
):
    before = {("opeth", "blackwater park"): {"played": 5, "skipped": 1, "favorited": False}}
    after_state = {
        "played": 5 + played_delta,
        "skipped": 1 + skip_delta,
        "favorited": newly_faved,
    }
    after = {("opeth", "blackwater park"): after_state}
    return before, after


def test_diff_snapshot_detects_favorite():
    before, after = _make_before_after(newly_faved=True, played_delta=1)
    diffs = fb.diff_snapshot(before, after)
    assert ("opeth", "blackwater park") in diffs
    assert diffs[("opeth", "blackwater park")]["outcome"] == "favorite"


def test_diff_snapshot_detects_skip():
    before, after = _make_before_after(skip_delta=2)
    diffs = fb.diff_snapshot(before, after)
    assert ("opeth", "blackwater park") in diffs
    result = diffs[("opeth", "blackwater park")]
    assert result["outcome"] == "skip"
    assert result["skip_delta"] == 2


def test_diff_snapshot_detects_listen_no_fave():
    before, after = _make_before_after(played_delta=1)
    diffs = fb.diff_snapshot(before, after)
    assert ("opeth", "blackwater park") in diffs
    assert diffs[("opeth", "blackwater park")]["outcome"] == "listen"


def test_diff_snapshot_presumed_skip_on_no_change():
    """Tracks with no play/skip/fave change are presumed skips (streaming track gap)."""
    before, after = _make_before_after()  # no changes
    diffs = fb.diff_snapshot(before, after)
    assert ("opeth", "blackwater park") in diffs
    assert diffs[("opeth", "blackwater park")]["outcome"] == "presumed_skip"


def test_diff_snapshot_favorite_trumps_skip():
    """If both newly favorited and skip count increased, 'favorite' wins."""
    before, after = _make_before_after(newly_faved=True, skip_delta=1)
    diffs = fb.diff_snapshot(before, after)
    assert diffs[("opeth", "blackwater park")]["outcome"] == "favorite"


# ── aggregate_artist_feedback ─────────────────────────────────────────────────

def test_aggregate_tracks_offered_from_all_offered():
    """tracks_offered must reflect ALL offered tracks, not just those with changes."""
    diffs = {
        ("opeth", "blackwater park"): {"outcome": "favorite"},
    }
    all_offered = [
        ("opeth", "blackwater park"),
        ("opeth", "ghost of perdition"),  # unplayed — no diff entry
        ("ghost", "he is"),
    ]
    result = fb.aggregate_artist_feedback(diffs, all_offered_tracks=all_offered)
    assert result["opeth"]["tracks_offered"] == 2
    assert result["opeth"]["fave_tracks"] == 1
    assert result["ghost"]["tracks_offered"] == 1
    assert result["ghost"]["fave_tracks"] == 0


def test_aggregate_artist_feedback_basic():
    diffs = {
        ("opeth", "blackwater park"): {"outcome": "favorite"},
        ("opeth", "ghost of perdition"): {"outcome": "listen"},
        ("tool", "schism"): {"outcome": "skip", "skip_delta": 1},
    }
    all_offered = [
        ("opeth", "blackwater park"),
        ("opeth", "ghost of perdition"),
        ("tool", "schism"),
    ]
    result = fb.aggregate_artist_feedback(diffs, all_offered_tracks=all_offered)
    assert result["opeth"]["fave_tracks"] == 1
    assert result["opeth"]["listen_tracks"] == 1
    assert result["opeth"]["skip_tracks"] == 0
    assert result["tool"]["skip_tracks"] == 1
    assert result["tool"]["fave_tracks"] == 0


def test_aggregate_artist_feedback_presumed_skip():
    """Presumed skips are counted separately from confirmed skips."""
    diffs = {
        ("opeth", "blackwater park"): {"outcome": "favorite"},
        ("ghost", "he is"): {"outcome": "presumed_skip"},
        ("ghost", "cirice"): {"outcome": "presumed_skip"},
    }
    all_offered = [
        ("opeth", "blackwater park"),
        ("ghost", "he is"),
        ("ghost", "cirice"),
    ]
    result = fb.aggregate_artist_feedback(diffs, all_offered_tracks=all_offered)
    assert result["ghost"]["presumed_skip_tracks"] == 2
    assert result["ghost"]["skip_tracks"] == 0
    assert result["ghost"]["fave_tracks"] == 0


def test_aggregate_artist_feedback_no_all_offered_fallback():
    """Without all_offered_tracks, tracks_offered falls back to diffs count."""
    diffs = {
        ("opeth", "blackwater park"): {"outcome": "favorite"},
        ("opeth", "ghost of perdition"): {"outcome": "listen"},
    }
    result = fb.aggregate_artist_feedback(diffs, all_offered_tracks=None)
    assert result["opeth"]["tracks_offered"] == 2


# ── save_snapshot / load_snapshot ─────────────────────────────────────────────

def test_save_load_snapshot_roundtrip():
    snapshot = {
        ("opeth", "blackwater park"): {"played": 5, "skipped": 1, "favorited": True},
        ("ghost", "he is"): {"played": 3, "skipped": 0, "favorited": False},
    }
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        path = tmp.name

    fb.save_snapshot(path, snapshot)
    loaded = fb.load_snapshot(path)

    assert loaded == snapshot


def test_load_snapshot_missing_file():
    loaded = fb.load_snapshot("/tmp/nonexistent_snapshot_xyz.json")
    assert loaded == {}


# ── feedback history ──────────────────────────────────────────────────────────

def test_feedback_history_idempotency():
    """Saving the same round_id twice must not create a duplicate entry."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        path = tmp.name

    history = fb.load_feedback_history(path)  # empty
    round1 = fb.FeedbackRound(
        round_id="2026-04-01-001",
        artist_feedback={"opeth": {"fave_tracks": 1, "skip_tracks": 0,
                                   "listen_tracks": 0, "tracks_offered": 2}},
        raw_features={},
    )
    history = fb.save_feedback_history(path, history, round1)
    assert len(history) == 1

    # Save same round_id again
    history = fb.save_feedback_history(path, history, round1)
    assert len(history) == 1  # still 1, not 2

    # Reload from disk and check
    reloaded = fb.load_feedback_history(path)
    assert len(reloaded) == 1
    assert reloaded[0]["round_id"] == "2026-04-01-001"


def test_feedback_history_multiple_rounds():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        path = tmp.name

    history = fb.load_feedback_history(path)
    for i in range(3):
        r = fb.FeedbackRound(
            round_id=f"round-{i}",
            artist_feedback={},
            raw_features={},
        )
        history = fb.save_feedback_history(path, history, r)

    assert len(history) == 3
    reloaded = fb.load_feedback_history(path)
    assert len(reloaded) == 3
    assert [r["round_id"] for r in reloaded] == ["round-0", "round-1", "round-2"]


def test_feedback_history_schema_version():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        path = tmp.name

    history = fb.load_feedback_history(path)
    r = fb.FeedbackRound(round_id="r1", artist_feedback={}, raw_features={})
    fb.save_feedback_history(path, history, r)

    with open(path) as fh:
        payload = json.load(fh)
    assert payload.get("schema_version") == 1
