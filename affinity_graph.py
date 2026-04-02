# affinity_graph.py
"""
Affinity graph for adaptive music discovery.

Artist nodes are connected by similarity edges (from music-map.com and Last.fm).
User feedback injects signal that propagates through the graph via BFS, boosting
artists near liked artists and penalizing artists near skipped ones.

Propagation is kept separate per edge source (musicmap vs lastfm) so callers
can apply independent weights.
"""

from __future__ import annotations

import json
import math
import logging
from collections import defaultdict, deque
from pathlib import Path
from typing import Dict

log = logging.getLogger("affinity_graph")

# ── Constants ──────────────────────────────────────────────────────────────────

HOP_DECAY = 0.4
DEFAULT_MAX_HOPS = 3
SKIP_STRENGTH = 0.7
LISTEN_PENALTY = 0.1          # per occurrence after the first
MAX_LISTEN_PENALTY = 0.5
LIBRARY_HALF_LIFE_DAYS = 180
DISCOVERY_HALF_LIFE_DAYS = 90

_SCHEMA_VERSION = 1


# ── Helper: recency factor ─────────────────────────────────────────────────────

def _recency_factor(days_ago: float, half_life_days: float) -> float:
    """Exponential decay: exp(-ln(2)/half_life * days_ago)."""
    if days_ago < 0:
        days_ago = 0.0
    lam = math.log(2) / half_life_days
    return math.exp(-lam * days_ago)


# ── AffinityGraph ──────────────────────────────────────────────────────────────

