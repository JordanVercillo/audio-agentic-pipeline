"""
guardrails.py — Spotify 2026 API Compliance Layer
===================================================
Wraps spotipy calls with enforcement of the 2026 deprecation rules
from 01_spotify_api_guardrails.md.

This module exists because raw spotipy still exposes methods for
deprecated endpoints (e.g., sp.audio_features()). If we accidentally
call them, we get a confusing 403/404. This layer catches those
mistakes at the Python level with clear error messages, and also
strips deprecated fields from response objects before they propagate
into downstream data structures.

Hard blocks:
    ✖ audio_features()       → removed Feb 2026
    ✖ audio_analysis()       → removed Feb 2026
    ✖ current_user_saved_tracks()   → deprecated, use /me/library
    ✖ current_user_saved_albums()   → deprecated, use /me/library

Field stripping:
    (none currently — `popularity` is deprecated-NOT-removed; captured as
     optional fetched context, never an ML input. See _DEPRECATED_FIELDS.)

Reference: 01_spotify_api_guardrails.md
"""

import time
from typing import Any, Optional

import spotipy

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DEPRECATED ENDPOINT BLOCKLIST
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# These spotipy method names map to deprecated endpoints.
# Calling any of these should raise an immediate, clear error
# instead of a cryptic HTTP 403.
_BLOCKED_METHODS = {
    "audio_features": (
        "/audio-features is REMOVED as of Feb 2026. "
        "Use src.dsp.extract_features() for local acoustic analysis."
    ),
    "audio_analysis": (
        "/audio-analysis is REMOVED as of Feb 2026. "
        "Use src.dsp.extract_features() for local acoustic analysis."
    ),
    "current_user_saved_tracks": (
        "/me/tracks is DEPRECATED. Use PUT /me/library with mixed URIs instead."
    ),
    "current_user_saved_albums": (
        "/me/albums is DEPRECATED. Use PUT /me/library with mixed URIs instead."
    ),
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SAFE API CALL WRAPPER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def safe_api_call(
    func,
    *args,
    label: str = "API call",
    **kwargs,
) -> tuple[Optional[Any], Optional[str]]:
    """
    Execute a spotipy method with guardrail checks and error handling.

    1. Blocks calls to deprecated endpoints with clear error messages.
    2. Catches HTTP 403/404 (Development Mode restrictions) gracefully.
    3. Returns (data, None) on success or (None, error_message) on failure.

    Args:
        func:   A bound method on a spotipy.Spotify instance (e.g., sp.track).
        *args:  Positional args passed to the method.
        label:  Human-readable label for error messages (e.g., "GET /tracks/123").
        **kwargs: Keyword args passed to the method.

    Returns:
        (result_data, None) on success.
        (None, error_message) on failure.

    Raises:
        DeprecatedEndpointError: If calling a blocked deprecated method.
    """
    # ── Check blocklist ──
    method_name = getattr(func, "__name__", "")
    if method_name in _BLOCKED_METHODS:
        msg = f"🚫 BLOCKED — {label}\n   {_BLOCKED_METHODS[method_name]}"
        raise DeprecatedEndpointError(msg)

    # ── Execute with error handling and retries ──
    import requests
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            result = func(*args, **kwargs)
            return result, None
        except spotipy.exceptions.SpotifyException as e:
            if e.http_status in (403, 404):
                msg = (
                    f"⚠️  RESTRICTED — {label}\n"
                    f"   HTTP {e.http_status}: Endpoint requires Extended Quota Mode.\n"
                    f"   Your app is in Development Mode (post-Feb 2026 restriction).\n"
                    f"   Skipping gracefully."
                )
                print(msg)
                return None, msg
            raise
        except (requests.exceptions.RequestException, ConnectionError) as e:
            if attempt < max_retries:
                print(f"   🔄 Network error in {label} (attempt {attempt}/{max_retries}), retrying in 2s... ({e})")
                time.sleep(2)
                continue
            msg = f"❌ Network error in {label} after {max_retries} attempts: {e}"
            print(msg)
            return None, msg
        except Exception as e:
            msg = f"❌ Unexpected error in {label}: {e}"
            print(msg)
            return None, msg


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  RESPONSE FIELD STRIPPING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# CORRECTED 2026-07-10 (journal #20): a live check of GET /tracks showed
# `popularity` is DEPRECATED, NOT REMOVED — still returned, discouraged, may
# vanish. Our earlier guardrail hardened a defensive assumption into "removed"
# and silently threw the field away on every fetch. Policy now:
#   - popularity is CAPTURED as optional fetched context (absent-safe),
#   - it is NEVER an acoustic feature (it's fetched, not derived) and NEVER
#     an ML input (Spotify's terms forbid training on their content),
#   - nothing may HARD-depend on it (it can disappear any day).
_DEPRECATED_FIELDS: set[str] = set()  # nothing currently needs stripping


def strip_deprecated_fields(obj: dict) -> dict:
    """
    Remove hard-removed fields from a Spotify API response object.

    Currently a no-op passthrough: `popularity` — the one field this used to
    strip — turned out to be deprecated-not-removed (see the policy note on
    _DEPRECATED_FIELDS). The hook stays so a future real removal is a
    one-line change on every fetch path at once.

    Args:
        obj: A raw Spotify API response dict (track, artist, or album).

    Returns:
        The same dict with any hard-removed fields dropped.
    """
    for field in _DEPRECATED_FIELDS:
        obj.pop(field, None)
    return obj


def strip_deprecated_fields_batch(items: list[dict]) -> list[dict]:
    """Apply strip_deprecated_fields to a list of response objects."""
    return [strip_deprecated_fields(item) for item in items]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  RATE LIMITING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def throttle(delay: float = 0.1) -> None:
    """
    Simple rate-limit pause between API calls.

    Spotify's rate limit is ~180 requests/minute for most endpoints.
    A 100ms pause between calls keeps us at ~600 req/min theoretical max,
    well above the limit — but in practice, network latency naturally
    throttles us. This is a safety floor, not the primary rate limiter.
    """
    time.sleep(delay)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CUSTOM EXCEPTIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DeprecatedEndpointError(Exception):
    """Raised when code attempts to call a deprecated Spotify API endpoint."""
    pass
