"""
Integration tests for the adaptive music discovery feedback loop.

Simulates multiple rounds of user feedback with synthetic data to verify
that the system actually learns preferences over time.
"""

from __future__ import annotations

import sys
import pathlib

# Ensure project root is importable
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from affinity_graph import AffinityGraph
from weight_learner import WeightLearner
from feedback import FeedbackRound, load_feedback_history, save_feedback_history
from adaptive_engine import (
    compute_final_score,
    rank_candidates,
    _collect_feedback_round,
    _normalize_affinity,
    check_cooldown,
)


# ── Fixtures ────────────────────────────────────────────────────────────────────

SIGNAL_NAMES = ["sig_metal", "sig_jazz"]

METAL_SEEDS = [f"metal_seed_{i}" for i in range(5)]
JAZZ_SEEDS = [f"jazz_seed_{i}" for i in range(5)]
METAL_CANDIDATES = [f"metal_cand_{i}" for i in range(5)]
JAZZ_CANDIDATES = [f"jazz_cand_{i}" for i in range(5)]
ALL_CANDIDATES = METAL_CANDIDATES + JAZZ_CANDIDATES


def _build_graph() -> AffinityGraph:
    """Build a graph with metal seeds → metal candidates, jazz seeds → jazz candidates."""
    g = AffinityGraph()
    for seed in METAL_SEEDS:
        for cand in METAL_CANDIDATES:
            g.add_edge_musicmap(seed, cand, 0.8)
    for seed in JAZZ_SEEDS:
        for cand in JAZZ_CANDIDATES:
            g.add_edge_musicmap(seed, cand, 0.8)
    # Cross-genre edges are weak
    for seed in METAL_SEEDS:
        for cand in JAZZ_CANDIDATES:
            g.add_edge_musicmap(seed, cand, 0.1)
    for seed in JAZZ_SEEDS:
        for cand in METAL_CANDIDATES:
            g.add_edge_musicmap(seed, cand, 0.1)
    return g


def _candidate_features(candidate: str) -> dict:
    """Return clearly separable feature vectors: metal candidates high on sig_metal,
    jazz candidates high on sig_jazz."""
    if candidate.startswith("metal_cand"):
        return {"sig_metal": 0.9, "sig_jazz": 0.1}
    else:
        return {"sig_metal": 0.1, "sig_jazz": 0.9}


def _all_candidate_features() -> dict:
    """Features for all 10 candidates."""
    return {c: _candidate_features(c) for c in ALL_CANDIDATES}


def _make_snapshots(favorites, skips, listens, all_offered):
    """Build before/after snapshots to simulate user actions.

    favorites/skips/listens: lists of artist names.
    all_offered: list of artist names offered (each gets a single fake track).
    Returns (before_snapshot, after_snapshot, all_offered_tracks).
    """
    before = {}
    after = {}
    offered_tracks = []

    for artist in all_offered:
        key = (artist, f"track_by_{artist}")
        offered_tracks.append((artist, f"track_by_{artist}"))
        before[key] = {"played": 0, "skipped": 0, "favorited": False}
        # Default: no change
        after[key] = {"played": 0, "skipped": 0, "favorited": False}

    for artist in favorites:
        key = (artist, f"track_by_{artist}")
        after[key] = {"played": 1, "skipped": 0, "favorited": True}

    for artist in skips:
        key = (artist, f"track_by_{artist}")
        after[key] = {"played": 0, "skipped": 1, "favorited": False}

    for artist in listens:
        key = (artist, f"track_by_{artist}")
        after[key] = {"played": 1, "skipped": 0, "favorited": False}

    return before, after, offered_tracks


def _collect_training_data(history_rounds):
    """Extract (feature_dicts, labels) from accumulated history for model refit."""
    feature_dicts = []
    labels = []
    for rnd in history_rounds:
        artist_fb = rnd.get("artist_feedback", {})
        raw_feats = rnd.get("raw_features", {})
        for artist, fb in artist_fb.items():
            feats = raw_feats.get(artist)
            if feats is None:
                continue
            label = 1 if fb.get("fave_tracks", 0) > 0 else 0
            feature_dicts.append(feats)
            labels.append(label)
    return feature_dicts, labels


