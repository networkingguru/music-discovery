# signal_analysis.py
"""
Analysis engine for the signal wargaming experiment.

Runs four phases: individual signal profiling (A), ablation (B),
degraded scenarios (C), and recommendation synthesis (D).
"""

import logging
from signal_scoring import (
    ALL_SIGNALS, DEFAULT_WEIGHTS,
    score_candidates_multisignal,
)

log = logging.getLogger("signal_analysis")

TOP_N = 25


def _run_scoring(cache, signals, weights, **kwargs):
    """Convenience wrapper for scoring with given weights."""
    return score_candidates_multisignal(cache, signals, weights, **kwargs)


def _top_names(ranked, n):
    """Extract top N artist names from ranked list."""
    return [name for _, name in ranked[:n]]


def _overlap_pct(list_a, list_b):
    """Percentage of list_a items that appear in list_b."""
    if not list_a:
        return 0.0
    set_b = set(list_b)
    return 100.0 * sum(1 for x in list_a if x in set_b) / len(list_a)


def run_phase_a(cache, signals, top_n=TOP_N, **scoring_kwargs):
    """Phase A: Individual Signal Profiling.
    Runs scoring with each signal solo (weight=1.0, all others 0.0).
    Returns: {signal_name: {"ranked", "unique", "baseline_overlap"}}
    """
    baseline_weights = {s: 0.0 for s in ALL_SIGNALS}
    baseline_weights["favorites"] = 1.0
    baseline_ranked = _run_scoring(cache, signals, baseline_weights, **scoring_kwargs)
    baseline_names = _top_names(baseline_ranked, top_n)

    solo_results = {}
    for sig in ALL_SIGNALS:
        weights = {s: 0.0 for s in ALL_SIGNALS}
        weights[sig] = 1.0
        ranked = _run_scoring(cache, signals, weights, **scoring_kwargs)
        solo_results[sig] = {
            "ranked": ranked,
            "top_names": _top_names(ranked, top_n),
        }

    results = {}
    for sig in ALL_SIGNALS:
        other_names = set()
        for other_sig in ALL_SIGNALS:
            if other_sig != sig:
                other_names.update(solo_results[other_sig]["top_names"])
        unique = [n for n in solo_results[sig]["top_names"] if n not in other_names]
        overlap = _overlap_pct(solo_results[sig]["top_names"], baseline_names)
        results[sig] = {
            "ranked": solo_results[sig]["ranked"],
            "unique": unique,
            "baseline_overlap": overlap,
        }

    return results


def run_phase_b(cache, signals, top_n=TOP_N, **scoring_kwargs):
    """Phase B: Ablation — drop one signal at a time from all-on.
    Returns: {signal_name: {"ranked", "dropped", "entered"}}
    """
    all_on = {s: 1.0 for s in ALL_SIGNALS}
    all_ranked = _run_scoring(cache, signals, all_on, **scoring_kwargs)
    all_names = _top_names(all_ranked, top_n)

    results = {}
    for sig in ALL_SIGNALS:
        weights = {s: 1.0 for s in ALL_SIGNALS}
        weights[sig] = 0.0
        ranked = _run_scoring(cache, signals, weights, **scoring_kwargs)
        ablated_names = _top_names(ranked, top_n)
        dropped = [n for n in all_names if n not in ablated_names]
        entered = [n for n in ablated_names if n not in all_names]
        results[sig] = {
            "ranked": ranked,
            "dropped": dropped,
            "entered": entered,
        }

    return results


SCENARIOS = {
    "baseline": {
        "desc": "Current behavior — favorites only",
        "weights": {"favorites": 1.0, "playcount": 0.0, "playlists": 0.0,
                    "heavy_rotation": 0.0, "recommendations": 0.0},
    },
    "full_signals": {
        "desc": "All signals active at equal weight",
        "weights": {"favorites": 1.0, "playcount": 1.0, "playlists": 1.0,
                    "heavy_rotation": 1.0, "recommendations": 1.0},
    },
    "no_favorites": {
        "desc": "User doesn't favorite — all other signals",
        "weights": {"favorites": 0.0, "playcount": 1.0, "playlists": 1.0,
                    "heavy_rotation": 1.0, "recommendations": 1.0},
    },
    "light_listener": {
        "desc": "Favorites but low engagement — capped play count, no playlists/rotation",
        "weights": {"favorites": 1.0, "playcount": 1.0, "playlists": 0.0,
                    "heavy_rotation": 0.0, "recommendations": 1.0},
        "caps": {"playcount": 5},
    },
    "api_only": {
        "desc": "No local data — only API signals",
        "weights": {"favorites": 0.0, "playcount": 0.0, "playlists": 0.0,
                    "heavy_rotation": 1.0, "recommendations": 1.0},
    },
    "jxa_only": {
        "desc": "No API user token — only local JXA signals",
        "weights": {"favorites": 1.0, "playcount": 1.0, "playlists": 1.0,
                    "heavy_rotation": 0.0, "recommendations": 0.0},
    },
}


