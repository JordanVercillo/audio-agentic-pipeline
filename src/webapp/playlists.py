"""
playlists.py — the "Your playlists" surface (Epic I / P3.4), pure view logic.

Pure functions over `fetch_user_playlists()` → importable playlist cards. In dev
mode only the user's OWN + collaborative playlists expose their items
(SPOTIFY_API_RESEARCH §2), and the surface is honestly "import from YOUR
playlists" — so the same "mine" rule filters both the cards and the Analyze
membership check (one source of truth).
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd


def _is_mine(row: Any, me_id: Optional[str]) -> bool:
    """Own (owner id == me) OR collaborative — the only playlists with importable
    items in dev mode. Fails CLOSED when me_id is absent (a borrowed-time /me
    miss): only collaborative playlists pass, never a stranger's."""
    owner = row.get("owner_id")
    collaborative = bool(row.get("collaborative"))
    return collaborative or (me_id is not None and owner == me_id)


def playlist_cards(df: Optional[pd.DataFrame], me_id: Optional[str]) -> list[dict]:
    """Importable playlists → display cards, in Spotify's returned order."""
    if df is None or getattr(df, "empty", True):
        return []
    cards: list[dict] = []
    for _, r in df.iterrows():
        if not _is_mine(r, me_id):
            continue
        cards.append({
            "id": r.get("playlist_id"),
            "name": r.get("playlist_name") or r.get("playlist_id"),
            "owner": r.get("owner_name") or "",
            "collaborative": bool(r.get("collaborative")),
            "track_count": int(r.get("track_count") or 0),
            "image": r.get("image_url"),
        })
    return cards


def importable_ids(df: Optional[pd.DataFrame], me_id: Optional[str]) -> set[str]:
    """The set of playlist ids the user may Analyze — the membership gate for the
    POST, using the SAME rule as the cards so the UI and the guard can't diverge."""
    return {c["id"] for c in playlist_cards(df, me_id)}


def coverage_line(total: int, new_count: int, already_count: int, cap: int) -> str:
    """Honest post-Analyze summary: queued-new vs already-engineered, and whether
    the cap clipped the import. `total` is the pre-cap track count."""
    msg = f"Queued <b>{new_count}</b> new track{'s' if new_count != 1 else ''} for analysis"
    if already_count > 0:
        msg += f" · <b>{already_count}</b> already engineered"
    if total > cap:
        msg += f" · capped at {cap} of {total} (import more later)"
    return msg + "."