# ── Tests ────────────────────────────────────────────────────────────────────────


class TestMultiRoundLearning:
    """Simulate 3 rounds of feedback and verify the model adapts."""

    def test_multi_round_learning(self):
        graph = _build_graph()
        all_features = _all_candidate_features()
        history = []

        # ── Round 1: User favorites 2 metal, skips 1 jazz, listens 1 jazz ────
        r1_faves = ["metal_cand_0", "metal_cand_1"]
        r1_skips = ["jazz_cand_0"]
        r1_listens = ["jazz_cand_1"]

        before, after, offered = _make_snapshots(
            r1_faves, r1_skips, r1_listens, ALL_CANDIDATES
        )
        round1 = _collect_feedback_round("1", before, after, all_features, offered)

        # Verify real features were collected (not empty)
        assert round1.raw_features, "Round 1 must have non-empty raw_features"
        for artist in r1_faves + r1_skips + r1_listens:
            assert artist in round1.raw_features, f"Missing features for {artist}"

        # Inject feedback into graph
        graph.reset_injections()
        for artist, fb in round1.artist_feedback.items():
            graph.inject_feedback(
                artist,
                fave_count=fb["fave_tracks"],
                skip_count=fb["skip_tracks"],
                listen_count=fb["listen_tracks"],
                tracks_offered=fb["tracks_offered"],
                days_ago=0.0,
            )

        scores = graph.propagate(max_hops=3)
        mm_scores = scores["musicmap"]
        mm_norm = _normalize_affinity(mm_scores)

        # Metal candidates near favorites should have higher affinity than jazz near skip
        metal_affinities = [mm_norm.get(c, 0.0) for c in METAL_CANDIDATES]
        jazz_affinities = [mm_norm.get(c, 0.0) for c in JAZZ_CANDIDATES]
        avg_metal = sum(metal_affinities) / len(metal_affinities)
        avg_jazz = sum(jazz_affinities) / len(jazz_affinities)
        assert avg_metal > avg_jazz, (
            f"After round 1 metal faves, metal affinity ({avg_metal:.4f}) "
            f"should exceed jazz affinity ({avg_jazz:.4f})"
        )

        history.append({
            "round_id": "1",
            "artist_feedback": round1.artist_feedback,
            "raw_features": round1.raw_features,
        })

        # ── Round 2: User favorites 1 more metal candidate ───────────────────
        r2_faves = ["metal_cand_2"]
        r2_skips = []
        r2_listens = []

        before2, after2, offered2 = _make_snapshots(
            r2_faves, r2_skips, r2_listens, ALL_CANDIDATES
        )
        round2 = _collect_feedback_round("2", before2, after2, all_features, offered2)
        assert round2.raw_features, "Round 2 must have non-empty raw_features"

        history.append({
            "round_id": "2",
            "artist_feedback": round2.artist_feedback,
            "raw_features": round2.raw_features,
        })

        # Refit model on rounds 1 + 2
        feature_dicts, labels = _collect_training_data(history)
        assert len(feature_dicts) > 0, "Must have training data to refit"
        assert 1 in labels and 0 in labels, "Need both positive and negative labels"

        model = WeightLearner(signal_names=SIGNAL_NAMES)
        model.fit(feature_dicts, labels)

        # After training on metal favorites, sig_metal weight should be positive
        # and greater than sig_jazz weight
        metal_idx = SIGNAL_NAMES.index("sig_metal")
        jazz_idx = SIGNAL_NAMES.index("sig_jazz")
        assert model._fitted, "Model must be fitted after round 2"
        assert model._weights[metal_idx] > model._weights[jazz_idx], (
            f"sig_metal weight ({model._weights[metal_idx]:.4f}) should exceed "
            f"sig_jazz weight ({model._weights[jazz_idx]:.4f}) after metal-heavy feedback"
        )

        # Metal candidates should score higher than jazz
        metal_scores_r2 = [model.predict_proba(_candidate_features(c)) for c in METAL_CANDIDATES]
        jazz_scores_r2 = [model.predict_proba(_candidate_features(c)) for c in JAZZ_CANDIDATES]
        assert min(metal_scores_r2) > max(jazz_scores_r2), (
            "After rounds 1-2, every metal candidate should outscore every jazz candidate"
        )

        # ── Round 3: User expands taste — favorites 2 jazz candidates ────────
        r3_faves = ["jazz_cand_2", "jazz_cand_3"]
        r3_skips = []
        r3_listens = []

        before3, after3, offered3 = _make_snapshots(
            r3_faves, r3_skips, r3_listens, ALL_CANDIDATES
        )
        round3 = _collect_feedback_round("3", before3, after3, all_features, offered3)
        assert round3.raw_features, "Round 3 must have non-empty raw_features"

        history.append({
            "round_id": "3",
            "artist_feedback": round3.artist_feedback,
            "raw_features": round3.raw_features,
        })

        # Snapshot jazz scores BEFORE round 3 refit
        jazz_scores_before_r3 = [
            model.predict_proba(_candidate_features(c)) for c in JAZZ_CANDIDATES
        ]

        # Refit on all 3 rounds
        feature_dicts_r3, labels_r3 = _collect_training_data(history)
        model_r3 = WeightLearner(signal_names=SIGNAL_NAMES)
        model_r3.fit(feature_dicts_r3, labels_r3)

        # Jazz candidates should score higher after round 3 than before
        jazz_scores_after_r3 = [
            model_r3.predict_proba(_candidate_features(c)) for c in JAZZ_CANDIDATES
        ]
        avg_jazz_before = sum(jazz_scores_before_r3) / len(jazz_scores_before_r3)
        avg_jazz_after = sum(jazz_scores_after_r3) / len(jazz_scores_after_r3)
        assert avg_jazz_after > avg_jazz_before, (
            f"Jazz scores should increase after round 3 jazz favorites: "
            f"before={avg_jazz_before:.4f}, after={avg_jazz_after:.4f}"
        )

        # sig_jazz weight should have increased (become less negative / more positive)
        assert model_r3._weights[jazz_idx] > model._weights[jazz_idx], (
            f"sig_jazz weight should increase after jazz favorites: "
            f"r2={model._weights[jazz_idx]:.4f}, r3={model_r3._weights[jazz_idx]:.4f}"
        )


