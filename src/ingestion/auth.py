"""
auth.py — Spotify OAuth Authentication (2026 Compliant, PKCE-only)
===================================================================
ONE auth flow for the whole project: Authorization Code with PKCE
(per 01_spotify_api_guardrails.md — Implicit Grant is deprecated).

Why PKCE-only (SPEC decision, 2026-07-03):
    - No client secret exists ANYWHERE in this project — not in code, not in
      env, not in deployment. PKCE uses a code_verifier/code_challenge pair.
    - A user-authorized PKCE token can call both user-scoped endpoints
      (/me/top) AND public endpoints (/tracks, /search), so the old
      Client Credentials flow was redundant surface area.
    - This is the same flow the production-pilot webapp needs: any visitor
      authenticates their own Spotify account against our public client_id.

Credential loading priority:
    1. Environment variables (SPOTIPY_CLIENT_ID, SPOTIPY_REDIRECT_URI)
    2. .env file in project root (loaded via python-dotenv)

    There are NO in-code fallbacks (CLAUDE.md ground rule: no secrets in the
    repo). A missing client_id raises immediately with setup instructions.
"""

import os
from pathlib import Path
from typing import Optional

import spotipy
from spotipy.oauth2 import SpotifyPKCE

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CREDENTIAL MANAGEMENT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Attempt to load .env file (optional dependency)
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass  # python-dotenv not installed — rely on env vars or fallbacks

# The redirect URI is a public OAuth convention, not a credential — a
# loopback default is safe and matches the app's dashboard registration.
_DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"

_MISSING_CREDENTIAL_HELP = (
    "Set it as an environment variable or in the project-root .env file "
    "(gitignored). Get the value from your app at "
    "https://developer.spotify.com/dashboard"
)

# ── Scopes ──
# user-top-read:             GET /me/top/{type} — our primary personalization signal
# user-read-playback-state:  GET /me/player — current playback context
# playlist-read-private:     GET /me/playlists — user's private playlists
# playlist-modify-public:    PUT/POST /playlists/{id} — create/modify playlists
# user-library-modify:       PUT /me/library — unified library management
USER_SCOPES = " ".join([
    "user-top-read",
    "user-read-private",
    "user-read-email",
    "user-read-playback-state",
    "user-read-currently-playing",
    "playlist-read-private",
    "playlist-read-collaborative",
    "playlist-modify-public",
    "playlist-modify-private",
    "user-library-modify",
    "user-library-read",
])

# Token cache location — stored alongside this module
_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_PKCE_CACHE_PATH = _CACHE_DIR / ".spotify_pkce_cache"


def _get_client_id() -> str:
    client_id = os.environ.get("SPOTIPY_CLIENT_ID")
    if not client_id:
        raise RuntimeError(f"SPOTIPY_CLIENT_ID is not set. {_MISSING_CREDENTIAL_HELP}")
    return client_id

def _get_redirect_uri() -> str:
    return os.environ.get("SPOTIPY_REDIRECT_URI", _DEFAULT_REDIRECT_URI)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PKCE FLOW (User-Scoped Endpoints)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_user_spotify(
    scopes: Optional[str] = None,
    open_browser: bool = True,
) -> spotipy.Spotify:
    """
    Authenticate via PKCE Authorization Code flow and return a Spotify client.

    Why PKCE over standard Authorization Code?
    Per 01_spotify_api_guardrails.md, the Implicit Grant flow is deprecated.
    PKCE (Proof Key for Code Exchange) is the recommended replacement because:
    - It doesn't require a client_secret on the client side.
    - It uses a dynamically generated code_verifier + SHA256 code_challenge,
      making it immune to authorization code interception attacks.
    - Spotipy handles all the PKCE crypto internally (RFC 7636).

    On first run, opens a browser for Spotify login → redirects to localhost
    → exchanges the code for tokens → caches tokens locally. Subsequent calls
    use the cached (auto-refreshing) token.

    Args:
        scopes:       Override default scopes. Uses USER_SCOPES if None.
        open_browser: If True, automatically open the Spotify login page.

    Returns:
        An authenticated spotipy.Spotify client for user-scoped endpoints.
    """
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    auth_manager = SpotifyPKCE(
        client_id=_get_client_id(),
        redirect_uri=_get_redirect_uri(),
        scope=scopes or USER_SCOPES,
        cache_path=str(_PKCE_CACHE_PATH),
        open_browser=open_browser,
    )

    sp = spotipy.Spotify(auth_manager=auth_manager, requests_timeout=15)
    return sp


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SELF-TEST
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    import sys
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    print("─" * 50)
    print("🔐 Testing PKCE flow (will open browser on first run)...")
    try:
        sp_user = get_user_spotify()
        me = sp_user.me()
        print(f"   ✅ PKCE authenticated as: {me['display_name']} ({me['id']})")
        results = sp_user.search(q="Muse", type="artist", limit=1)
        name = results["artists"]["items"][0]["name"]
        print(f"   ✅ Public endpoint via PKCE token works: found {name}")
    except Exception as e:
        print(f"   ❌ PKCE failed: {e}")
    print("─" * 50)
