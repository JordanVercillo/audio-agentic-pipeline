"""
run_injection.py — K2a gate: run the prompt-injection set through the LIVE tool
loop and exit non-zero unless 100% of attacks are defended (never averaged).

    WEBAPP_LLM_MODEL=ollama:gemma4:e4b uv run python evals/run_injection.py

Needs a real model (the attack lives in tool RESULTs — the deterministic
fallback never runs the loop, so there is nothing to inject). Without one, it
says so and exits 0 (nothing was tested — a skip, not a pass).
"""

import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.webapp.injectionset import format_injection_report, run_injection  # noqa: E402
from src.webapp.rag import TasteRAG  # noqa: E402

if __name__ == "__main__":
    rag = TasteRAG()
    if not rag._wants_llm():
        print("no model configured (set WEBAPP_LLM_MODEL=ollama:… or ANTHROPIC_API_KEY) "
              "— the injection set needs the tool loop; SKIPPING (not a pass).")
        sys.exit(0)
    with tempfile.TemporaryDirectory() as td:
        summary = run_injection(rag, Path(td))
    print(f"model: {rag.model}")
    print(format_injection_report(summary))
    sys.exit(0 if summary["passed"] else 1)
