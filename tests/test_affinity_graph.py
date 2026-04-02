# tests/test_affinity_graph.py
"""Tests for the affinity_graph module."""

import math
import sys
import pathlib
import tempfile
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from affinity_graph import (
    AffinityGraph,
    HOP_DECAY,
    SKIP_STRENGTH,
    LISTEN_PENALTY,
    MAX_LISTEN_PENALTY,
    _recency_factor,
    LIBRARY_HALF_LIFE_DAYS,
)


# ── Edge management ────────────────────────────────────────────────────────────

def test_add_edges_musicmap():
    g = AffinityGraph()
    g.add_edge_musicmap("a", "b", 0.8)
    assert g.neighbors_musicmap("a") == {"b": 0.8}
    assert g.neighbors_musicmap("b") == {"a": 0.8}


def test_add_edges_lastfm():
    g = AffinityGraph()
    g.add_edge_lastfm("x", "y", 0.6)
    assert g.neighbors_lastfm("x") == {"y": 0.6}
    assert g.neighbors_lastfm("y") == {"x": 0.6}


# ── inject_feedback ────────────────────────────────────────────────────────────

def test_inject_feedback_single_fave():
    g = AffinityGraph()
    val = g.inject_feedback("opeth", fave_count=1, days_ago=0)
    assert abs(val - 1.0) < 1e-9


def test_inject_feedback_multi_fave_sqrt():
    g = AffinityGraph()
    val = g.inject_feedback("opeth", fave_count=9, days_ago=0)
    assert abs(val - 3.0) < 1e-9


def test_inject_feedback_skip_attenuated():
    """1 skip, 1 track offered → attenuation = 1/3."""
    g = AffinityGraph()
    val = g.inject_feedback("opeth", skip_count=1, tracks_offered=1, days_ago=0)
    expected = -(1 * SKIP_STRENGTH * (1 / 3.0))
    assert abs(val - expected) < 1e-9


def test_inject_feedback_skip_full_strength():
    """1 skip, 3 tracks offered → attenuation = 3/3 = 1.0."""
    g = AffinityGraph()
    val = g.inject_feedback("opeth", skip_count=1, tracks_offered=3, days_ago=0)
    expected = -(1 * SKIP_STRENGTH * 1.0)
    assert abs(val - expected) < 1e-9


def test_inject_feedback_first_listen_neutral():
    """1 listen, no fave → net = 0."""
    g = AffinityGraph()
    val = g.inject_feedback("opeth", listen_count=1, days_ago=0)
    assert abs(val) < 1e-9


def test_inject_feedback_second_listen_negative():
    """3 listens → (3-1) * -0.1 = -0.2."""
    g = AffinityGraph()
    val = g.inject_feedback("opeth", listen_count=3, days_ago=0)
    expected = -(2 * LISTEN_PENALTY)
    assert abs(val - expected) < 1e-9


def test_inject_feedback_mixed_net():
    """2 faves + 1 skip (3 tracks) → sqrt(2) - SKIP_STRENGTH."""
    g = AffinityGraph()
    val = g.inject_feedback("opeth", fave_count=2, skip_count=1, tracks_offered=3, days_ago=0)
    expected = math.sqrt(2) - SKIP_STRENGTH
    assert abs(val - expected) < 1e-9


def test_inject_feedback_accumulates():
    """Two calls must accumulate, not overwrite."""
    g = AffinityGraph()
    g.inject_feedback("opeth", fave_count=1, days_ago=0)
    g.inject_feedback("opeth", fave_count=4, days_ago=0)
    # Should be 1.0 + 2.0 = 3.0
    assert abs(g._injections["opeth"] - 3.0) < 1e-9


def test_reset_injections():
    g = AffinityGraph()
    g.inject_feedback("opeth", fave_count=1, days_ago=0)
    g.inject_feedback("ghost", fave_count=1, days_ago=0)
    g.reset_injections()
    assert g._injections == {}


# ── propagate ─────────────────────────────────────────────────────────────────

def test_propagate_single_hop():
    """Source → neighbor: signal = injection * HOP_DECAY * edge_weight."""
    g = AffinityGraph()
    g.add_edge_musicmap("src", "n1", 1.0)
    g._injections["src"] = 1.0

    result = g.propagate(max_hops=1)
    mm = result["musicmap"]
    expected = 1.0 * HOP_DECAY * 1.0
    assert abs(mm["n1"] - expected) < 1e-9
    # lastfm has no edges → no scores
    assert result["lastfm"] == {}


