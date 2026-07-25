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


def playlist_cards(df: Optional[pd.DataFrame], me_id: Optional[str],
                   *, members: Optional[dict] = None,
                   analyzed_ids: Optional[set] = None) -> list[dict]:
    """Importable playlists → display cards, in Spotify's returned order.

    With `members` ({playlist_id: [track_id]}, recorded at import) and
    `analyzed_ids`, each card also carries `n_known` / `n_analyzed` so it can say
    "X of Y analyzed". Both default to absent, and a playlist we have never
    imported gets `n_known = None` — we genuinely do not know its track ids
    without fetching it, and a zero would read as "none of them are analyzed"
    rather than "not imported yet"."""
    if df is None or getattr(df, "empty", True):
        return []
    members = members or {}
    analyzed_ids = analyzed_ids or set()
    cards: list[dict] = []
    for _, r in df.iterrows():
        if not _is_mine(r, me_id):
            continue
        ids = members.get(r.get("playlist_id"))
        # journal #30: a missing cover comes back from the DataFrame as a TRUTHY
        # float('nan') — `{% if c.image %}` passes it and the browser GETs /nan.
        img = r.get("image_url")
        cards.append({
            "id": r.get("playlist_id"),
            "name": r.get("playlist_name") or r.get("playlist_id"),
            "owner": r.get("owner_name") or "",
            "collaborative": bool(r.get("collaborative")),
            "track_count": int(r.get("track_count") or 0),
            "image": img if isinstance(img, str) and img else None,
            # DENOMINATOR is Spotify's own count, not len(members): a capped
            # import knows only a prefix, so counting members would shrink the
            # playlist to whatever we happen to have read so far.
            "n_known": int(r.get("track_count") or 0) if ids is not None else None,
            "n_analyzed": sum(1 for t in ids if t in analyzed_ids) if ids else 0,
            "n_seen": len(ids) if ids is not None else 0,
        })
    return cards


def track_count_for(df: Optional[pd.DataFrame], playlist_id: str) -> Optional[int]:
    """Spotify's own track count for one playlist, or None if we don't have it.

    Free — it rides on the /me/playlists frame we already fetched, so it needs
    no extra call. Used as the DENOMINATOR of "N of M analyzed" (a capped import
    only knows a prefix of the membership) and to detect a playlist that SHRANK,
    which invalidates the resume offset."""
    if df is None or getattr(df, "empty", True):
        return None
    rows = df[df["playlist_id"] == playlist_id]
    if rows.empty:
        return None
    try:
        return int(rows.iloc[0].get("track_count") or 0)
    except (TypeError, ValueError):
        return None


def importable_ids(df: Optional[pd.DataFrame], me_id: Optional[str]) -> set[str]:
    """The set of playlist ids the user may Analyze — the membership gate for the
    POST, using the SAME rule as the cards so the UI and the guard can't diverge."""
    return {c["id"] for c in playlist_cards(df, me_id)}


def coverage_line(queued: int, skipped: int, remaining: Optional[int],
                  cap: int) -> str:
    """Honest post-Analyze summary. `queued` = newly queued, `skipped` = already
    analyzed or already in the queue (cap slots are NEVER spent on these).

    `remaining` is None when the import stopped EARLY — we capped out or hit the
    page ceiling and never reached the end, so we genuinely don't know how many
    are left. That is different from 0 ("we walked the whole playlist and there
    is nothing more"), and saying "0 remaining" on a partial walk would tell the
    visitor a 1004-track playlist was finished after 50."""
    msg = f"Queued <b>{queued}</b> new track{'s' if queued != 1 else ''} for analysis"
    if skipped > 0:
        msg += f" · skipped <b>{skipped}</b> already analyzed or queued"
    if remaining is None:
        msg += (" · there may be more in this playlist — click Analyze again "
                "once these finish and it picks up where it left off")
    elif remaining > 0 and cap > 0:
        msg += (f" · <b>{remaining}</b> more held by the {cap}-track cap — "
                f"run Analyze again once these finish")
    if queued == 0 and skipped > 0:
        msg = (f"Nothing new to queue — all <b>{skipped}</b> track"
               f"{'s are' if skipped != 1 else ' is'} already analyzed or in the queue")
    return msg + "."
