"""
sessions.py — ephemeral server-side sessions (SPEC P8, D-7 "sessions expire").

The visitor's browser holds only a random session id in a *signed* cookie
(itsdangerous); all session data (the in-flight PKCE params, then the access
token + taste profile) lives server-side in an in-memory store with a TTL.

    - Signed cookie → the id can't be forged/tampered (integrity).
    - Server-side data → the access token never rides in the browser cookie.
    - TTL + sweep → sessions expire by default (privacy-first, ephemeral).

In-memory is right for the single-instance pilot (Cloud Run min-instances=1).
Multi-instance later swaps `SessionStore` for Redis/Firestore with the same
interface — noted in docs/P8_PLAN.md, not built here.
"""

from __future__ import annotations

import secrets
import time
from typing import Any, Optional

from itsdangerous import BadSignature, URLSafeSerializer


class SessionStore:
    """Thread-simple in-memory session store keyed by opaque session id."""

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._data: dict[str, dict[str, Any]] = {}
        self._expiry: dict[str, float] = {}

    def new(self) -> str:
        """Create an empty session, return its id."""
        sid = secrets.token_urlsafe(24)
        self._data[sid] = {}
        self._touch(sid)
        return sid

    def get(self, sid: Optional[str]) -> Optional[dict[str, Any]]:
        """Return the session dict if the id is live and unexpired, else None."""
        if not sid:
            return None
        self._sweep()
        if sid not in self._data:
            return None
        if self._expiry.get(sid, 0) < time.time():
            self.delete(sid)
            return None
        self._touch(sid)  # sliding expiry on access
        return self._data[sid]

    def delete(self, sid: str) -> None:
        self._data.pop(sid, None)
        self._expiry.pop(sid, None)

    def rotate(self, sid: str) -> str:
        """Move a session's data to a fresh id (session-fixation defense on login)."""
        data = self._data.get(sid, {})
        self.delete(sid)
        new = secrets.token_urlsafe(24)
        self._data[new] = data
        self._touch(new)
        return new

    def _touch(self, sid: str) -> None:
        self._expiry[sid] = time.time() + self._ttl

    def _sweep(self) -> None:
        now = time.time()
        for sid in [s for s, exp in self._expiry.items() if exp < now]:
            self.delete(sid)

    def __len__(self) -> int:  # for tests / introspection
        self._sweep()
        return len(self._data)


class CookieSigner:
    """Signs/verifies the session id carried in the cookie (integrity only)."""

    def __init__(self, secret_key: str) -> None:
        self._s = URLSafeSerializer(secret_key, salt="va-session")

    def sign(self, sid: str) -> str:
        return self._s.dumps(sid)

    def unsign(self, token: Optional[str]) -> Optional[str]:
        if not token:
            return None
        try:
            return self._s.loads(token)
        except BadSignature:
            return None
