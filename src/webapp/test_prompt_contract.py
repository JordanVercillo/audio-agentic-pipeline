"""
test_prompt_contract.py — the RTCROS contract (D-48). The verify-and-retry
teeth are what the probe demanded; test them directly (synthetic, no LLM).
"""

from __future__ import annotations

from .prompt_contract import (
    PROMPT_VERSION,
    build_system,
    is_empty_reply,
    reply_text,
    verify_citations,
)

_GROUND = ("Taste drift (recent vs all-time): Major drift (genre shift). "
           "Top artists: Nova Rills; Iron Harbor.")


def test_build_system_is_one_encoding_per_mode():
    for mode in ("adhoc", "story", "profile"):
        sys = build_system(mode)
        assert "ROLE:" in sys and "STOP:" in sys and "cited" in sys
        # cited is required BEFORE the answer field (copy-anchoring)
        assert sys.index('"cited"') < sys.index('"' + {
            "adhoc": "answer", "story": "answer", "profile": "narrative"}[mode] + '"')
    assert PROMPT_VERSION == "rtcros-v1"


def test_verify_drops_hallucinated_citations():
    # the probe's exact failure: gemma4 "cited" a paraphrase not in the grounding
    parsed = {"cited": ["Major drift (genre shift or genre new discovery phase)",
                        "Nova Rills"],
              "answer": "Your Nova Rills listening shows change."}
    v = verify_citations(parsed, _GROUND, "adhoc")
    assert "Nova Rills" in v["verified"]                       # real citation kept
    assert all("genre new discovery" not in c for c in v["verified"])  # hallucination dropped


def test_verify_flags_claimed_but_unsaid_citations():
    parsed = {"cited": ["Iron Harbor", "Nova Rills"],
              "answer": "You lean toward Iron Harbor lately."}  # Nova Rills claimed, not said
    v = verify_citations(parsed, _GROUND, "adhoc")
    assert v["ok"] is False and v["missing"] == ["Nova Rills"]


def test_verify_ok_when_answer_contains_its_citations():
    parsed = {"cited": ["Iron Harbor"], "answer": "You lean toward Iron Harbor."}
    assert verify_citations(parsed, _GROUND, "adhoc")["ok"] is True


def test_story_mode_is_flat_answer():
    # K1c: story mode uses the FLAT "answer" field (gemma4 chokes on nested arrays)
    from .prompt_contract import answer_field
    assert answer_field("story") == "answer"
    assert reply_text({"answer": "You run bright, exploring new sounds."}, "story") \
        == "You run bright, exploring new sounds."


def test_reply_text_tolerates_a_sectioned_list():
    # defensive: if a reply ever comes back as sections, join rather than blank
    parsed = {"answer": [{"heading": "Sound", "text": "You run bright."},
                         {"heading": "Drift", "text": "You are exploring."}]}
    txt = reply_text(parsed, "story")
    assert "You run bright." in txt and "You are exploring." in txt


def test_is_empty_reply_guards_blank_and_unparsed():
    assert is_empty_reply(None, "adhoc") is True                 # unparseable
    assert is_empty_reply({"answer": ""}, "adhoc") is True        # blank (the probe's T4)
    assert is_empty_reply({"answer": "ok"}, "adhoc") is False
    assert is_empty_reply({"story": []}, "story") is True         # no sections
