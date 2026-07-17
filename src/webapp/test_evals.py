"""
test_evals.py — the gold eval harness guards itself (F0: A1 + A2).

The load-bearing test: the deterministic fallback must pass EVERY golden case
on every push (the $0 CI regression guard for the LLM surfaces).
"""

from __future__ import annotations

from .evalset import (
    format_report,
    grade_case,
    load_golden,
    run_baseline,
    run_golden,
)
from .rag import _parse_llm_json


def test_golden_set_loads_and_is_versioned():
    cases = load_golden()
    assert len(cases) >= 15                       # the card's n≈15 floor
    assert {c["kind"] for c in cases} == {"ask", "classify"}
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids))              # unique ids


def test_fallback_passes_every_golden_case():
    report = run_golden(force_fallback=True)
    assert report["passed"] == report["total"], "\n" + format_report("fallback", report)


def test_force_fallback_neutralizes_local_llm_route(monkeypatch):
    # K0 tripwire: a dev box's WEBAPP_LLM_MODEL=ollama:* needs no API key, so
    # popping only the key left the "deterministic" run on the LLM path. With
    # BOTH routes armed, force_fallback must still measure the fallback only.
    monkeypatch.setenv("WEBAPP_LLM_MODEL", "ollama:fake-model:0b")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    report = run_golden(force_fallback=True)
    assert report["passed"] == report["total"]
    # "fallback" + "none" (archetype-missing early return) are the only
    # legitimate non-LLM sources; "llm" here = the guard is de-calibrated.
    assert set(report["sources"]) <= {"fallback", "none"}
    assert "llm" not in report["sources"]


def test_baseline_scores_below_fallback_on_citing():
    """The constant baseline must fail must_cite — proof the check carries skill."""
    base = run_baseline()
    assert base["by_check"]["must_cite"]["pass"] == 0
    assert base["passed"] < base["total"]
    # …while trivially passing the invention guard (why we disaggregate).
    assert base["by_check"]["no_invention"]["pass"] == base["by_check"]["no_invention"]["total"]


def test_grader_catches_a_wrong_answer():
    case = {"id": "x", "kind": "ask",
            "expect": {"must_cite": ["Iron Harbor"], "must_not_cite": ["Drake"]}}
    good = grade_case(case, "Iron Harbor anchors your listening.")
    assert good["passed"]
    invented = grade_case(case, "You listen to Iron Harbor and Drake.")
    assert not invented["passed"] and not invented["checks"]["no_invention"]
    missing = grade_case(case, "You like loud music.")
    assert not missing["passed"] and not missing["checks"]["must_cite"]
    markdown = grade_case(case, "**Iron Harbor** rules.")
    assert not markdown["passed"] and not markdown["checks"]["plain_prose"]


def test_grader_wrong_archetype_fails():
    case = {"id": "x", "kind": "classify",
            "expect": {"archetype": "The Anchored Loyalist", "must_cite": [],
                       "must_not_cite": []}}
    assert grade_case(case, "text", name="The Anchored Loyalist")["passed"]
    assert not grade_case(case, "text", name="The Roaming Eclectic")["passed"]


# ── the A2 JSON parser ─────────────────────────────────────────────────────
def test_parse_llm_json_plain_and_fenced():
    assert _parse_llm_json('{"answer": "hi"}') == {"answer": "hi"}
    fenced = 'Here you go:\n```json\n{"thoughts": "t", "answer": "a", "cited": []}\n```'
    assert _parse_llm_json(fenced)["answer"] == "a"


def test_parse_llm_json_failures_return_none():
    assert _parse_llm_json("") is None
    assert _parse_llm_json("no json here") is None
    assert _parse_llm_json('{"broken": ') is None
    assert _parse_llm_json('["a", "list"]') is None
