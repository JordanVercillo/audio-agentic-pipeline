"""
library.py — the Library catalog's pure view logic (Epic H1 / P3.3).

Pure functions over cache.library_rows() → filtered/sorted display rows. The
catalog is PUBLIC corpus data (D-18); the "My songs" tab overlays the viewer's
own analyzed set. Search/sort/filter are form-GET (no-JS house style).
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlencode

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


def annotate_queue_state(rows: list[dict], job_states: dict,
                         max_attempts: int = 3) -> list[dict]:
    """Attach `queue_state` to every unanalyzed row: "analyzing" | "no_source" | None.

    The catalog used to render "analyzing…" for ANY unanalyzed track, so the
    tracks whose acquisition permanently failed advertised work that had
    already stopped — 40+ of them, indefinitely. That is the same lie
    "download failed" told when conversion failed (QA_PLAN B6): the UI naming
    the nearest generic state instead of what actually happened.

    A job dead-letters at `max_attempts` and `enqueue` never retries it, so it
    is honestly finished; a failure UNDER the cap is re-queued on the next
    dashboard visit that includes the track, so it is honestly still coming.
    No job row at all → no claim (blank): metadata-only rows were never
    requested. Analyzed rows are left untouched."""
    for r in rows:
        if r.get("analyzed"):
            r["queue_state"] = None
            continue
        status, attempts = job_states.get(r["id"], (None, 0))
        if status in ("queued", "running"):
            r["queue_state"] = "analyzing"
        elif status == "failed" and attempts >= max_attempts:
            r["queue_state"] = "no_source"
        elif status == "failed":
            r["queue_state"] = "analyzing"      # under the cap → re-queued later
        else:
            r["queue_state"] = None
    return rows


def consolidate_rows(rows: list[dict], *, expand: bool = False) -> list[dict]:
    """Collapse twin rows under their canonical (O3c — DISPLAY only, red-team
    #5: the group is counted and named BEFORE any row is dropped, and the twin
    titles ride the canonical as `alt_names` so searching a twin's distinct
    title still surfaces the recording). `expand=True` keeps every row (the
    transparency view — twins carry their same_as note from annotate_dupes).
    A twin whose canonical is absent from the list stays visible (fail-open)."""
    by_id = {r["id"]: r for r in rows}
    for r in rows:
        canon = r.get("duplicate_of")
        if canon and canon in by_id:
            c = by_id[canon]
            c.setdefault("alt_names", []).append(r["name"])
            c["n_versions"] = 1 + len(c["alt_names"])
    if expand:
        return rows
    return [r for r in rows
            if not (r.get("duplicate_of") and r["duplicate_of"] in by_id)]


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
        # O3c: a collapsed canonical also matches through its twins' titles
        # (alt_names), so searching "… - 2011 Remaster" still finds the recording.
        out = [r for r in out
               if ql in (r.get("name") or "").lower()
               or ql in (r.get("artist") or "").lower()
               or any(ql in (n or "").lower() for n in r.get("alt_names") or [])]
    field, numeric = _SORTS.get(sort, _SORTS["name"])
    out = _apply_sort(out, field, numeric, desc=(order == "desc"))
    return {"rows": out, "shown": len(out), "total": total,
            "analyzed": analyzed_total, "sort": sort if sort in _SORTS else "name",
            "order": "desc" if order == "desc" else "asc"}


def sort_options() -> list[str]:
    return list(_SORTS)


# ── pagination (the growth gate) ─────────────────────────────────────────────
# THE source of truth for every page-size claim on this surface: the caption,
# the pager links and the per-page selector all derive from these. Nothing in a
# template may restate them — a second encoding is how the UI and the behaviour
# drift apart.
PAGE_SIZE = 100
PAGE_SIZES: tuple[int, ...] = (50, 100, 250)
ALL = "all"
# The query keys this surface owns. Pager URLs are rebuilt from an ALLOWLIST,
# never echoed from whatever arrived, so a crafted /library?<junk> can't plant
# junk in our own links.
_PAGER_KEYS = ("q", "sort", "order", "tab", "filter", "dupes", "per")


def _coerce_per(per: Any) -> int:
    """Allowlist, not int(): `?per=100000` is a self-inflicted 12 MB page."""
    try:
        v = int(per)
    except (TypeError, ValueError):
        return PAGE_SIZE
    return v if v in PAGE_SIZES else PAGE_SIZE


def _coerce_page(page: Any, pages: int) -> int:
    """Clamp. `?page=0` / `-3` / `abc` / `99999` must render a real page — never
    a 500, and never an empty one that reads as "the corpus ended here"."""
    try:
        p = int(page)
    except (TypeError, ValueError):
        p = 1
    return min(max(p, 1), max(pages, 1))


def page_slice(view: dict[str, Any], *, page: Any = 1,
               per: Any = PAGE_SIZE) -> dict[str, Any]:
    """Slice an ALREADY filtered-and-sorted `library_view()` result into one page.

    Ordering and filtering happen over the WHOLE corpus in `library_view`; this
    only ever slices that output. A sort that covers just the visible window is
    therefore unrepresentable here, not merely untested — this function never
    sees the unsorted rows.

    `rows` (the full matching set) is preserved so callers that COUNT — the
    my-songs total, the why-only-N explainer — keep counting the whole set; the
    template renders `page_rows`. `from_index`/`to_index` are real 1-based
    inclusive positions, so the caption states what is on screen instead of
    recomputing page*per and hoping."""
    rows = view["rows"]
    n = len(rows)
    is_all = str(per).strip().lower() == ALL
    size = n if is_all else _coerce_per(per)
    pages = 1 if is_all or size <= 0 else max(1, -(-n // size))   # ceil
    p = 1 if is_all else _coerce_page(page, pages)
    start = 0 if is_all else (p - 1) * size
    page_rows = rows if is_all else rows[start:start + size]
    return {**view,
            "page_rows": page_rows, "page": p, "pages": pages,
            "per": ALL if is_all else size, "is_all": is_all,
            "from_index": start + 1 if page_rows else 0,
            "to_index": start + len(page_rows),
            "page_sizes": list(PAGE_SIZES)}


def pager_query(params: dict, **overrides) -> str:
    """A query string for this surface, built from the allowlist + overrides."""
    keep = {k: str(v) for k, v in (params or {}).items()
            if k in _PAGER_KEYS and v not in (None, "")}
    for k, v in overrides.items():
        if v in (None, ""):
            keep.pop(k, None)
        else:
            keep[k] = str(v)
    return urlencode(keep)


def page_links(params: dict, nav: dict[str, Any],
               window: int = 2) -> list[dict[str, Any]]:
    """Pager entries: first, last, ±`window` around current, '…' for the gaps.

    The LAST page is always present. A pager that cannot reach the tail hides
    tracks as effectively as an infinite scroll does."""
    pages, cur = nav["pages"], nav["page"]
    if pages <= 1:
        return []
    wanted = sorted({1, pages, *range(max(1, cur - window),
                                      min(pages, cur + window) + 1)})
    out: list[dict[str, Any]] = []
    prev = 0
    for p in wanted:
        if prev and p != prev + 1:
            out.append({"label": "…", "url": None, "current": False})
        out.append({"label": str(p),
                    "url": f"/library?{pager_query(params, page=p)}",
                    "current": p == cur})
        prev = p
    return out


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
