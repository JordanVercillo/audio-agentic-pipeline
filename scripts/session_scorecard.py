"""session_scorecard.py — the cheap half of a director review.

Runs the gates that already exist, measures the session's diff, and prints ONE
ledger row for `docs/QUALITY_LEDGER.md`. It asserts nothing new: the
"did you forget a gate" work belongs inside pytest (see
`docs/QUALITY_BAR.md` Q1/Q2), where it fails a build instead of a report.

    uv run python scripts/session_scorecard.py --base <commit>
    uv run python scripts/session_scorecard.py --base HEAD~6 --session 72

The six HAND-entered fields (defect discovery channels) are deliberately not
automated: they are a discipline, not a gate, and the row being visibly empty
when they are skipped is the only thing making them real.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# The box-drawing characters below crash a Windows cp1252 console — the same
# gremlin that bit two other scripts this session. Every CLI here does this.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], **kw) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT,
                           timeout=kw.pop("timeout", 1800), **kw)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as exc:  # noqa: BLE001 — a scorecard must never be the thing that breaks
        return 1, f"{type(exc).__name__}: {exc}"


def _tests() -> tuple[int, str]:
    code, out = _run([sys.executable, "-m", "pytest", "src/", "-q", "-p", "no:warnings",
                      "--tb=no"], env=None)
    n = out.count(".") if code == 0 else -1
    return n, ("PASS" if code == 0 else "FAIL")


def _ruff() -> str:
    code, _ = _run([sys.executable, "-m", "ruff", "check"])
    return "clean" if code == 0 else "ERRORS"


def _audit() -> str:
    code, out = _run([sys.executable, ".claude/skills/warehouse-audit/audit_warehouse.py"])
    try:
        flags = json.loads(out)["flags"]
        true = [k for k, v in flags.items() if v]
        return f"{len(flags) - len(true)}/{len(flags)} false" + (
            f" (TRUE: {', '.join(true)})" if true else "")
    except Exception:  # noqa: BLE001
        return "unreadable"


def _diff_stats(base: str) -> dict:
    _, code_out = _run(["git", "diff", "--numstat", f"{base}..HEAD", "--",
                        "src", "scripts"])
    code = tests = 0
    for line in code_out.splitlines():
        parts = line.split("\t")
        if len(parts) != 3 or not parts[0].isdigit():
            continue
        added, path = int(parts[0]), parts[2]
        if "test_" in path:
            tests += added
        elif path.endswith(".py"):
            code += added
    _, commits = _run(["git", "rev-list", "--count", f"{base}..HEAD"])
    _, files = _run(["git", "diff", "--name-only", f"{base}..HEAD"])
    return {"code_lines": code, "test_lines": tests,
            "commits": commits.strip() or "?",
            "files": len([f for f in files.splitlines() if f.strip()])}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True, help="commit the session started from")
    ap.add_argument("--session", default="?", help="session number for the row")
    ap.add_argument("--skip-tests", action="store_true", help="reuse a known count")
    args = ap.parse_args()

    print("running the gates that already exist…\n")
    d = _diff_stats(args.base)
    n_tests, verdict = (-1, "skipped") if args.skip_tests else _tests()
    ruff = _ruff()
    audit = _audit()

    ratio = (f"{d['test_lines'] / d['code_lines']:.2f}"
             if d["code_lines"] else "n/a")

    print("── scorecard " + "─" * 58)
    print(f"  session      : {args.session}   (base {args.base}..HEAD)")
    print(f"  commits      : {d['commits']}   files touched: {d['files']}")
    print(f"  tests        : {n_tests} ({verdict})")
    print(f"  ruff         : {ruff}")
    print(f"  warehouse    : {audit}")
    print(f"  lines        : +{d['code_lines']} code / +{d['test_lines']} test "
          f"(ratio {ratio})")
    print("─" * 70)
    print("\nledger row (paste into docs/QUALITY_LEDGER.md):\n")
    print(f"| {args.session} | | {d['commits']} | {n_tests} | {ruff} | "
          f"{audit.split(' (')[0]} | +{d['code_lines']}/+{d['test_lines']} | | | |")
    print("\nHAND-ENTER these — they are the honest half (see QUALITY_BAR.md):")
    for code, meaning in (
            ("D-self", "found by the author's own new tests"),
            ("D-matrix", "found by an existing standing gate firing"),
            ("D-build", "found by building on top (pre-existing bug)"),
            ("D-use", "found by USING the live product"),
            ("D-red", "found by a red-team / consult"),
            ("D-post", "found AFTER shipping  <- the only one a user feels")):
        print(f"    {code:9s} _   {meaning}")
    print("\n  measured claims (before -> after + the command that produced both):")
    print("    …")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
