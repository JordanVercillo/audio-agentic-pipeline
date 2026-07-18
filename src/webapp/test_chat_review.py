"""
test_chat_review.py — the D-47 review flywheel (pure), synthetic. Guards the
things that matter: honest pre-grades, escaped untrusted text, the K5 counter.
"""

from __future__ import annotations

from . import chat_review


def _row(i, mode, source, *, answer="", cited=None, ctx=""):
    return {"id": i, "mode": mode, "source": source, "parsed_answer": answer,
            "cited_entities": cited or [], "rendered_context": ctx,
            "user_question": "q", "model": "ollama:gemma4:12b", "latency_ms": 30}


def test_stratified_sample_fills_targets_then_spills():
    rows = ([_row(i, "adhoc", "llm") for i in range(12)]
            + [_row(100 + i, "story", "llm") for i in range(3)]
            + [_row(200 + i, "adhoc", "fallback") for i in range(6)])
    picked = chat_review.stratified_sample(rows, size=20)
    ids = {r["id"] for r in picked}
    assert len(picked) == 20 and len(ids) == 20                 # no dupes
    story = [r for r in picked if r["mode"] == "story"]
    fb = [r for r in picked if r["source"] == "fallback"]
    assert len(story) == 3          # thin stratum contributes all it has, never blocks
    assert len(fb) >= 4             # fallback target met


def test_pre_grade_rewards_real_citations_flags_hallucinated():
    ctx = "Top artists: Iron Harbor; Nova Rills. Taste drift: Major drift."
    real = _row(1, "adhoc", "llm", answer="You lean toward Iron Harbor.",
                cited=["Iron Harbor"], ctx=ctx)
    assert chat_review.pre_grade(real) == {"citation_fidelity": 2, "invention": 0,
                                           "unverified_citations": []}
    # a citation NOT in the context = hallucinated → invention flagged
    fake = _row(2, "adhoc", "llm", answer="Drake is your #1.",
                cited=["Drake is your #1"], ctx=ctx)
    pg = chat_review.pre_grade(fake)
    assert pg["invention"] == 1 and pg["citation_fidelity"] == 0


def test_render_worksheet_escapes_untrusted_text():
    # a track/question with markup must render inert (log text is untrusted)
    evil = _row(1, "adhoc", "llm", answer="ok", cited=["<script>x</script>"], ctx="ctx")
    evil["user_question"] = "<img src=x onerror=alert(1)>"
    card = chat_review.render_worksheet([evil])[0]
    assert "<img" not in card["question"] and "&lt;img" in card["question"]
    assert "<script>" not in card["cited"][0]


def test_aggregate_counts_k5_eligible_and_groups():
    labels = [
        {"mode": "adhoc", "source": "llm", "accuracy": 2, "citation_fidelity": 2,
         "usefulness": 2, "invention": 0, "verdict": "good"},
        {"mode": "adhoc", "source": "llm", "accuracy": 1, "citation_fidelity": 1,
         "usefulness": 2, "invention": 0, "verdict": "fixable-prompt"},
        {"mode": "story", "source": "fallback", "accuracy": 2, "citation_fidelity": 2,
         "usefulness": 1, "invention": 1, "verdict": "bad"},  # invention → NOT k5-eligible
    ]
    rep = chat_review.aggregate(labels)
    assert rep["graded"] == 3 and rep["k5_eligible"] == 1     # only the clean row counts
    assert rep["by_group"]["adhoc/llm"]["n"] == 2
    assert rep["by_group"]["adhoc/llm"]["accuracy"] == 1.5
    assert rep["verdicts"] == {"good": 1, "fixable-prompt": 1, "bad": 1}
