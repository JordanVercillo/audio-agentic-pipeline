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

    if top_share >= 0.70 or len(ordered) == 1:
        breadth = "Loyalist"
        breadth_fact = f"{round(100 * top_share)}% of your top songs live in one sound"
    elif two_share >= 0.85:
        breadth = "Dualist"
        breadth_fact = (f"two sounds cover {round(100 * two_share)}% of your listening")
    else:
        breadth = "Eclectic"
        breadth_fact = f"your songs spread across {len(ordered)} distinct sounds"

    home = labels.get(str(top_cid), f"Cluster {top_cid}")
    motion = _motion_word((drift or {}).get("score"))
    name = f"The {motion} {breadth}" if motion else f"The {breadth}"

    evidence = [f"home sound “{home}” — {round(100 * top_share)}% of your top songs",
                breadth_fact]
    if drift and motion:
        evidence.append(
            f"motion “{motion}” — recent vs all-time σ-shift {drift['score']}")
    for s in signature[:2]:
        evidence.append(f"signature: {s['word']} than the corpus ({s['z']:+.1f}σ)")

    return {"name": name, "home": home, "home_color_id": int(top_cid),
            "breadth": breadth, "motion": motion, "evidence": evidence}