def run_phase_c(cache, signals, top_n=TOP_N, **scoring_kwargs):
    """Phase C: Degraded Scenarios."""
    full_weights = SCENARIOS["full_signals"]["weights"]
    full_ranked = _run_scoring(cache, signals, full_weights, **scoring_kwargs)
    full_names = _top_names(full_ranked, top_n)

    results = {}
    for name, scenario in SCENARIOS.items():
        caps = scenario.get("caps", {})
        ranked = _run_scoring(cache, signals, scenario["weights"],
                              caps=caps, **scoring_kwargs)
        scenario_names = _top_names(ranked, top_n)
        results[name] = {
            "desc": scenario["desc"],
            "ranked": ranked,
            "weights": scenario["weights"],
            "caps": caps,
            "full_overlap": _overlap_pct(scenario_names, full_names),
        }

    return results


def run_phase_d(cache, signals, top_n=TOP_N, **scoring_kwargs):
    """Phase D: Synthesize 3-5 recommended weight configurations."""
    baseline_weights = {"favorites": 1.0, "playcount": 0.0, "playlists": 0.0,
                        "heavy_rotation": 0.0, "recommendations": 0.0}
    baseline_ranked = _run_scoring(cache, signals, baseline_weights, **scoring_kwargs)
    baseline_names = _top_names(baseline_ranked, top_n)

    phase_a = run_phase_a(cache, signals, top_n=top_n, **scoring_kwargs)

    active_signals = set()
    for sig in ALL_SIGNALS:
        data = phase_a[sig]
        if len(data["ranked"]) > 0:
            active_signals.add(sig)

    recommendations = [
        {
            "name": "Favorites-Heavy",
            "rationale": "Favorites dominate, with play count as secondary confirmation. "
                         "Best for users who actively favorite songs.",
            "weights": {"favorites": 1.0, "playcount": 0.3, "playlists": 0.1,
                        "heavy_rotation": 0.1, "recommendations": 0.1},
        },
        {
            "name": "Engagement-Balanced",
            "rationale": "Balances explicit preference (favorites) with engagement depth "
                         "(play count, playlists). Good all-around default.",
            "weights": {"favorites": 1.0, "playcount": 0.5, "playlists": 0.3,
                        "heavy_rotation": 0.2, "recommendations": 0.2},
        },
        {
            "name": "Engagement-Heavy",
            "rationale": "Play count and playlists weighted nearly as high as favorites. "
                         "Surfaces artists the user listens to heavily even without favoriting.",
            "weights": {"favorites": 0.8, "playcount": 0.8, "playlists": 0.5,
                        "heavy_rotation": 0.3, "recommendations": 0.2},
        },
        {
            "name": "No-Favorites Fallback",
            "rationale": "Designed for users who never favorite. Play count is primary, "
                         "supplemented by playlists and Apple signals.",
            "weights": {"favorites": 0.0, "playcount": 1.0, "playlists": 0.5,
                        "heavy_rotation": 0.3, "recommendations": 0.3},
        },
        {
            "name": "Discovery-Maximizer",
            "rationale": "Weights all signals equally to maximize breadth. "
                         "Surfaces the widest variety of candidates across all signals.",
            "weights": {"favorites": 1.0, "playcount": 1.0, "playlists": 1.0,
                        "heavy_rotation": 1.0, "recommendations": 1.0},
        },
    ]

    for rec in recommendations:
        for sig in ALL_SIGNALS:
            if sig not in active_signals:
                rec["weights"][sig] = 0.0

    seen = set()
    unique_recs = []
    for rec in recommendations:
        key = tuple(sorted(rec["weights"].items()))
        if key not in seen:
            seen.add(key)
            unique_recs.append(rec)
    recommendations = unique_recs

    for rec in recommendations:
        ranked = _run_scoring(cache, signals, rec["weights"], **scoring_kwargs)
        rec["ranked"] = ranked
        rec_names = _top_names(ranked, top_n)
        rec["baseline_diff"] = {
            "entered": [n for n in rec_names if n not in baseline_names],
            "dropped": [n for n in baseline_names if n not in rec_names],
        }

    return recommendations
