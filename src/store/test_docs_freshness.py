"""Q9/Q11 - the public docs may not state a number that is no longer true.

`README.md` and `docs/CASE_STUDY.md` are the two documents a stranger reads
first. On 2026-07-31 they carried TEN wrong numbers between them: 579 tests
when the suite had 930, 771 analyzed tracks when the corpus held 1,946, 731
sourced when 1,894 were, a decision log stated as D-1..D-57 when it ran to
D-73. Not one of them was wrong when written. Every one rotted, because a
number typed into prose has no relationship to the thing it describes.

Journal #60: a fix that is a command, not a trigger, regresses on schedule.
Retyping the numbers would have reset the clock on exactly the same failure, so
`scripts/docs_facts.py` derives them from the live system and this test fails
the build when the docs disagree.

The check is SKIPPED when the live cache is absent (a fresh clone, or CI without
the gitignored `data/`), because the corpus counts genuinely cannot be derived
there - the alternative is a test that fails for everyone who has not yet run
the pipeline. The claims that do NOT need the cache (test count, decision log)
are asserted unconditionally, so CI still guards the two that rot fastest.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "docs_facts.py"


def _facts() -> dict:
    import json

    out = subprocess.run([sys.executable, str(SCRIPT), "--json"],
                         capture_output=True, text=True, cwd=ROOT, timeout=900)
    assert out.returncode == 0, f"docs_facts.py failed:\n{out.stderr}"
    return json.loads(out.stdout)


def test_docs_state_no_number_that_is_no_longer_true():
    """The whole guard: run the checker, fail with WHICH claim drifted."""
    out = subprocess.run([sys.executable, str(SCRIPT), "--check"],
                         capture_output=True, text=True, cwd=ROOT, timeout=900)
    stale = [ln for ln in (out.stdout or "").splitlines() if ln.startswith("STALE:")]
    assert out.returncode == 0, (
        "the public docs state numbers that are no longer true:\n  "
        + "\n  ".join(stale)
        + "\n\nFix (regenerate, do not retype): "
          "uv run python scripts/docs_facts.py --apply")


def test_the_facts_are_actually_derived_not_defaulted():
    """A checker that derives nothing passes vacuously.

    `_q()` swallows sqlite errors and returns 0, which is right for a fresh
    clone and wrong as a silent answer - a mistyped column name once derived a
    confident `sourced_tracks: 0` while 1,896 rows sat in the table. If the
    cache is present, the counts it feeds must be non-zero and internally
    consistent.
    """
    facts = _facts()

    # These never need the cache.
    assert facts.get("tests", 0) > 500, (
        f"test count did not derive: {facts.get('tests')!r}")
    assert facts.get("highest_decision", 0) >= 73, (
        f"decision log did not derive: {facts.get('highest_decision')!r}")

    if not (ROOT / "data" / "feature_cache.db").exists():
        pytest.skip("no live cache - corpus counts cannot be derived here")

    for key in ("analyzed_tracks", "cached_tracks", "artists", "with_isrc",
                "sourced_tracks"):
        assert facts.get(key, 0) > 0, f"{key} derived as 0 with a cache present"

    # Internal consistency: you cannot have analyzed more tracks than you hold,
    # nor have sourced more than you analyzed.
    assert facts["analyzed_tracks"] <= facts["cached_tracks"]
    assert facts["sourced_tracks"] <= facts["cached_tracks"]


def test_the_checker_can_actually_fail():
    """A guard nobody has seen fail is a comment (journal #44).

    Drives the checker against a doc whose number is deliberately wrong and
    asserts it says so - without touching the real files.
    """

    sys.path.insert(0, str(ROOT / "scripts"))
    import docs_facts  # noqa: PLC0415

    # Derived, NOT hard-coded: writing `{"tests": 930}` here would rot the
    # moment a test was added - the exact disease this file exists to catch,
    # reproduced inside the test that catches it. (It did, immediately.)
    facts = _facts()
    rules = [("README.md", r"(\d[\d,]*) synthetic-data tests", "tests", "test count")]
    real_rules, real_root = docs_facts.RULES, docs_facts.ROOT
    try:
        docs_facts.RULES = rules
        findings = docs_facts.audit(facts, apply=False)
        assert findings == [], "the real README should be clean right now"

        facts_wrong = {"tests": 1}          # pretend the source moved
        findings = docs_facts.audit(facts_wrong, apply=False)
        assert findings, "the checker did not notice a disagreeing number"
        assert "test count" in findings[0]
    finally:
        docs_facts.RULES, docs_facts.ROOT = real_rules, real_root
