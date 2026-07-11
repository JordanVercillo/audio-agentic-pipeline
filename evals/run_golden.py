"""
run_golden.py — grade the LLM surfaces against the gold eval set (F0/A1).

    uv run python evals/run_golden.py            # deterministic fallback (the CI guard)
    uv run python evals/run_golden.py --llm      # ALSO grade the live LLM path (needs key)

Exit code 1 if the fallback path fails any golden case.
"""

import argparse
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.webapp.evalset import (  # noqa: E402
    format_report,
    load_golden,
    run_baseline,
    run_golden,
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gold eval set for /ask + /classify.")
    parser.add_argument("--llm", action="store_true",
                        help="also grade the live LLM path (WEBAPP_LLM_MODEL=ollama:… or ANTHROPIC_API_KEY)")
    args = parser.parse_args()

    cases = load_golden()
    fallback = run_golden(cases, force_fallback=True)
    print(format_report("deterministic fallback", fallback))
    print()
    print(format_report("constant baseline (honesty anchor)", run_baseline(cases)))

    if args.llm:
        from src.webapp.rag import TasteRAG
        rag = TasteRAG()
        if not rag._wants_llm():
            print("\n--llm requested but no model configured "
                  "(set WEBAPP_LLM_MODEL=ollama:… or ANTHROPIC_API_KEY); skipping.")
        else:
            print()
            llm = run_golden(cases, force_fallback=False)
            print(format_report(f"LLM path ({rag.model})", llm))

    sys.exit(0 if fallback["passed"] == fallback["total"] else 1)