class TestCooldownIntegration:
    """Verify cooldown blocks recently-skipped artists and allows them back later."""

    def test_cooldown_blocks_skipped_then_allows(self):
        history = []

        # Round 1: artist_a is skipped, artist_b is favorited
        history.append({
            "round_id": "1",
            "artist_feedback": {
                "artist_a": {"fave_tracks": 0, "skip_tracks": 1, "listen_tracks": 0, "tracks_offered": 1},
                "artist_b": {"fave_tracks": 1, "skip_tracks": 0, "listen_tracks": 0, "tracks_offered": 1},
            },
            "raw_features": {},
        })

        # Favorited artist should NEVER be cooled down
        assert not check_cooldown("artist_b", history, current_round=2, cooldown_rounds=3)
        assert not check_cooldown("artist_b", history, current_round=3, cooldown_rounds=3)

        # Skipped artist should be blocked for rounds 2, 3, 4 (within 3-round cooldown)
        assert check_cooldown("artist_a", history, current_round=2, cooldown_rounds=3)
        assert check_cooldown("artist_a", history, current_round=3, cooldown_rounds=3)
        assert check_cooldown("artist_a", history, current_round=4, cooldown_rounds=3)

        # Round 5: cooldown expired (5 - 1 = 4 > 3)
        assert not check_cooldown("artist_a", history, current_round=5, cooldown_rounds=3)

    def test_cooldown_in_rank_candidates(self):
        """Verify rank_candidates respects cooldown."""
        history = [{
            "round_id": "1",
            "artist_feedback": {
                "skipped_artist": {"fave_tracks": 0, "skip_tracks": 1, "listen_tracks": 0, "tracks_offered": 1},
            },
            "raw_features": {},
        }]

        scores = {"skipped_artist": 0.9, "fresh_artist": 0.5}

        # Round 2: skipped_artist should be cooled down
        ranked = rank_candidates(
            scores,
            history_rounds=history,
            current_round=2,
            cooldown_rounds=3,
        )
        artist_names = [name for _, name in ranked]
        assert "skipped_artist" not in artist_names
        assert "fresh_artist" in artist_names

        # Round 5: cooldown expired, skipped_artist returns
        ranked_later = rank_candidates(
            scores,
            history_rounds=history,
            current_round=5,
            cooldown_rounds=3,
        )
        artist_names_later = [name for _, name in ranked_later]
        assert "skipped_artist" in artist_names_later


