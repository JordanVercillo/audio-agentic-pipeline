"""
spotify_config.py — Authentication & Configuration for Spotify Analytics
=========================================================================
Handles both Client Credentials (public data) and Authorization Code (user data) flows.
Uses spotipy under the hood for token management and refresh.
"""

import os
import spotipy

# ─────────────────────────────────────────────────────────
# LEGACY (v0) — auth flows removed 2026-07-03.
# This project is PKCE-only with NO client secret anywhere.
# Use src/ingestion/auth.py:get_user_spotify() instead.
# ─────────────────────────────────────────────────────────
CLIENT_ID = os.environ.get("SPOTIPY_CLIENT_ID")
REDIRECT_URI = os.environ.get("SPOTIPY_REDIRECT_URI", "http://127.0.0.1:8888/callback")

# Scopes needed for user-specific endpoints (/me/top, etc.)
USER_SCOPES = "user-top-read user-read-recently-played"

_REMOVED_MSG = (
    "Removed: this legacy v0 auth flow used a client secret. The project is "
    "PKCE-only now — use src.ingestion.auth.get_user_spotify() instead."
)


def get_client_credentials_spotify() -> spotipy.Spotify:
    """LEGACY — removed. See src/ingestion/auth.py (PKCE-only)."""
    raise NotImplementedError(_REMOVED_MSG)


def get_user_spotify() -> spotipy.Spotify:
    """LEGACY — removed. See src/ingestion/auth.py (PKCE-only)."""
    raise NotImplementedError(_REMOVED_MSG)


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
