"""The explainer set stays navigable and its links stay real.

`docs/HOW_IT_WORKS.md` is the front door for someone with little
data-engineering background; `docs/concepts/*.md` are the deeper pages it links
to. That structure only helps if it holds together, and documentation rots in
two specific ways this file prevents:

  1. **An orphan page** — a concept page nobody links to. It stops being read,
     stops being updated, and starts contradicting the code.
  2. **A dead link** — a page moved or renamed and the reference wasn't
     followed. The reader hits a 404 and loses trust in the whole set.

Neither is caught by a spellchecker or a linter, and neither is visible to
someone reading one page at a time. This is the same reasoning as
`test_docs_freshness.py`, applied to structure instead of numbers: a fix that
is a command ("remember to link the new page") regresses on schedule, so it is
a build failure instead.

Content accuracy is NOT asserted here - no test can check that prose is true.
What is asserted is that the set is reachable, wired together, and honest about
where its numbers come from.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
FRONT_DOOR = DOCS / "HOW_IT_WORKS.md"
CONCEPTS = DOCS / "concepts"

_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _links_in(path: Path) -> list[str]:
    """Relative markdown link targets, minus anchors and external URLs."""
    out = []
    for target in _LINK.findall(path.read_text(encoding="utf-8")):
        target = target.split("#")[0].strip()
        if not target or target.startswith(("http://", "https://", "mailto:")):
            continue
        out.append(target)
    return out


def test_the_front_door_exists_and_is_the_entry_point():
    assert FRONT_DOOR.exists(), "docs/HOW_IT_WORKS.md is the documented entry point"
    text = FRONT_DOOR.read_text(encoding="utf-8")
    assert len(text) > 2000, "the front door got gutted"
    assert "concepts/" in text, "the front door no longer links to any concept page"


def test_every_concept_page_is_linked_from_somewhere():
    """An unlinked page is an unread page, and an unread page goes stale."""
    if not CONCEPTS.is_dir():
        return
    pages = {p.name for p in CONCEPTS.glob("*.md")}
    assert pages, "docs/concepts/ exists but is empty"

    linked: set[str] = set()
    for md in [FRONT_DOOR, *CONCEPTS.glob("*.md")]:
        if not md.exists():
            continue
        for target in _links_in(md):
            name = Path(target).name
            if name in pages and md.name != name:      # a page linking itself doesn't count
                linked.add(name)

    orphans = sorted(pages - linked)
    assert not orphans, (
        f"concept page(s) nothing links to: {orphans}. Link them from "
        "docs/HOW_IT_WORKS.md (or from the page they follow), or delete them - "
        "an unlinked page is one nobody will keep true.")


def test_no_relative_link_in_the_explainer_set_is_dead():
    """A moved file leaves a 404 that no linter catches."""
    dead: list[str] = []
    for md in [FRONT_DOOR, *CONCEPTS.glob("*.md")]:
        if not md.exists():
            continue
        for target in _links_in(md):
            if not (md.parent / target).resolve().exists():
                dead.append(f"{md.relative_to(ROOT).as_posix()} -> {target}")
    assert not dead, "dead relative link(s) in the explainer set:\n  " + "\n  ".join(dead)


def test_every_concept_page_routes_back_to_the_front_door():
    """Someone arriving from a search engine lands mid-set and needs a way up."""
    if not CONCEPTS.is_dir():
        return
    stranded = [p.name for p in CONCEPTS.glob("*.md")
                if "HOW_IT_WORKS.md" not in p.read_text(encoding="utf-8")]
    assert not stranded, (
        f"concept page(s) with no link back to the front door: {stranded}")


def test_the_front_door_says_where_its_numbers_come_from():
    """The explainer states corpus counts. Those are exactly the claims that
    rotted on the README, so the page must point at the generator that keeps
    them true rather than reading as hand-typed."""
    text = FRONT_DOOR.read_text(encoding="utf-8")
    assert "docs_facts.py" in text, (
        "HOW_IT_WORKS.md states numbers without naming the generator that "
        "keeps them current - see test_docs_freshness.py")
