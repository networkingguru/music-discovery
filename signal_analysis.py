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
