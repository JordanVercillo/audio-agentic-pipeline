"""
build_insights.py — SPEC P2: the insight engine (one command → the narrative)
==============================================================================
Gold layer → artifacts/insights.json + artifacts/INSIGHTS.md.

    python scripts/build_insights.py                # deterministic (default)
    python scripts/build_insights.py --llm-polish   # + LLM executive summary

The deterministic path is primary (SPEC D-5): same warehouse in, same
insights out. --llm-polish adds a prose executive summary via the Claude API
(needs the `anthropic` package + credentials, e.g. ANTHROPIC_API_KEY;
override the model with INSIGHTS_LLM_MODEL) and silently degrades to the
deterministic output on any failure.
"""

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s — %(message)s")


def main() -> None:
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Build taste insights from the gold layer")
    parser.add_argument("--llm-polish", action="store_true",
                        help="Add an LLM-written executive summary (Claude API; "
                             "falls back to deterministic output on any failure)")
    args = parser.parse_args()

    from src.analysis.insights import build_and_write_insights

    print("=" * 60)
    print("  📝 Insight engine (SPEC P2)")
    print("=" * 60)

    insights = build_and_write_insights(polish=args.llm_polish)

    d = insights["drift"]
    print(f"\n   🎯 Drift {d['score']} — {d['label']}")
    print("   ✅ Insights complete\n")


if __name__ == "__main__":
    main()
