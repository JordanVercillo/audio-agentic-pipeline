"""
evalset.py — the gold eval harness for the LLM surfaces (VISION_SPECS F0/A1).

Per the KB `gold-eval-sets` card: a fixed, versioned, human-authored set of
taste contexts with machine-checkable expectations, graded DETERMINISTICALLY
(substring/equality — no LLM judge at this size), reported disaggregated and
next to a trivial constant baseline.

The same grader scores both paths:
    - the deterministic fallback (runs in CI at $0 — the regression guard), and
    - the LLM path (run locally when a key is set) via the A2 JSON contract.

Checks per case:
    nonempty      the surface produced an answer at all
    must_cite     every expected entity appears (the grounding contract)
    no_invention  none of the banned entities appear (the invention guard)
    plain_prose   no markdown leaked into visitor-facing text
    archetype     (classify) the deterministic name was preserved exactly
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from .rag import TasteRAG

GOLDEN_PATH = Path(__file__).resolve().parent.parent.parent / "evals" / "golden_taste_v1.jsonl"

_MARKDOWN_TELLS = ("**", "##", "```")
CONSTANT_BASELINE = "You have great taste in music and should keep exploring!"


def load_golden(path: Path = GOLDEN_PATH) -> list[dict]:
    cases = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            cases.append(json.loads(line))
    return cases


def grade_case(case: dict, text: str, name: Optional[str] = None) -> dict:
    """Grade one surface output against a case's expectations. Deterministic."""
    expect = case.get("expect", {})
    low = (text or "").lower()
    checks: dict[str, bool] = {}

    if case["kind"] == "classify" and expect.get("archetype") is None:
        # The graceful-none case: no archetype → no profile, and no invention.
        checks["archetype"] = name is None
        checks["no_invention"] = not any(
            b.lower() in low for b in expect.get("must_not_cite", []))
        return _finish(case, checks)

    checks["nonempty"] = bool((text or "").strip())
    checks["must_cite"] = all(c.lower() in low for c in expect.get("must_cite", []))
    checks["no_invention"] = not any(
        b.lower() in low for b in expect.get("must_not_cite", []))
    checks["plain_prose"] = not any(t in (text or "") for t in _MARKDOWN_TELLS)
    if case["kind"] == "classify":
        checks["archetype"] = name == expect.get("archetype")
    return _finish(case, checks)


def _finish(case: dict, checks: dict[str, bool]) -> dict:
    return {"id": case["id"], "kind": case["kind"], "checks": checks,
            "passed": all(checks.values())}


def run_case(rag: TasteRAG, case: dict) -> dict:
    """Run one case through the real surface and grade the output."""
    if case["kind"] == "ask":
        res = rag.answer(case.get("question", "what's my vibe?"), case["taste"])
        return grade_case(case, res.get("answer", "")) | {"source": res.get("source")}
    res = rag.classify(case["taste"])
    return grade_case(case, res.get("narrative", ""), name=res.get("name")) \
        | {"source": res.get("source")}


def run_golden(cases: Optional[list[dict]] = None, *,
               force_fallback: bool = True) -> dict[str, Any]:
    """Grade every golden case. force_fallback=True neutralizes BOTH LLM routes
    so the deterministic path is what's measured (the CI guard).

    K0 fix: popping only the API key left a hole — a local `.env` with
    `WEBAPP_LLM_MODEL=ollama:…` needs no key, so the "deterministic" run
    silently measured the LLM path (or whatever a down Ollama fell through
    to). Both env routes must be neutralized or the $0 CI guard de-calibrates
    the moment someone runs it on a dev box."""
    cases = cases if cases is not None else load_golden()
    saved: dict[str, Optional[str]] = {}
    if force_fallback:
        for var in ("ANTHROPIC_API_KEY", "WEBAPP_LLM_MODEL"):
            saved[var] = os.environ.pop(var, None)
    try:
        rag = TasteRAG()
        results = [run_case(rag, c) for c in cases]
    finally:
        for var, val in saved.items():
            if val is not None:
                os.environ[var] = val
    return _summarize(results)


def run_baseline(cases: Optional[list[dict]] = None) -> dict[str, Any]:
    """Grade the constant string against every case — the honesty anchor.

    A constant passes plain_prose/no_invention trivially; it can never pass
    must_cite. Reporting it beside the real run shows which checks carry skill.
    """
    cases = cases if cases is not None else load_golden()
    results = [grade_case(c, CONSTANT_BASELINE,
                          name="The Constant" if c["kind"] == "classify" else None)
               for c in cases]
    return _summarize(results)


def _summarize(results: list[dict]) -> dict[str, Any]:
    by_kind: dict[str, dict[str, int]] = {}
    by_check: dict[str, dict[str, int]] = {}
    for r in results:
        k = by_kind.setdefault(r["kind"], {"pass": 0, "total": 0})
        k["total"] += 1
        k["pass"] += 1 if r["passed"] else 0
        for check, ok in r["checks"].items():
            c = by_check.setdefault(check, {"pass": 0, "total": 0})
            c["total"] += 1
            c["pass"] += 1 if ok else 0
    return {"results": results,
            "passed": sum(1 for r in results if r["passed"]),
            "total": len(results),
            "by_kind": by_kind, "by_check": by_check,
            # which path actually answered — the K0 tripwire asserts {"fallback"}
            # under force_fallback (a de-calibrated guard shows "llm" here)
            "sources": sorted({r.get("source") for r in results if r.get("source")}),
            "failures": [r for r in results if not r["passed"]]}


def format_report(title: str, report: dict[str, Any]) -> str:
    lines = [f"== {title}: {report['passed']}/{report['total']} cases pass =="]
    for kind, k in sorted(report["by_kind"].items()):
        lines.append(f"  {kind:9s} {k['pass']}/{k['total']}")
    lines.append("  per check:")
    for check, c in sorted(report["by_check"].items()):
        lines.append(f"    {check:13s} {c['pass']}/{c['total']}")
    for f in report["failures"]:
        bad = [name for name, ok in f["checks"].items() if not ok]
        lines.append(f"  FAIL {f['id']} ({f['kind']}): {', '.join(bad)}")
    return "\n".join(lines)
