"""
chat_review.py — the D-47 review-session flywheel (pure logic).

Sample ungraded ChatLog rows (stratified, deterministic — no RNG), suggest the
verifiable rubric dimensions, render them ESCAPED for a human grader, and
aggregate the graded ChatLabel rows into an aggregates-only report (raw user
text never leaves the gitignored DB — rule 7). The graded rows are the seed for
new golden cases and the K5 adapter dataset (the counter is `k5_eligible`).
"""

from __future__ import annotations

import html
from collections import Counter
from typing import Any, Optional

from .prompt_contract import answer_field, verify_citations

# A review session's strata (chat-analyst consult): a bit of each surface, with
# the rare fallback-degraded turns over-sampled so their honesty gets checked.
_STRATA: list[tuple[Optional[str], Optional[str], int]] = [
    ("story", "llm", 8),
    ("adhoc", "llm", 8),
    (None, "fallback", 4),   # any mode that degraded
]


def _matches(row: dict, mode: Optional[str], source: Optional[str]) -> bool:
    return ((mode is None or row.get("mode") == mode)
            and (source is None or row.get("source") == source))


def stratified_sample(rows: list[dict], size: int = 20) -> list[dict]:
    """Deterministic stratified sample of UNGRADED rows (newest-first input).
    Fill each stratum up to its target, then spill remaining slots latest-first.
    A thin stratum just contributes what it has — the sampler never blocks."""
    picked: list[dict] = []
    seen: set[int] = set()
    for mode, source, target in _STRATA:
        n = 0
        for r in rows:
            if n >= target:
                break
            if r["id"] not in seen and _matches(r, mode, source):
                picked.append(r)
                seen.add(r["id"])
                n += 1
    for r in rows:  # spill to `size` with whatever's left, latest-first
        if len(picked) >= size:
            break
        if r["id"] not in seen:
            picked.append(r)
            seen.add(r["id"])
    return picked[:size]


def pre_grade(row: dict) -> dict[str, Any]:
    """Deterministic SUGGESTIONS the human confirms/overrides — only the
    machine-checkable dimensions (citation fidelity + invention, from
    verify_citations over the row itself). Accuracy + usefulness are human
    judgments and are left blank."""
    mode = row.get("mode") or "adhoc"
    cited = list(row.get("cited_entities") or [])
    parsed = {answer_field(mode): row.get("parsed_answer") or "", "cited": cited}
    v = verify_citations(parsed, row.get("rendered_context") or "", mode)
    n_cited, n_verified = len(cited), len(v["verified"])
    if not cited:
        fidelity: Optional[int] = None                 # nothing claimed → human judges
    elif n_verified == n_cited and v["ok"]:
        fidelity = 2                                    # all citations real AND said
    elif n_verified:
        fidelity = 1                                    # some real, some paraphrased/unsaid
    else:
        fidelity = 0                                    # none of the citations are in the data
    invention = 1 if (cited and n_verified < n_cited) else 0  # a cited string not in the data
    return {"citation_fidelity": fidelity, "invention": invention,
            "unverified_citations": [c for c in cited if c not in v["verified"]]}


def render_worksheet(rows: list[dict]) -> list[dict]:
    """One escaped grading card per row (log text is untrusted — a track named
    `<script>` must render inert). Pre-grades ride along as suggestions."""
    cards = []
    for r in rows:
        cards.append({
            "log_id": r["id"], "mode": r.get("mode"), "source": r.get("source"),
            "model": r.get("model"), "latency_ms": r.get("latency_ms"),
            "question": html.escape(r.get("user_question") or ""),
            "context": html.escape(r.get("rendered_context") or ""),
            "answer": html.escape(r.get("parsed_answer") or ""),
            "cited": [html.escape(str(c)) for c in (r.get("cited_entities") or [])],
            "suggested": pre_grade(r),
        })
    return cards


def _mean(vals: list) -> Optional[float]:
    nums = [v for v in vals if isinstance(v, (int, float))]
    return round(sum(nums) / len(nums), 2) if nums else None


def aggregate(labels: list[dict]) -> dict[str, Any]:
    """Aggregates-only report over graded rows (each label enriched with its
    log's mode+source by the caller). NO raw text — safe to commit to
    evals/runs/. `k5_eligible` = the running counter toward D-46's ≥200-500."""
    total = len(labels)
    by_group: dict[str, dict] = {}
    for lb in labels:
        key = f"{lb.get('mode', '?')}/{lb.get('source', '?')}"
        g = by_group.setdefault(key, {"n": 0, "accuracy": [], "citation_fidelity": [],
                                      "usefulness": [], "invention": 0})
        g["n"] += 1
        for dim in ("accuracy", "citation_fidelity", "usefulness"):
            g[dim].append(lb.get(dim))
        g["invention"] += 1 if lb.get("invention") else 0
    groups = {k: {"n": g["n"], "invention": g["invention"],
                  "accuracy": _mean(g["accuracy"]),
                  "citation_fidelity": _mean(g["citation_fidelity"]),
                  "usefulness": _mean(g["usefulness"])}
              for k, g in sorted(by_group.items())}
    verdicts = dict(Counter(lb.get("verdict") for lb in labels if lb.get("verdict")))
    k5_eligible = sum(1 for lb in labels
                      if lb.get("accuracy") == 2 and lb.get("citation_fidelity") == 2
                      and not lb.get("invention"))
    return {"graded": total, "by_group": groups, "verdicts": verdicts,
            "k5_eligible": k5_eligible, "k5_gate": "200-500 (D-46)"}


def format_report(report: dict, *, prompt_version: str = "?") -> str:
    lines = [f"== chat review -- {report['graded']} graded turns | contract {prompt_version} =="]
    for grp, g in report["by_group"].items():
        lines.append(f"  {grp:16s} n={g['n']:3d}  acc={g['accuracy']}  "
                     f"cite={g['citation_fidelity']}  use={g['usefulness']}  "
                     f"invention={g['invention']}")
    if report["verdicts"]:
        lines.append("  verdicts: " + " | ".join(f"{k} {v}" for k, v in report["verdicts"].items()))
    lines.append(f"  K5 dataset: {report['k5_eligible']} eligible / gate {report['k5_gate']}")
    return "\n".join(lines)
