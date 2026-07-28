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
                   analyzed_ids: Optional[set] = None,
                   needs_source_ids: Optional[set] = None,
                   duplicate_of: Optional[dict] = None,
                   walked: Optional[dict] = None) -> list[dict]:
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
    needs_source_ids = needs_source_ids or set()
    duplicate_of = duplicate_of or {}
    walked = walked or {}

    def _covered(tid: str) -> bool:
        """Is this track's RECORDING in the library?

        A dedup twin has no features of its own — the canonical carries them
        (O3) — so counting only `analyzed_ids` reported it as missing forever.
        "Anna setlist" read 3 of 7 while all 7 recordings were present: the
        other four were twins of tracks already analyzed, and no Analyze click
        would ever change that number. 130 members corpus-wide were undercounted
        this way."""
        return tid in analyzed_ids or duplicate_of.get(tid) in analyzed_ids
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
            # DENOMINATOR: Spotify's own count while the walk is PARTIAL — a
            # capped import knows only a prefix, and counting members would
            # shrink a 1004-track playlist to its first 50. Once we've reached
            # the end, what we FOUND is the honest total: track_count includes
            # local files and market-unavailable items the API never hands us as
            # playable tracks, and treating that gap as pending work left a card
            # reading "55 of 57" forever.
            "n_known": ((len(ids) if walked.get(r.get("playlist_id"))
                         else int(r.get("track_count") or 0))
                        if ids is not None else None),
            "n_unavailable": (max(0, int(r.get("track_count") or 0) - len(ids))
                              if ids is not None
                              and walked.get(r.get("playlist_id")) else 0),
            "n_analyzed": sum(1 for t in ids if _covered(t)) if ids else 0,
            "n_seen": len(ids) if ids is not None else 0,
            # Tracks whose acquisition permanently failed. Without this the card
            # read "50 of 129 analyzed" next to "nothing new to add" and looked
            # broken — 78 of the missing 79 needed a MANUAL source, which no
            # number of Analyze clicks can supply.
            "n_needs_source": (sum(1 for t in ids if t in needs_source_ids)
                               if ids else 0),
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
                  cap: int, *, scanned: Optional[int] = None,
                  queue_depth: Optional[int] = None,
                  needs_source: int = 0, fetch_failed: bool = False) -> str:
    """Honest post-Analyze summary: what we READ, what was already done, and what
    is now queued — the three numbers that tell a visitor whether the click did
    anything (owner, 2026-07-27: "I don't see any tracks getting extracted").

    The common case on a well-imported library is queued=0 with a large
    `skipped`, and that is a SUCCESS, not a no-op: the playlist's next tracks
    were already analyzed. Saying only "queued 0" made a working click look
    broken, so `scanned` anchors it — we looked at N, N were already done.

    `remaining` is None when the import stopped EARLY — we capped out or hit the
    page ceiling and never reached the end, so we genuinely don't know how many
    are left. That is different from 0 ("we walked the whole playlist and there
    is nothing more"), and saying "0 remaining" on a partial walk would tell the
    visitor a 1004-track playlist was finished after 50."""
    # The tracks whose acquisition permanently failed are the missing piece that
    # made a correct "nothing new" look broken: a card could read "50 of 129
    # analyzed" with nothing to queue, because 78 of the other 79 need a MANUAL
    # source and no amount of clicking Analyze will change that.
    ns = (f" · <b>{needs_source}</b> couldn't be found automatically and need a "
          f"source — <a href=\"/library?filter=needs-source\">repair them</a>"
          if needs_source else "")
    failed_bit = (" · Spotify stopped answering partway, so there may be more we "
                  "couldn't reach" if fetch_failed else "")
    scanned_bit = (f"Checked <b>{scanned}</b> track{'s' if scanned != 1 else ''} "
                   f"in this playlist — " if scanned else "")
    if queued == 0:
        if skipped > 0:
            msg = (f"{scanned_bit}all <b>{skipped}</b> already analyzed or in the "
                   f"queue, so there was nothing new to add")
        elif needs_source:
            msg = (f"{scanned_bit}nothing left that can be fetched automatically"
                   if scanned_bit else "Nothing left that can be fetched automatically")
        else:
            msg = f"{scanned_bit}nothing new to add"
        msg += ns + failed_bit
        if remaining is None and not needs_source:
            msg += (" · there may be more further in — click again and it picks "
                    "up where it left off")
        return msg + "."

    msg = (f"{scanned_bit}queued <b>{queued}</b> new track"
           f"{'s' if queued != 1 else ''} for analysis")
    if skipped > 0:
        msg += f", <b>{skipped}</b> were already done"
    if queue_depth:
        mins = max(1, round(queue_depth * 50 / 60))
        msg += (f" · the worker is analyzing them now — <a href=\"/queue\">"
                f"{queue_depth} in the queue, ~{mins} min</a>")
    msg += ns + failed_bit
    if remaining is None:
        msg += (" · click again once these finish and it picks up where it "
                "left off")
    elif remaining > 0 and cap > 0:
        msg += (f" · <b>{remaining}</b> more held by the {cap}-track cap")
    return msg + "."
