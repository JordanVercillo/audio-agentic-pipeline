"""
conftest.py — test-session hygiene for the LLM env routes.

config.py load_dotenv()s the gitignored .env at import, so a dev box's LIVE
model config (WEBAPP_LLM_MODEL / WEBAPP_TOOLS_LLM_MODEL = ollama:…) leaks into
the test process and silently routes "deterministic" tests at a live server —
the journal #34 / K0 tripwire, now with the K2d tools route as a THIRD door.

This autouse fixture neutralizes BOTH model routes before every test, so the
suite's default is the hosted model with no key = the deterministic fallback,
identical on a bare CI box and a fully-configured dev box. A test that WANTS a
model sets it via monkeypatch AFTER this fixture runs (fixtures precede the
test body), so explicit setups are unaffected.
"""

import pytest


@pytest.fixture(autouse=True)
def _neutralize_live_llm_routes(monkeypatch):
    for var in ("WEBAPP_LLM_MODEL", "WEBAPP_TOOLS_LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)
