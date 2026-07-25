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
# The one public host this app serves. The www→apex redirect matches ONLY
# www.<this> — never an arbitrary Host header (that would be an open redirect).
CANONICAL_HOST = os.environ.get("WEBAPP_CANONICAL_HOST", "vercilloanalytics.com")
# Least privilege, but grouped so the gate + the privacy copy derive from ONE
# source (never a second hard-coded list). BASE = the always-needed top-items
# read; PLAYLIST = Epic I (playlist import) — adding it forces every existing
# pilot user to re-consent on next login (their old token lacks these scopes).
BASE_SCOPES = ("user-top-read",)
PLAYLIST_SCOPES = ("playlist-read-private", "playlist-read-collaborative")
SCOPES = " ".join(BASE_SCOPES + PLAYLIST_SCOPES)

# Load-bearing throughput guard (Epic I / D-41): extraction is ~50 s/track,
# serial on one worker, so a playlist import is capped to this many tracks —
# a TOTAL, enforced by slicing before enqueue (the fetcher's `limit` is only a
# page size). 100 ≈ 83 min worst-case worker time. Config-tunable.
# How many NEW tracks one Analyze click queues. 0 = no cap.
#
# Restored to 100 (owner, 2026-07-25) after uncapping caused Spotify throttling —
# but the cap is no longer the whole story. The real cost was the FETCH: the
# import drained every page of a playlist (21 API calls for 1004 tracks) merely
# to decide which 100 to queue, so uncapping and capping were equally expensive
# upstream. The import now stops paging once it has this many new tracks, which
# is what makes a 1000-track playlist importable at all.
PLAYLIST_IMPORT_CAP = int(os.environ.get("WEBAPP_PLAYLIST_IMPORT_CAP", "50"))
# Hard ceiling on API calls per Analyze click, whatever the cap. 50 items/page,
# so this is at most ~6 calls — reliability over speed (owner, 2026-07-25:
# "I want to ensure reliability over speed, I can keep importing as we go").
# Without it, a click that finds only already-known tracks would page to the end
# of a 1000-track playlist looking for something new.
PLAYLIST_IMPORT_MAX_PAGES = int(os.environ.get("WEBAPP_PLAYLIST_MAX_PAGES", "6"))

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
    """Optional — enables Anthropic LLM RAG answers. Absent → local Ollama
    (if WEBAPP_LLM_MODEL=ollama:…) or the deterministic fallback."""
    return os.environ.get("ANTHROPIC_API_KEY") or None


# The RAG model. `ollama:<name>` routes to the local Ollama server ($0, A3 —
# no key); anything else is an Anthropic model (needs ANTHROPIC_API_KEY).
# Default stays a hosted model so tests/CI never reach for a local server.
def rag_model() -> str:
    return os.environ.get("WEBAPP_LLM_MODEL", "claude-opus-4-8")


# K2d: the model that drives the /chat TOOL LOOP — a security-sensitive surface
# (it reads back attacker-controllable import names inside tool results), so it
# must pass the injection gate 100%. Split from rag_model() because the two
# surfaces want different models: gemma4:e4b (rag_model) is multimodal for K4
# but OBEYS token-injections; qwen3:8b defends them every run. Defaults to
# rag_model() so an un-split single-model setup (tests/CI) just works.
def tools_model() -> str:
    return os.environ.get("WEBAPP_TOOLS_LLM_MODEL") or rag_model()


def ollama_host() -> str:
    """Base URL of the local Ollama server (A3). Override with OLLAMA_HOST."""
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")


def owner_spotify_id() -> str | None:
    """The OWNER's Spotify user id (D-56) — gates the acquisition-repair
    surfaces (paste-a-link / upload-own-audio). Unset → repair is DISABLED
    for everyone (fail closed); set it in the gitignored .env."""
    return os.environ.get("WEBAPP_OWNER_SPOTIFY_ID") or None
