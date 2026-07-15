"""
library.py — the Library catalog's pure view logic (Epic H1 / P3.3).

Pure functions over cache.library_rows() → filtered/sorted display rows. The
catalog is PUBLIC corpus data (D-18); the "My songs" tab overlays the viewer's
own analyzed set. Search/sort/filter are form-GET (no-JS house style).
"""

from __future__ import annotations

from typing import Any, Optional

# sort key → (row field, is-numeric). Numeric Nones (unanalyzed tracks) sort last.
_SORTS: dict[str, tuple[str, bool]] = {
    "name": ("name", False),
    "artist": ("artist", False),
    "popularity": ("popularity", True),
    "tempo": ("tempo", True),
    "energy": ("energy", True),
    "brightness": ("brightness", True),
}


def annotate_dupes(rows: list[dict]) -> list[dict]:
    """Attach `same_as` = the canonical track's display name for any row flagged
    duplicate_of (D-28) — a display annotation, never a merge (the bridge key is
    untouched)."""
    name_by_id = {r["id"]: r["name"] for r in rows}
    for r in rows:
        canon = r.get("duplicate_of")
        r["same_as"] = name_by_id.get(canon) if canon else None
    return rows


def _apply_sort(rows: list[dict], field: str, numeric: bool, desc: bool) -> list[dict]:
    if numeric:
        # Unanalyzed rows (value None) always sort LAST, in either direction —
        # so split them off rather than letting reverse= flip the None flag.
        present = [r for r in rows if r.get(field) is not None]
        missing = [r for r in rows if r.get(field) is None]
        present.sort(key=lambda r: r[field], reverse=desc)
        return present + missing
    return sorted(rows, key=lambda r: (r.get(field) or "").lower(), reverse=desc)


def library_view(rows: list[dict], *, q: str = "", sort: str = "name",
                 order: str = "asc", mine_ids: Optional[set[str]] = None,
                 analyzed_only: bool = False) -> dict[str, Any]:
    """Filter (search + optional 'mine' + optional analyzed-only) then sort.

    Returns {rows, shown, total, analyzed, sort, order} — `total` is the whole
    catalog, `shown` the count after filtering (the honesty numbers)."""
    total = len(rows)
    analyzed_total = sum(1 for r in rows if r.get("analyzed"))
    out = rows
    if mine_ids is not None:
        out = [r for r in out if r["id"] in mine_ids]
    if analyzed_only:
        out = [r for r in out if r.get("analyzed")]
    ql = (q or "").strip().lower()
    if ql:
        out = [r for r in out
               if ql in (r.get("name") or "").lower()
               or ql in (r.get("artist") or "").lower()]
    field, numeric = _SORTS.get(sort, _SORTS["name"])
    out = _apply_sort(out, field, numeric, desc=(order == "desc"))
    return {"rows": out, "shown": len(out), "total": total,
            "analyzed": analyzed_total, "sort": sort if sort in _SORTS else "name",
            "order": "desc" if order == "desc" else "asc"}


def sort_options() -> list[str]:
    return list(_SORTS)


def why_n_analyzed(n_mine: int, top_limit: int, n_ranges: int = 3) -> str:
    """The honest 'why only N analyzed' explainer for the My-songs tab (D-34).
    Derived from `_TOP_LIMIT` so it can never disagree with the fetch depth."""
    ceiling = top_limit * n_ranges
    return (
        f"You have <b>{n_mine}</b> analyzed. We pull your top <b>{top_limit}</b> tracks "
        f"per time range (last 4 weeks · 6 months · all time) — up to {ceiling} entries, "
        f"far fewer unique after overlap — then download each and extract features "
        f"locally (~50 s each). New logins add more; the Playlists tab (soon) lets you "
        f"grow it further.")
