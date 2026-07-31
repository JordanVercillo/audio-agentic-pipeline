"""Q6 - `faiss_store` and `pipeline` are DORMANT, and that must stay deliberate.

The first CI coverage baseline (2026-07-31) reported `src/search/faiss_store.py`
and `src/search/pipeline.py` at 0.0%. That is not a testing gap - nothing
outside `src/search/` imports either one. Live similarity is plain
`math.dist` at `src/store/cache.py:1336`; the FAISS index is a road not taken.

So 88.8% line coverage was partly a measurement artifact: it averaged live code
against code nobody runs. Two ways to fix that honestly - delete the dormant
modules, or state and enforce their dormancy. Deleting is the owner's call
(FAISS is a portfolio-relevant capability), so this states it.

What this file buys: the day something DOES import them, this test fails and
says "you just made untested code live". That converts a silent 0% into a
decision point. It is the same shape as `test_audit_tripwires.py`'s
set-equality - the failure mode being prevented is "it became load-bearing and
nobody noticed".

Also nails down a trap: `test_search.py` defines `run_smoke_test()`, which
pytest never collects because the name does not start with `test_`. It has
therefore never run. That is WHY these modules read 0% while appearing to have
a test beside them.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Modules with no importer outside src/search/. Shrinking this set is progress;
# growing it needs a reason in the commit message.
DORMANT = ("faiss_store", "pipeline")

# Where a live importer would have to appear.
SEARCHED = ("src", "scripts", "spark")


def _importers_of(module: str) -> list[str]:
    """Files outside src/search/ that import `src.search.<module>`."""
    hits: list[str] = []
    for root in SEARCHED:
        base = ROOT / root
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            if rel.startswith("src/search/"):
                continue                    # inside the package: not an importer
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    if mod.endswith(f"search.{module}") or mod == module:
                        hits.append(f"{rel}:{node.lineno}")
                elif isinstance(node, ast.Import):
                    for a in node.names:
                        if a.name.endswith(f"search.{module}"):
                            hits.append(f"{rel}:{node.lineno}")
    return sorted(set(hits))


def test_the_dormant_modules_are_still_dormant():
    """If this fails, the module became live - test it or revert the import."""
    for module in DORMANT:
        importers = _importers_of(module)
        assert not importers, (
            f"src/search/{module}.py is no longer dormant - imported at "
            f"{importers}. It has ~0% test coverage, so it just became "
            f"untested load-bearing code. Either test it or drop the import.")


def test_the_live_one_is_not_in_the_dormant_list():
    """`visualizer` IS live (clustering.py imports compute_umap). Proving the
    detector finds a real importer is what stops this file passing vacuously -
    an `_importers_of` that always returned [] would pass every assertion above."""
    importers = _importers_of("visualizer")
    assert importers, (
        "the importer detector found nothing for a module known to be imported "
        "- the detector is broken, and the dormancy assertions above are vacuous")
    assert any("clustering.py" in i for i in importers), importers


def test_the_packages_own_smoke_file_is_not_a_collected_test():
    """`test_search.py::run_smoke_test` is not named `test_*`, so pytest has
    never collected it. Recorded so nobody reads the filename and assumes the
    package is covered - the honest state is 'a smoke script that must be run
    by hand'."""
    src = (ROOT / "src" / "search" / "test_search.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    collected = [n.name for n in tree.body
                 if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
    assert not collected, (
        f"test_search.py now defines collectable tests {collected} - update "
        "this file's premise, and check whether the dormant modules are now "
        "actually exercised")
