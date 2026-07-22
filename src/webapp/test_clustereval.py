"""
test_clustereval.py — the K3 cluster-description eval set guards itself.

The load-bearing test: the deterministic template must pass EVERY cluster case
on every push (the $0 CI guard); the name-only baseline must fail
grounded_in_centroid — proof that check carries the skill.
"""

from __future__ import annotations

from .clustereval import (
    format_report,
    grade_cluster_case,
    load_golden_clusters,
    run_cluster_baseline,
    run_cluster_golden,
)


def test_cluster_set_loads_and_is_versioned():
    cases = load_golden_clusters()
    assert len(cases) >= 8
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids))
    # the set exercises the corners: a Mixed cluster and a single-dim label
    assert any(not c["cluster"]["dims"] for c in cases)
    assert any(len(c["cluster"]["dims"]) == 1 for c in cases)


def test_template_fallback_passes_every_cluster_case():
    report = run_cluster_golden(force_fallback=True)
    assert report["passed"] == report["total"], \
        "\n" + format_report("cluster fallback", report)


def test_force_fallback_neutralizes_live_routes_for_clusters(monkeypatch):
    # journal-#34 discipline, same tripwire as the taste set: armed env routes
    # must not leak the LLM path into the $0 guard.
    monkeypatch.setenv("WEBAPP_LLM_MODEL", "ollama:fake-model:0b")
    monkeypatch.setenv("WEBAPP_TOOLS_LLM_MODEL", "ollama:fake-tools:0b")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    report = run_cluster_golden(force_fallback=True)
    assert report["passed"] == report["total"]
    assert "llm" not in report["sources"]


def test_name_only_baseline_fails_grounding_only():
    base = run_cluster_baseline()
    assert base["by_check"]["grounded_in_centroid"]["pass"] == 0
    assert base["passed"] < base["total"]
    # …while trivially passing the invention guard (why we disaggregate)
    assert (base["by_check"]["no_invention"]["pass"]
            == base["by_check"]["no_invention"]["total"])


def test_cluster_grader_has_teeth():
    case = {"id": "x",
            "cluster": {"label": "Loud · Fast",
                        "dims": [{"feature": "rms_mean", "word": "Loud", "z": 1.8},
                                 {"feature": "tempo_bpm", "word": "Fast", "z": 1.2}]},
            "expect": {"canonical_name": "Loud · Fast",
                       "must_cite": ["Loud", "Fast"],
                       "must_not_cite": ["quiet", "Drake"]}}
    good = grade_cluster_case(case, {
        "label": "Loud · Fast",
        "description": "These tracks run Loud and Fast against the library."})
    assert good["passed"]
    renamed = grade_cluster_case(case, {
        "label": "Bangers", "description": "Loud and Fast tracks."})
    assert not renamed["passed"] and not renamed["checks"]["canonical_name_preserved"]
    ungrounded = grade_cluster_case(case, {
        "label": "Loud · Fast", "description": "High-energy favorites."})
    assert not ungrounded["passed"] and not ungrounded["checks"]["grounded_in_centroid"]
    contradicts = grade_cluster_case(case, {
        "label": "Loud · Fast",
        "description": "Loud and Fast, never quiet."})
    assert not contradicts["passed"] and not contradicts["checks"]["no_invention"]
    markdown = grade_cluster_case(case, {
        "label": "Loud · Fast", "description": "**Loud** and Fast."})
    assert not markdown["passed"] and not markdown["checks"]["plain_prose"]


def test_mixed_case_grades_without_grounding_check():
    case = {"id": "m", "cluster": {"label": "Mixed", "dims": []},
            "expect": {"canonical_name": "Mixed", "must_cite": [],
                       "must_not_cite": ["Muse"]}}
    res = grade_cluster_case(case, {"label": "Mixed",
                                    "description": "A varied set of tracks."})
    assert res["passed"] and "grounded_in_centroid" not in res["checks"]