def test_propagate_two_hops():
    """src → a → b: signal decays through two hops."""
    g = AffinityGraph()
    g.add_edge_musicmap("src", "a", 1.0)
    g.add_edge_musicmap("a", "b", 1.0)
    g._injections["src"] = 1.0

    result = g.propagate(max_hops=2)
    mm = result["musicmap"]
    # hop1: src→a = 1.0 * HOP_DECAY * 1.0
    # hop2: a→b  = (1.0 * HOP_DECAY) * HOP_DECAY * 1.0
    expected_a = HOP_DECAY
    expected_b = HOP_DECAY ** 2
    assert abs(mm["a"] - expected_a) < 1e-9
    assert abs(mm["b"] - expected_b) < 1e-9


def test_propagate_max_3_hops():
    """4th hop gets nothing."""
    g = AffinityGraph()
    for pair in [("src", "a"), ("a", "b"), ("b", "c"), ("c", "d")]:
        g.add_edge_musicmap(pair[0], pair[1], 1.0)
    g._injections["src"] = 1.0

    result = g.propagate(max_hops=3)
    mm = result["musicmap"]
    assert "a" in mm
    assert "b" in mm
    assert "c" in mm
    # d is 4 hops away, must not appear (or have 0 score)
    assert mm.get("d", 0.0) == 0.0


def test_propagate_separate_sources():
    """Returns dict with both 'musicmap' and 'lastfm' keys."""
    g = AffinityGraph()
    g.add_edge_musicmap("src", "mm_neighbor", 1.0)
    g.add_edge_lastfm("src", "lf_neighbor", 1.0)
    g._injections["src"] = 1.0

    result = g.propagate(max_hops=1)
    assert "musicmap" in result
    assert "lastfm" in result
    assert "mm_neighbor" in result["musicmap"]
    assert "lf_neighbor" in result["lastfm"]
    # Cross-source contamination must not occur
    assert "lf_neighbor" not in result["musicmap"]
    assert "mm_neighbor" not in result["lastfm"]


# ── recency decay ─────────────────────────────────────────────────────────────

def test_recency_decay():
    """Feedback from half_life days ago should be decayed by ~0.5."""
    g = AffinityGraph()
    val = g.inject_feedback(
        "opeth",
        fave_count=1,
        days_ago=LIBRARY_HALF_LIFE_DAYS,
        half_life_days=LIBRARY_HALF_LIFE_DAYS,
    )
    # exp(-ln(2)) = 0.5
    assert abs(val - 0.5) < 1e-6


# ── prune ─────────────────────────────────────────────────────────────────────

def test_prune_removes_cold_nodes():
    """Edges below threshold are removed; orphan nodes are dropped."""
    g = AffinityGraph()
    g.add_edge_musicmap("a", "b", 0.9)   # kept
    g.add_edge_musicmap("b", "c", 0.05)  # pruned (below 0.1)

    g.prune(min_edge_weight=0.1)

    assert "a" in g.neighbors_musicmap("b") or "b" in g.neighbors_musicmap("a")
    # c should have been pruned away entirely
    assert "c" not in g.nodes


# ── boundary / cap tests ──────────────────────────────────────────────────────

def test_inject_feedback_listen_penalty_capped():
    """Many listens cap at MAX_LISTEN_PENALTY, not accumulating unboundedly."""
    g = AffinityGraph()
    val = g.inject_feedback("opeth", listen_count=100, days_ago=0)
    # negative_listen = min((100-1)*0.1, 0.5) = 0.5
    assert abs(val - (-MAX_LISTEN_PENALTY)) < 1e-9


def test_inject_feedback_zero_tracks_offered():
    """tracks_offered=0 → attenuation=0 → skip contributes nothing."""
    g = AffinityGraph()
    val = g.inject_feedback("opeth", skip_count=5, tracks_offered=0, days_ago=0)
    assert abs(val) < 1e-9


# ── save / load roundtrip ─────────────────────────────────────────────────────

def test_save_load_roundtrip():
    """Graph topology (edges) survives a save/load cycle."""
    g = AffinityGraph()
    g.add_edge_musicmap("opeth", "porcupine tree", 0.75)
    g.add_edge_lastfm("opeth", "steven wilson", 0.6)
    # Inject some feedback — must NOT be persisted
    g.inject_feedback("opeth", fave_count=4, days_ago=0)

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        path = tmp.name

    g.save(path)
    g2 = AffinityGraph.load(path)

    assert g2.neighbors_musicmap("opeth") == {"porcupine tree": 0.75}
    assert g2.neighbors_musicmap("porcupine tree") == {"opeth": 0.75}
    assert g2.neighbors_lastfm("opeth") == {"steven wilson": 0.6}
    # Injections must NOT be persisted
    assert g2._injections == {}
