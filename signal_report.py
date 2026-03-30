# signal_report.py
"""
Report generation for the signal wargaming experiment.
Produces a formatted markdown report from analysis phase results.
"""

import datetime
from signal_scoring import ALL_SIGNALS

SIGNAL_DISPLAY = {
    "favorites": "Favorites",
    "playcount": "Play Count",
    "playlists": "Playlist Membership",
    "ratings": "Star Ratings",
    "heavy_rotation": "Heavy Rotation",
    "recommendations": "Personal Recs",
}

TOP_N = 25


def _format_ranked(ranked, n=TOP_N):
    lines = []
    for i, (score, name) in enumerate(ranked[:n], 1):
        lines.append(f"  {i:>2}. {name:<35s} ({score:.3f})")
    return "\n".join(lines) if lines else "  (no candidates)"


def _format_weights(weights):
    parts = []
    for sig in ALL_SIGNALS:
        w = weights.get(sig, 0.0)
        if w > 0:
            parts.append(f"{SIGNAL_DISPLAY[sig]}={w}")
    return ", ".join(parts) if parts else "(all zero)"


def generate_wargaming_report(phase_a, phase_b, phase_c, phase_d,
                               library_count=0, top_n=TOP_N):
    lines = []
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    lines.append(f"# Signal Wargaming Results — {date_str}")
    lines.append(f"Library artists: {library_count}")
    lines.append(f"Top N: {top_n}")
    lines.append("")

    # Phase A
    lines.append("## Phase A — Individual Signal Profiling")
    lines.append("")
    lines.append("Each signal run solo (weight=1.0, all others zeroed).")
    lines.append("")
    for sig in ALL_SIGNALS:
        data = phase_a.get(sig, {})
        display = SIGNAL_DISPLAY.get(sig, sig)
        lines.append(f"### {display} (`{sig}`)")
        lines.append(f"Baseline overlap: {data.get('baseline_overlap', 0):.0f}%")
        unique = data.get("unique", [])
        if unique:
            lines.append(f"Unique to this signal: {', '.join(unique)}")
        else:
            lines.append("No unique artists (all appear in other signals' top lists)")
        lines.append(f"\nTop {top_n}:")
        lines.append(_format_ranked(data.get("ranked", []), top_n))
        lines.append("")

    # Phase B
    lines.append("## Phase B — Ablation (drop one signal at a time)")
    lines.append("")
    lines.append("Starting from all signals at weight=1.0, zero one signal per run.")
    lines.append("")
    for sig in ALL_SIGNALS:
        data = phase_b.get(sig, {})
        display = SIGNAL_DISPLAY.get(sig, sig)
        dropped = data.get("dropped", [])
        entered = data.get("entered", [])
        lines.append(f"### Without {display}")
        if not dropped and not entered:
            lines.append("No change to top list — this signal has no marginal impact.")
        else:
            if dropped:
                lines.append(f"Dropped: {', '.join(dropped)}")
            if entered:
                lines.append(f"Entered: {', '.join(entered)}")
        lines.append("")

    # Phase C
    lines.append("## Phase C — Degraded Scenarios")
    lines.append("")
    for scenario_name, data in phase_c.items():
        lines.append(f"### {scenario_name.replace('_', ' ').title()}")
        lines.append(f"*{data.get('desc', '')}*")
        lines.append(f"Weights: {_format_weights(data.get('weights', {}))}")
        caps = data.get("caps", {})
        if caps:
            cap_str = ", ".join(f"{SIGNAL_DISPLAY.get(k,k)} capped at {v}" for k, v in caps.items())
            lines.append(f"Caps: {cap_str}")
        lines.append(f"Overlap with full signals: {data.get('full_overlap', 0):.0f}%")
        lines.append(f"\nTop {top_n}:")
        lines.append(_format_ranked(data.get("ranked", []), top_n))
        lines.append("")

    # Phase D
    lines.append("## Phase D — Recommended Configurations")
    lines.append("")
    for i, rec in enumerate(phase_d, 1):
        lines.append(f"### Option {i}: {rec['name']}")
        lines.append(f"**Rationale:** {rec['rationale']}")
        lines.append(f"**Weights:** {_format_weights(rec['weights'])}")
        diff = rec.get("baseline_diff", {})
        entered = diff.get("entered", [])
        dropped = diff.get("dropped", [])
        if entered:
            lines.append(f"**New vs baseline:** {', '.join(entered)}")
        if dropped:
            lines.append(f"**Dropped vs baseline:** {', '.join(dropped)}")
        lines.append(f"\nTop {top_n}:")
        lines.append(_format_ranked(rec.get("ranked", []), top_n))
        lines.append("")

    return "\n".join(lines)
