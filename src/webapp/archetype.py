"""
archetype.py — the deterministic taste archetype (APP_SPEC Epic D).

Classifies a listener from three REAL signals — no model call required (D-5):

    home    — the cluster where most of their songs live (its acoustic label)
    breadth — how concentrated their listening is across clusters
              (Loyalist ≥70% one cluster · Dualist: two clusters ≥85% · Eclectic)
    motion  — the D-9 σ-shift bands (Anchored <0.15 · Drifting <0.35 ·
              Roaming <0.60 · Shape-shifting)

Name = "The {motion} {breadth}", e.g. "The Anchored Loyalist". Every claim in
`evidence` cites a number the dashboard already shows — the LLM narrative
(rag.classify) is grounded on exactly these strings and may not invent others.
"""

from __future__ import annotations

from typing import Any, Optional

_MOTION_BANDS = [(0.15, "Anchored"), (0.35, "Drifting"), (0.60, "Roaming")]
_MOTION_MAX = "Shape-shifting"
_LOYALIST_MIN = 0.70   # one sound ≥70% of top songs → Loyalist
_DUALIST_MIN = 0.85    # top two sounds together ≥85% → Dualist


def _motion_word(score: Optional[float]) -> Optional[str]:
    if score is None:
        return None
    for upper, word in _MOTION_BANDS:
        if score < upper:
            return word
    return _MOTION_MAX


def derive_archetype(per_window_clusters: dict[str, list[int]],
                     labels: dict[str, str],
                     drift: Optional[dict[str, Any]],
                     signature: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Deterministic archetype from cluster assignments + drift + signature.

    per_window_clusters: {"short_term": [cluster_id, ...], ...} (the user's songs).
    Returns None when there's nothing to classify (no assigned songs).
    """
    all_cids = [c for cids in per_window_clusters.values() for c in cids]
    if not all_cids:
        return None

    counts: dict[int, int] = {}
    for c in all_cids:
        counts[c] = counts.get(c, 0) + 1
    total = len(all_cids)
    ordered = sorted(counts.items(), key=lambda kv: -kv[1])
    top_cid, top_n = ordered[0]
    top_share = top_n / total
    two_share = (top_n + (ordered[1][1] if len(ordered) > 1 else 0)) / total

    if top_share >= _LOYALIST_MIN or len(ordered) == 1:
        breadth = "Loyalist"
        breadth_fact = f"{round(100 * top_share)}% of your top songs live in one sound"
    elif two_share >= _DUALIST_MIN:
        breadth = "Dualist"
        breadth_fact = (f"two sounds cover {round(100 * two_share)}% of your listening")
    else:
        breadth = "Eclectic"
        breadth_fact = f"your songs spread across {len(ordered)} distinct sounds"

    home = labels.get(str(top_cid), f"Cluster {top_cid}")
    motion = _motion_word((drift or {}).get("score"))
    name = archetype_name(motion, breadth)

    evidence = [f"home sound “{home}” — {round(100 * top_share)}% of your top songs",
                breadth_fact]
    if drift and motion:
        evidence.append(
            f"motion “{motion}” — recent vs all-time σ-shift {drift['score']}")
    for s in signature[:2]:
        evidence.append(f"signature: {s['word']} than the corpus ({s['z']:+.1f}σ)")

    return {"name": name, "home": home, "home_color_id": int(top_cid),
            "breadth": breadth, "motion": motion, "evidence": evidence}


# ── the taxonomy: single source of truth for the /analytics 12-cell grid ─────
# Plain-language clauses per axis word. Thresholds are NEVER re-typed here — they
# derive from the band / percent constants above, so the reference grid can't
# drift from derive_archetype. Adding a motion/breadth word without a clause here
# trips the taxonomy test loudly (intended tripwire).
_MOTION_DEF = {
    "Anchored": "your recent sound barely moves from your all-time average",
    "Drifting": "your recent sound has edged away from your all-time average",
    "Roaming": "your recent sound has travelled well away from your all-time average",
    "Shape-shifting": "your recent listening looks little like your all-time sound",
}
_BREADTH_DEF = {
    "Loyalist": "one sound owns most of your rotation",
    "Dualist": "two sounds split most of your rotation",
    "Eclectic": "your songs spread across many sounds",
}


def archetype_name(motion: Optional[str], breadth: str) -> str:
    """The archetype's display name — the ONE place the "The {motion} {breadth}"
    format lives, shared by derive_archetype and archetype_taxonomy."""
    return f"The {motion} {breadth}" if motion else f"The {breadth}"


def _motion_rows() -> list[dict[str, Any]]:
    """The 4 motion tiers as ordered rows with human σ-band text, derived from
    _MOTION_BANDS + _MOTION_MAX so the ranges mirror _motion_word (half-open
    [lo, hi) === score < upper)."""
    rows: list[dict[str, Any]] = []
    lo = 0.0
    for hi, word in _MOTION_BANDS:
        band = (f"σ-shift under {hi:g}" if lo == 0.0 else f"σ-shift {lo:g}–{hi:g}")
        rows.append({"word": word, "band": band})
        lo = hi
    rows.append({"word": _MOTION_MAX, "band": f"σ-shift {lo:g} or more"})
    return rows


def _breadth_rows() -> list[dict[str, Any]]:
    """The 3 breadth tiers with the exact rule that earns each — percentages
    derive from _LOYALIST_MIN / _DUALIST_MIN (the SAME constants the classifier
    tests against)."""
    return [
        {"word": "Loyalist",
         "rule": f"one sound is ≥{round(100 * _LOYALIST_MIN)}% of your top songs"},
        {"word": "Dualist",
         "rule": f"your top two sounds together cover ≥{round(100 * _DUALIST_MIN)}%"},
        {"word": "Eclectic", "rule": "no one or two sounds dominate"},
    ]


def archetype_taxonomy() -> dict[str, Any]:
    """The full 4×3 archetype grid + the thresholds that earn each cell.

    Single source of truth for the /analytics taxonomy section: every name,
    σ-band and breadth-rule is DERIVED from the same module constants
    derive_archetype uses, so the reference grid can never disagree with the
    classifier. Pure + deterministic (no args, no I/O). `grid` and `cells`
    share the same cell dicts, so they cannot diverge."""
    motions, breadths = _motion_rows(), _breadth_rows()
    grid: list[dict[str, Any]] = []
    cells: list[dict[str, Any]] = []
    for m in motions:
        row_cells: list[dict[str, Any]] = []
        for b in breadths:
            cell = {"name": archetype_name(m["word"], b["word"]),
                    "motion": m["word"], "breadth": b["word"],
                    "def": f"{_MOTION_DEF[m['word']]}, and {_BREADTH_DEF[b['word']]}."}
            row_cells.append(cell)
            cells.append(cell)
        grid.append({"motion": m, "cells": row_cells})
    return {"breadths": breadths, "grid": grid, "cells": cells}
