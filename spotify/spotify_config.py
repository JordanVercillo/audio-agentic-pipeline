"""
spotify_config.py — Authentication & Configuration for Spotify Analytics
=========================================================================
Handles both Client Credentials (public data) and Authorization Code (user data) flows.
Uses spotipy under the hood for token management and refresh.
"""

import os
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials, SpotifyOAuth

# ─────────────────────────────────────────────────────────
# Credentials — set here or via environment variables
# ─────────────────────────────────────────────────────────
CLIENT_ID = os.environ.get("SPOTIPY_CLIENT_ID", "8900a9bfd0424ea0aaa054ce5aa9cfff")
CLIENT_SECRET = os.environ.get("SPOTIPY_CLIENT_SECRET", "***REMOVED***")
REDIRECT_URI = os.environ.get("SPOTIPY_REDIRECT_URI", "http://127.0.0.1:8888/callback")

# Scopes needed for user-specific endpoints (/me/top, etc.)
USER_SCOPES = "user-top-read user-read-recently-played"


def get_client_credentials_spotify() -> spotipy.Spotify:
    """
    Returns a Spotify client authenticated via Client Credentials flow.
    Use this for public endpoints: tracks, artists, albums, search.
    No user login required.
    """
    auth_manager = SpotifyClientCredentials(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
    )
    sp = spotipy.Spotify(auth_manager=auth_manager, requests_timeout=10)
    return sp


def get_user_spotify() -> spotipy.Spotify:
    """
    Returns a Spotify client authenticated via Authorization Code flow.
    Use this for user-specific endpoints: /me/top/{type}, /me/player, etc.
    Will open browser for OAuth login on first run, then caches the token.
    """
    auth_manager = SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=USER_SCOPES,
        cache_path=os.path.join(os.path.dirname(__file__), ".spotify_cache"),
        open_browser=True,
    )
    sp = spotipy.Spotify(auth_manager=auth_manager, requests_timeout=10)
    return sp


# ─────────────────────────────────────────────────────────
# Quick self-test
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if sys.stdout.encoding != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    print("─" * 50)
    print("🔐 Testing Client Credentials flow...")
    try:
        sp = get_client_credentials_spotify()
        # Simple check: search for a known artist
        results = sp.search(q="Muse", type="artist", limit=1)
        name = results["artists"]["items"][0]["name"]
        print(f"   ✅ Authenticated! Found artist: {name}")
    except Exception as e:
        print(f"   ❌ Client Credentials failed: {e}")

    print("─" * 50)
    print("ℹ️  User OAuth flow (optional) — run get_user_spotify() to test.")
    print("─" * 50)
