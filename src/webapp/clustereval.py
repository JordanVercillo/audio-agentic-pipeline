"""
clustereval.py — the gold eval set for K3 cluster descriptions.

The second-set pattern (like injectionset.py): its own file, cases, and
graders — the input is a cluster (label + the K3a dims that produced it),
not a taste dict, so it does not overload evalset's `kind` machinery. The
summarize/report plumbing is shared.

Checks per case (deterministic substring/equality, no LLM judge):
    canonical_name_preserved  the returned label is byte-equal to the trained
                              name — a SINGLE rename is a D-5 violation
    grounded_in_centroid      every dim word that produced the name appears in
                              the description (skipped for Mixed — no dims to
                              cite, the graceful-none analogue of C15)
    no_invention              no banned string appears: artist names AND the
                              opposite-pole words (a "Loud · Fast" description
                              saying "quiet" contradicts its own centroid)
    plain_prose / nonempty    house checks

The name-only CONSTANT baseline fails grounded_in_centroid while passing the
rest — proving that check is the one that carries skill. The deterministic
template fallback passes everything by construction (it is built from the
dims): that is the $0 CI guard.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from .evalset import _MARKDOWN_TELLS, _summarize, format_report  # noqa: F401 — re-exported
from .rag import TasteRAG

GOLDEN_CLUSTERS_PATH = (Path(__file__).resolve().parent.parent.parent
                        / "evals" / "golden_clusters_v1.jsonl")

# The honesty anchor: a description any cluster could wear. It cites no dims.
CLUSTER_BASELINE = "A distinctive group of tracks in your library."


def load_golden_clusters(path: Path = GOLDEN_CLUSTERS_PATH) -> list[dict]:
    cases = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            cases.append(json.loads(line))
    return cases


def grade_cluster_case(case: dict, result: dict) -> dict:
    """Grade one describe_cluster result. Deterministic."""
    expect = case.get("expect", {})
    text = str(result.get("description") or "")
    low = text.lower()
    checks: dict[str, bool] = {}
    checks["canonical_name_preserved"] = (
        result.get("label") == expect.get("canonical_name"))
    if case.get("cluster", {}).get("dims"):
        checks["grounded_in_centroid"] = all(
            w.lower() in low for w in expect.get("must_cite", []))
    # Mixed: no dims exist to cite — grade the rest (the C15 analogue)
    checks["no_invention"] = not any(
        b.lower() in low for b in expect.get("must_not_cite", []))
    checks["plain_prose"] = not any(t in text for t in _MARKDOWN_TELLS)
    checks["nonempty"] = bool(text.strip())
    return {"id": case["id"], "kind": "cluster", "checks": checks,
            "passed": all(checks.values())}


def run_cluster_case(rag: TasteRAG, case: dict) -> dict:
    res = rag.describe_cluster(case["cluster"])
    return grade_cluster_case(case, res) | {"source": res.get("source")}


def run_cluster_golden(cases: Optional[list[dict]] = None, *,
                       force_fallback: bool = True) -> dict[str, Any]:
    """Grade every cluster case. force_fallback pops ALL live-model env routes
    (the journal-#34 discipline, same three vars as evalset.run_golden) so the
    $0 CI run measures the deterministic template."""
    cases = cases if cases is not None else load_golden_clusters()
    saved: dict[str, Optional[str]] = {}
    if force_fallback:
        for var in ("ANTHROPIC_API_KEY", "WEBAPP_LLM_MODEL", "WEBAPP_TOOLS_LLM_MODEL"):
            saved[var] = os.environ.pop(var, None)
    try:
        rag = TasteRAG()
        results = [run_cluster_case(rag, c) for c in cases]
    finally:
        for var, val in saved.items():
            if val is not None:
                os.environ[var] = val
    return _summarize(results)


def run_cluster_baseline(cases: Optional[list[dict]] = None) -> dict[str, Any]:
    """The name-only constant graded against every case — the honesty anchor."""
    cases = cases if cases is not None else load_golden_clusters()
    results = [grade_cluster_case(
        c, {"label": c["expect"].get("canonical_name"),
            "description": CLUSTER_BASELINE}) for c in cases]
    return _summarize(results)
