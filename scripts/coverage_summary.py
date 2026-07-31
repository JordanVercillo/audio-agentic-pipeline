"""coverage_summary.py — print the line-coverage headline + the weakest modules.

Runs in CI after pytest --cov (see .github/workflows/ci.yml). Lives as a script
rather than an inline heredoc because escaping Python inside YAML inside a shell
is how you get a broken build step that still "passes".

Reported, NOT gated: a threshold picked before the baseline is known is theatre.
docs/QUALITY_BAR.md (Q6) owns when that changes.
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPORT = Path("coverage.xml")


def main() -> int:
    if not REPORT.exists():
        print("no coverage.xml — did pytest --cov run?")
        return 0
    root = ET.parse(REPORT).getroot()
    print(f"LINE COVERAGE: {float(root.get('line-rate', 0)) * 100:.1f}%")

    rows = sorted(
        ((float(c.get("line-rate", 0)), c.get("filename", "?")) for c in root.iter("class")),
        key=lambda r: r[0])
    if rows:
        print()
        print("Least-covered modules:")
        for rate, name in rows[:12]:
            print(f"  {rate * 100:5.1f}%  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