class AffinityGraph:
    """Graph of artist similarity edges with feedback-driven signal propagation."""

    def __init__(self) -> None:
        # Edge storage: {artist: {neighbor: weight}}
        self._musicmap: Dict[str, Dict[str, float]] = defaultdict(dict)
        self._lastfm:   Dict[str, Dict[str, float]] = defaultdict(dict)
        # Accumulated injection values (cleared by reset_injections)
        self._injections: Dict[str, float] = {}

    # ── Edge management ────────────────────────────────────────────────────────

    @property
    def nodes(self) -> set:
        """All artist nodes present in either edge store."""
        nodes: set = set()
        for store in (self._musicmap, self._lastfm):
            for artist, neighbors in store.items():
                nodes.add(artist)
                nodes.update(neighbors.keys())
        return nodes

    def add_edge_musicmap(self, artist: str, neighbor: str, weight: float) -> None:
        """Add or update a music-map similarity edge (undirected)."""
        self._musicmap[artist][neighbor] = weight
        self._musicmap[neighbor][artist] = weight

    def add_edge_lastfm(self, artist: str, neighbor: str, weight: float) -> None:
        """Add or update a Last.fm similarity edge (undirected)."""
        self._lastfm[artist][neighbor] = weight
        self._lastfm[neighbor][artist] = weight

    def neighbors_musicmap(self, artist: str) -> Dict[str, float]:
        return dict(self._musicmap.get(artist, {}))

    def neighbors_lastfm(self, artist: str) -> Dict[str, float]:
        return dict(self._lastfm.get(artist, {}))

    # ── Injection management ───────────────────────────────────────────────────

    def reset_injections(self) -> None:
        """Clear all accumulated injections. Call at the start of each --build run."""
        self._injections = {}

    def inject_feedback(
        self,
        artist: str,
        fave_count: int = 0,
        skip_count: int = 0,
        listen_count: int = 0,
        tracks_offered: int = 1,
        days_ago: float = 0.0,
        half_life_days: float = LIBRARY_HALF_LIFE_DAYS,
    ) -> float:
        """Compute and accumulate a feedback injection for *artist*.

        Formula:
            positive       = sqrt(fave_count)  if fave_count > 0 else 0.0
            attenuation    = min(tracks_offered, 3) / 3.0
            negative_skip  = skip_count * SKIP_STRENGTH * attenuation
            negative_listen = min(max(0, listen_count - 1) * LISTEN_PENALTY,
                                  MAX_LISTEN_PENALTY)
            net            = positive - negative_skip - negative_listen
            injection      = net * recency_factor(days_ago, half_life_days)

        The first listen (listen_count == 1) contributes 0 negative signal.

        Returns the injection value that was accumulated.
        """
        positive = math.sqrt(fave_count) if fave_count > 0 else 0.0
        attenuation = min(tracks_offered, 3) / 3.0
        negative_skip = skip_count * SKIP_STRENGTH * attenuation
        negative_listen = min(
            max(0, listen_count - 1) * LISTEN_PENALTY,
            MAX_LISTEN_PENALTY,
        )
        net = positive - negative_skip - negative_listen
        recency = _recency_factor(days_ago, half_life_days)
        injection = net * recency

        # Accumulate (not overwrite)
        self._injections[artist] = self._injections.get(artist, 0.0) + injection
        return injection

    # ── Propagation ───────────────────────────────────────────────────────────

    def propagate(
        self,
        max_hops: int = DEFAULT_MAX_HOPS,
    ) -> Dict[str, Dict[str, float]]:
        """Propagate injections through the graph via BFS.

        Returns a dict with two keys:
            {"musicmap": {artist: score}, "lastfm": {artist: score}}

        Each key contains propagated scores from that edge source independently.
        Music-map and Last.fm edges are propagated separately so callers can
        apply independent weights to the returned score dicts.

        For listen-without-fave injections (weaker signal), callers should pass
        max_hops=2 per the spec's 2-hop limit for that signal type.
        """
        mm_scores: Dict[str, float] = {}
        lf_scores: Dict[str, float] = {}

        for source, injection in self._injections.items():
            if injection == 0.0:
                continue
            self._bfs_propagate(source, injection, max_hops, self._musicmap, mm_scores)
            self._bfs_propagate(source, injection, max_hops, self._lastfm, lf_scores)

        return {"musicmap": mm_scores, "lastfm": lf_scores}

    @staticmethod
    def _bfs_propagate(
        source: str,
        injection: float,
        max_hops: int,
        edge_store: Dict[str, Dict[str, float]],
        scores: Dict[str, float],
    ) -> None:
        """BFS from *source*, decaying signal by HOP_DECAY * edge_weight per hop.

        First path wins (visited set prevents double-counting the same source's
        signal via multiple paths — accepted simplification per spec).
        Scores are accumulated across multiple sources.
        """
        # queue entries: (artist, signal_at_this_node, hops_taken)
        visited = {source}
        queue = deque()

        # Seed neighbors of source at hop 1
        for neighbor, weight in edge_store.get(source, {}).items():
            signal = injection * HOP_DECAY * weight
            queue.append((neighbor, signal, 1))
            visited.add(neighbor)

        while queue:
            artist, signal, hops = queue.popleft()
            scores[artist] = scores.get(artist, 0.0) + signal

            if hops < max_hops:
                for neighbor, weight in edge_store.get(artist, {}).items():
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append((neighbor, signal * HOP_DECAY * weight, hops + 1))

    # ── Pruning ───────────────────────────────────────────────────────────────

    def prune(self, min_edge_weight: float = 0.1) -> None:
        """Remove edges below *min_edge_weight* and orphan nodes from both stores."""
        for store in (self._musicmap, self._lastfm):
            to_delete_artists = []
            for artist in list(store.keys()):
                store[artist] = {
                    n: w for n, w in store[artist].items() if w >= min_edge_weight
                }
                if not store[artist]:
                    to_delete_artists.append(artist)
            for artist in to_delete_artists:
                del store[artist]

    # ── Persistence ──────────────────────────────────────────────────────────

    def save(self, path: str | Path) -> None:
        """Persist graph topology (edges only, not injections) to JSON."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "musicmap": {a: dict(neighbors) for a, neighbors in self._musicmap.items()},
            "lastfm":   {a: dict(neighbors) for a, neighbors in self._lastfm.items()},
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        log.debug("Saved affinity graph to %s", path)

    @classmethod
    def load(cls, path: str | Path) -> "AffinityGraph":
        """Load graph topology from JSON. Returns empty graph if file missing."""
        path = Path(path)
        graph = cls()
        if not path.exists():
            log.debug("No affinity graph at %s; starting fresh", path)
            return graph
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        for artist, neighbors in payload.get("musicmap", {}).items():
            for neighbor, weight in neighbors.items():
                graph._musicmap[artist][neighbor] = weight
        for artist, neighbors in payload.get("lastfm", {}).items():
            for neighbor, weight in neighbors.items():
                graph._lastfm[artist][neighbor] = weight
        log.debug("Loaded affinity graph from %s", path)
        return graph
