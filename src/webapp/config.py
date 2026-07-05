"""
config.py — webapp settings from the environment (SPEC P8).

Ground rules honored:
    - NO Spotify client secret anywhere (D-8). Auth uses the public client_id
      + the registered redirect_uri only.
    - `SESSION_SECRET_KEY` is an INFRA credential (it signs the session-id
      cookie) — explicitly NOT the forbidden Spotify secret. Loaded from env /
      gitignored .env; a dev fallback is generated with a loud warning so the
      app can boot in CI/dev without it.

Everything required-at-runtime (the client_id) is read lazily so importing this
module never fails — only calling the getter without the value does.
"""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

logger = logging.getLogger(__name__)

# Load the gitignored .env (same file the pipeline uses) if python-dotenv is present.
try:
    from dotenv import load_dotenv

    _env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:  # pragma: no cover - dotenv is a normal dep
    pass

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# ── Auth (public values only) ──
REDIRECT_URI = os.environ.get("WEBAPP_REDIRECT_URI", "http://127.0.0.1:8000/callback")
# Least privilege: the pilot only needs the visitor's top items.
SCOPES = "user-top-read"

# ── Sessions ──
SESSION_COOKIE = "va_sid"
SESSION_TTL_SECONDS = int(os.environ.get("WEBAPP_SESSION_TTL", "3600"))  # 1h ephemeral

# ── Data ──
MODELED_DIR = _PROJECT_ROOT / "data" / "warehouse" / "modeled"
ARTIFACTS_DIR = _PROJECT_ROOT / "artifacts"

_MISSING_ID_HELP = (
    "SPOTIPY_CLIENT_ID is not set. Put it in the project-root .env (gitignored) "
    "or the environment. It is the PUBLIC client id — not a secret (get it from "
    "https://developer.spotify.com/dashboard)."
)


def get_client_id() -> str:
    """The public Spotify client id (required at /login time)."""
    client_id = os.environ.get("SPOTIPY_CLIENT_ID")
    if not client_id:
        raise RuntimeError(_MISSING_ID_HELP)
    return client_id


def get_session_secret() -> str:
    """
    Cookie-signing key (infra credential). Falls back to an ephemeral
    per-process key in dev/CI with a warning — fine for local runs and tests
    (sessions simply don't survive a restart), never for production.
    """
    key = os.environ.get("SESSION_SECRET_KEY")
    if not key:
        logger.warning(
            "SESSION_SECRET_KEY not set — using an ephemeral per-process key. "
            "Set it in .env for stable local sessions and in the deploy env for prod."
        )
        key = secrets.token_urlsafe(48)
    return key


def anthropic_key() -> str | None:
    """Optional — enables LLM RAG answers (slice 2). Absent → deterministic fallback."""
    return os.environ.get("ANTHROPIC_API_KEY") or None
