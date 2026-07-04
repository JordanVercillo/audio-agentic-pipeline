"""
build_report.py — SPEC P4: the shareable portfolio report (one command)
========================================================================
Fresh gold layer → self-contained artifacts/taste_report.html (< 10 MB,
opens offline, every image inlined).

    python scripts/build_report.py                 # regenerates all inputs first
    python scripts/build_report.py --no-rebuild    # render from existing artifacts
    python scripts/build_report.py --llm-polish    # pass through to the insight step

By default this regenerates every input deterministically (taste map,
insights, trend charts — all fixed-seed), so the report is reproducible from
the warehouse alone: the acceptance criterion is "one command from a fresh
gold layer".
"""

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SCRIPTS_DIR = PROJECT_ROOT / "scripts"

# (script, extra args) — order matters: insights reads cluster_assignments,
# which the taste-map builder writes.
_INPUT_BUILDERS = [
    ("build_taste_map.py", []),
    ("build_insights.py", []),
    ("build_trend_charts.py", []),
]


def main() -> None:
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Build the single-file taste report")
    parser.add_argument("--no-rebuild", action="store_true",
                        help="Render from existing artifacts/ without regenerating")
    parser.add_argument("--llm-polish", action="store_true",
                        help="Pass --llm-polish to the insight step")
    args = parser.parse_args()

    print("=" * 60)
    print("  📦 Portfolio report builder (SPEC P4)")
    print("=" * 60)

    if not args.no_rebuild:
        for script, extra in _INPUT_BUILDERS:
            cmd = [sys.executable, str(SCRIPTS_DIR / script), *extra]
            if script == "build_insights.py" and args.llm_polish:
                cmd.append("--llm-polish")
            print(f"\n▶ {script}")
            result = subprocess.run(cmd, cwd=PROJECT_ROOT)
            if result.returncode != 0:
                print(f"❌ {script} failed (exit {result.returncode}) — aborting report.")
                sys.exit(result.returncode)

    from src.export.portfolio import build_report_html

    print("\n▶ rendering taste_report.html")
    build_report_html()
    print("   ✅ Report complete\n")


if __name__ == "__main__":
    main()
