"""
auth.py — Spotify OAuth Authentication (2026 Compliant)
========================================================
Implements the two surviving auth flows per 01_spotify_api_guardrails.md:

    1. PKCE Authorization Code Flow — for user-scoped endpoints (/me/top, /me/player).
       The Implicit Grant flow is DEPRECATED. PKCE is the only sanctioned user auth flow.
       Key advantage: no client_secret needed on the client side (PKCE uses a
       code_verifier/code_challenge instead), making it safe for desktop/mobile apps.

    2. Client Credentials Flow — for public endpoints (tracks, artists, albums, search).
       No user login required. Uses client_id + client_secret for machine-to-machine auth.

Credential loading priority:
    1. Environment variables (SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET, SPOTIPY_REDIRECT_URI)
    2. .env file in project root (loaded via python-dotenv if available)
    3. Hardcoded fallback (your existing credentials from spotify_config.py)

Reference: 01_spotify_api_guardrails.md — "NO IMPLICIT GRANT" directive
"""

import os
from pathlib import Path
from typing import Optional

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials, SpotifyPKCE

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

# Fallback credentials (from your existing projects/spotify/spotify_config.py).
# In production, always prefer environment variables for security.
_FALLBACK_CLIENT_ID = "8900a9bfd0424ea0aaa054ce5aa9cfff"
_FALLBACK_CLIENT_SECRET = "***REMOVED***"
_FALLBACK_REDIRECT_URI = "http://127.0.0.1:8888/callback"

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
    return os.environ.get("SPOTIPY_CLIENT_ID", _FALLBACK_CLIENT_ID)

def _get_client_secret() -> str:
    return os.environ.get("SPOTIPY_CLIENT_SECRET", _FALLBACK_CLIENT_SECRET)

def _get_redirect_uri() -> str:
    return os.environ.get("SPOTIPY_REDIRECT_URI", _FALLBACK_REDIRECT_URI)


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
#  CLIENT CREDENTIALS FLOW (Public Endpoints)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_public_spotify() -> spotipy.Spotify:
    """
    Authenticate via Client Credentials flow for public data endpoints.

    Use this for:
    - GET /tracks/{id}, GET /artists/{id}, GET /albums/{id}
    - GET /search
    - Any endpoint that doesn't require user context

    No user login needed — uses client_id + client_secret for
    machine-to-machine authentication.
    """
    auth_manager = SpotifyClientCredentials(
        client_id=_get_client_id(),
        client_secret=_get_client_secret(),
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
    print("🔐 Testing Client Credentials flow...")
    try:
        sp = get_public_spotify()
        results = sp.search(q="Muse", type="artist", limit=1)
        name = results["artists"]["items"][0]["name"]
        print(f"   ✅ Authenticated! Found artist: {name}")
    except Exception as e:
        print(f"   ❌ Client Credentials failed: {e}")

    print("─" * 50)
    print("🔐 Testing PKCE flow (will open browser on first run)...")
    try:
        sp_user = get_user_spotify()
        me = sp_user.me()
        print(f"   ✅ PKCE authenticated as: {me['display_name']} ({me['id']})")
    except Exception as e:
        print(f"   ❌ PKCE failed: {e}")
    print("─" * 50)