class TestFeedbackHistoryPersistence:
    """Verify save/load round-trip and idempotency."""

    def test_save_load_roundtrip(self, tmp_path):
        path = tmp_path / "feedback_history.json"

        rounds = [
            FeedbackRound(
                round_id=str(i),
                artist_feedback={
                    f"artist_{i}": {
                        "fave_tracks": i,
                        "skip_tracks": 0,
                        "listen_tracks": 1,
                        "tracks_offered": 2,
                    }
                },
                raw_features={f"artist_{i}": {"sig_metal": float(i), "sig_jazz": 0.0}},
            )
            for i in range(1, 4)
        ]

        # Save all 3 rounds sequentially
        history = load_feedback_history(path)
        assert history == []

        for rd in rounds:
            history = save_feedback_history(path, history, rd)

        assert len(history) == 3

        # Reload from disk and verify
        loaded = load_feedback_history(path)
        assert len(loaded) == 3
        for i, rnd in enumerate(loaded, start=1):
            assert rnd["round_id"] == str(i)
            assert f"artist_{i}" in rnd["artist_feedback"]
            assert f"artist_{i}" in rnd["raw_features"]
            assert rnd["raw_features"][f"artist_{i}"]["sig_metal"] == float(i)

    def test_idempotent_save(self, tmp_path):
        path = tmp_path / "feedback_history.json"

        rd1 = FeedbackRound(
            round_id="1",
            artist_feedback={"a": {"fave_tracks": 1, "skip_tracks": 0,
                                    "listen_tracks": 0, "tracks_offered": 1}},
            raw_features={"a": {"sig_metal": 1.0}},
        )
        rd2 = FeedbackRound(
            round_id="2",
            artist_feedback={"b": {"fave_tracks": 0, "skip_tracks": 1,
                                    "listen_tracks": 0, "tracks_offered": 1}},
            raw_features={"b": {"sig_jazz": 1.0}},
        )

        history = []
        history = save_feedback_history(path, history, rd1)
        history = save_feedback_history(path, history, rd2)

        # Save round 1 again — should be idempotent
        history = save_feedback_history(path, history, rd1)
        assert len(history) == 2, "Saving round 1 again should not duplicate it"

        loaded = load_feedback_history(path)
        assert len(loaded) == 2
        round_ids = [r["round_id"] for r in loaded]
        assert round_ids == ["1", "2"]


def test_build_loop_skips_previously_offered_tracks(tmp_path):
    """Tracks offered in a prior round are not offered again."""
    from adaptive_engine import _load_offered_tracks, _save_offered_tracks

    offered_path = tmp_path / "offered_tracks.json"
    entries = [{"artist": "fleet foxes", "track": "white winter hymnal", "round": 1}]
    _save_offered_tracks(offered_path, entries)

    offered_set, _ = _load_offered_tracks(offered_path)
    assert ("fleet foxes", "white winter hymnal") in offered_set

    all_tracks = [
        {"name": "White Winter Hymnal", "artist": "Fleet Foxes"},
        {"name": "Mykonos", "artist": "Fleet Foxes"},
    ]
    available = [
        t for t in all_tracks
        if (t["artist"].lower(), t["name"].lower()) not in offered_set
    ]
    assert len(available) == 1
    assert available[0]["name"] == "Mykonos"


