"""
run_webapp.py — launch the P8 pilot locally (SPEC P8).

    uv run python scripts/run_webapp.py       # http://127.0.0.1:8000

Needs SPOTIPY_CLIENT_ID + SESSION_SECRET_KEY in .env (gitignored). The
redirect URI http://127.0.0.1:8000/callback must be registered on the Spotify
app. No client secret is used (D-8).
"""

import sys
from pathlib import Path

import uvicorn

# Force UTF-8 stdout/stderr. The reused pipeline code (e.g. fetchers) prints
# emoji status lines; on Windows the default cp1252 console can't encode them,
# which would crash a request mid-flight (journal: the Windows-stdout gremlin).
# Linux/Cloud Run defaults to UTF-8 already, so this is a no-op there.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):  # not a reconfigurable TextIO
        pass

# Repo root on sys.path so `src.webapp...` imports resolve (this is an app, not
# an installed package — pyproject `package = false`; scripts insert the root).
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

if __name__ == "__main__":
    # Warm the local LLM(s) in the background (A3) so the first /ask isn't a
    # ~90 s cold load — no-op unless the model is ollama:… ; never blocks
    # startup. K2d split: warm BOTH the primary (story/classify) and the tool
    # model when they differ. On a 12 GB card the two can't stay co-resident, so
    # warm the TOOL model LAST — the /chat tool loop is the latency-sensitive
    # surface, and keep_alive holds whichever was touched most recently.
    import threading

    from src.webapp import config
    from src.webapp.rag import warm_model

    models = [config.rag_model()]
    if config.tools_model() != config.rag_model():
        models.append(config.tools_model())

    def _warm_all():
        for m in models:
            warm_model(m)

    threading.Thread(target=_warm_all, daemon=True).start()

    uvicorn.run("src.webapp.app:app", host="127.0.0.1", port=8000, reload=False)
