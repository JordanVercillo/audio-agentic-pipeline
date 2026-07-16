"""
auth_web.py — session-scoped PKCE for the webapp (SPEC P8, D-8).

The pipeline's `ingestion/auth.py` uses spotipy's desktop flow (browser +
shared file cache). A webapp can't: each visitor authorizes their OWN account,
and the in-flight PKCE `code_verifier` must survive the redirect to Spotify and
back — per session, never on disk, never shared.

So we drive `SpotifyPKCE` by hand:

    /login    build_authorize_url(session)  → generates verifier+challenge+state,
              stashes them in the server-side session, returns the Spotify URL.
    /callback exchange_code(session, code, state) → verifies state (CSRF),
              RESTORES the stashed verifier+challenge (else spotipy regenerates
              them and the exchange fails), swaps code→token via a
              MemoryCacheHandler, stores token_info in the session.

No client secret is used anywhere — PKCE needs only the public client_id (D-8).
"""

from __future__ import annotations

import secrets
from typing import Any

import spotipy
from spotipy.cache_handler import MemoryCacheHandler
from spotipy.oauth2 import SpotifyPKCE

from . import config

# Session keys
_PKCE = "pkce"   # in-flight {verifier, challenge, state} between /login and /callback
_TOKEN = "token"  # token_info dict after a successful exchange


class AuthError(Exception):
    """Raised on a bad/mismatched callback (CSRF, missing in-flight PKCE, exchange failure)."""


def _new_pkce(cache_handler: MemoryCacheHandler | None = None) -> SpotifyPKCE:
    # Always pass a memory cache handler so spotipy never writes a token file.
    return SpotifyPKCE(
        client_id=config.get_client_id(),
        redirect_uri=config.REDIRECT_URI,
        scope=config.SCOPES,
        open_browser=False,
        cache_handler=cache_handler or MemoryCacheHandler(),
    )


def build_authorize_url(session: dict[str, Any]) -> str:
    """Generate the PKCE params, stash them in `session`, return Spotify's authorize URL."""
    pkce = _new_pkce()
    state = secrets.token_urlsafe(16)
    url = pkce.get_authorize_url(state=state)  # sets pkce.code_verifier + code_challenge
    session[_PKCE] = {
        "verifier": pkce.code_verifier,
        "challenge": pkce.code_challenge,
        "state": state,
    }
    return url


def exchange_code(session: dict[str, Any], code: str, state: str | None) -> dict[str, Any]:
    """
    Verify the callback and swap the auth code for a token, storing it in `session`.

    Raises AuthError on CSRF state mismatch, missing in-flight PKCE, or a failed
    token exchange. On success the in-flight PKCE is cleared and `session['token']`
    holds the full token_info.
    """
    stash = session.get(_PKCE)
    if not stash:
        raise AuthError("No in-flight login for this session (start at /login).")
    if not state or not secrets.compare_digest(str(state), str(stash["state"])):
        raise AuthError("State mismatch — possible CSRF; login rejected.")
    if not code:
        raise AuthError("Missing authorization code.")

    handler = MemoryCacheHandler()
    pkce = _new_pkce(cache_handler=handler)
    # Restore the exact verifier/challenge we sent, so spotipy doesn't regenerate them.
    pkce.code_verifier = stash["verifier"]
    pkce.code_challenge = stash["challenge"]

    try:
        pkce.get_access_token(code, check_cache=False)
    except Exception as exc:  # noqa: BLE001 — surface a clean auth error to the route
        raise AuthError(f"Token exchange failed: {exc}") from exc

    token_info = handler.get_cached_token()
    if not token_info or "access_token" not in token_info:
        raise AuthError("Token exchange returned no access token.")

    session.pop(_PKCE, None)
    session[_TOKEN] = token_info
    return token_info


def is_authenticated(session: dict[str, Any]) -> bool:
    return bool(session.get(_TOKEN, {}).get("access_token"))


def granted_scopes(session: dict[str, Any]) -> set[str]:
    """The scopes Spotify actually granted this session, read from the token
    response's `scope` field (stored verbatim by exchange_code). Empty for a
    pre-scope-change token or an anon session."""
    return set((session.get(_TOKEN, {}).get("scope") or "").split())


def has_playlist_scope(session: dict[str, Any]) -> bool:
    """True once the session's token carries BOTH playlist scopes — derived from
    config (never a second copy of the names), so retuning SCOPES can't leave the
    gate lying. An existing `user-top-read`-only token reads False → re-consent."""
    return set(config.PLAYLIST_SCOPES).issubset(granted_scopes(session))


def client_from_session(session: dict[str, Any]) -> spotipy.Spotify:
    """A spotipy client bound to this visitor's access token.

    FAIL FAST (owner report, session 36 — "the artists page gets stuck"):
    spotipy's default is 3 retries WITH Retry-After honoring, so one 429 on a
    borrowed-time garnish call can sleep a page render for 45s+. Every webapp
    call site already has an absent-safe try/except — raising immediately is
    the designed path, so retries are 0 across the board."""
    token = session.get(_TOKEN)
    if not token or "access_token" not in token:
        raise AuthError("Not authenticated.")
    return spotipy.Spotify(auth=token["access_token"], requests_timeout=15,
                           retries=0, status_retries=0, backoff_factor=0)