def test_build_loop_overflow_past_exhausted_artists(tmp_path):
    """When top artist is exhausted, continues to next artist."""
    from adaptive_engine import _load_offered_tracks, _save_offered_tracks

    offered_path = tmp_path / "offered_tracks.json"
    entries = [
        {"artist": "artist a", "track": "track 1", "round": 1},
        {"artist": "artist a", "track": "track 2", "round": 1},
    ]
    _save_offered_tracks(offered_path, entries)
    offered_set, _ = _load_offered_tracks(offered_path)

    ranked = [(0.9, "artist a"), (0.8, "artist b")]
    artist_tracks = {
        "artist a": [{"name": "Track 1", "artist": "Artist A"}, {"name": "Track 2", "artist": "Artist A"}],
        "artist b": [{"name": "New Song", "artist": "Artist B"}],
    }

    slots_filled = 0
    artist_idx = 0
    target = 2
    filled_artists = []
    while slots_filled < target and artist_idx < len(ranked):
        _, artist = ranked[artist_idx]
        artist_idx += 1
        tracks = artist_tracks.get(artist, [])
        available = [t for t in tracks if (artist, t["name"].lower()) not in offered_set]
        if available:
            slots_filled += 1
            filled_artists.append(artist)

    assert "artist b" in filled_artists
    assert slots_filled == 1


def test_multi_round_no_track_overlap(tmp_path):
    """Simulates 2 rounds and verifies no track is offered twice."""
    from adaptive_engine import _load_offered_tracks, _save_offered_tracks

    offered_path = tmp_path / "offered_tracks.json"

    # Round 1: offer track A
    offered_set, entries = _load_offered_tracks(offered_path)
    assert len(offered_set) == 0

    key = ("fleet foxes", "white winter hymnal")
    offered_set.add(key)
    entries.append({"artist": "fleet foxes", "track": "white winter hymnal", "round": 1})
    _save_offered_tracks(offered_path, entries)

    # Round 2: track A should be filtered
    offered_set2, entries2 = _load_offered_tracks(offered_path)
    assert key in offered_set2

    all_tracks = [
        {"name": "White Winter Hymnal", "artist": "Fleet Foxes"},
        {"name": "Mykonos", "artist": "Fleet Foxes"},
    ]
    available = [t for t in all_tracks if (t["artist"].lower(), t["name"].lower()) not in offered_set2]
    assert len(available) == 1
    assert available[0]["name"] == "Mykonos"


def test_three_strikes_auto_blocklist(tmp_path):
    """Artist with 3 consecutive clean misses is auto-blocklisted."""
    from adaptive_engine import (
        _evaluate_artist_strikes, _auto_blocklist_artist,
        _load_search_strikes, _save_search_strikes,
    )
    from music_discovery import SearchResult

    strikes_path = tmp_path / "search_strikes.json"
    blocklist_path = tmp_path / "ai_blocklist.txt"
    strikes = _load_search_strikes(strikes_path)

    not_found = [SearchResult(None, True)]

    # Rounds 1-2: strikes accumulate
    for rnd in range(1, 3):
        result = _evaluate_artist_strikes(strikes, "ghost artist", not_found, rnd)
        assert result is False

    # Round 3: hits threshold
    result = _evaluate_artist_strikes(strikes, "ghost artist", not_found, 3)
    assert result is True

    _auto_blocklist_artist(blocklist_path, "ghost artist", 3)
    assert "ghost artist" in blocklist_path.read_text()
    _save_search_strikes(strikes_path, strikes)


def test_two_strikes_then_found_resets(tmp_path):
    """Artist found after 2 strikes resets counter."""
    from adaptive_engine import _evaluate_artist_strikes
    from music_discovery import SearchResult

    strikes = {}
    not_found = [SearchResult(None, True)]
    found = [SearchResult("123", True, "Artist", "Track")]

    _evaluate_artist_strikes(strikes, "artist", not_found, 1)
    _evaluate_artist_strikes(strikes, "artist", not_found, 2)
    assert strikes["artist"]["count"] == 2

    _evaluate_artist_strikes(strikes, "artist", found, 3)
    assert strikes["artist"]["count"] == 0
