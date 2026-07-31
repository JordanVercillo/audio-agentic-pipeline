"""
artists.py — the Artists surface's pure view logic (Epic P / P3.2).

Everything here is a pure function from cached dicts → template context; the
routes stay thin. Grounding rules:
  - Artist identity joins are by PRIMARY NAME (the clusters.py:170 rule —
    `names.split(",")[0].strip()`), the established soft spot; artist_meta's
    `artist_id` hardens links where known (D-36).
  - Genres come from the stored artist_meta copy (deprecated-not-removed
    upstream — journal #9): every genre view carries its coverage number.
  - "Your top tracks by this artist" is the DERIVED core (D-33) — the live
    top-10 is absent-safe garnish handled by the route, never here.
  - "Similar in your library" is acoustic-centroid distance over OUR tracks —
    "who sounds alike HERE", not Spotify's fan-overlap neighbors (labelled so).

Chart rules (dataviz): one ranked-bar SVG, values labelled, names escaped
(markupsafe — rendered |safe), no color-only encoding.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from markupsafe import escape

from ..store.cache import _SIMILARITY_COLS
from . import scales

# Aggregate features shown on the hover card (means over analyzed tracks).
_CARD_FEATURES = ("tempo", "energy", "danceability")


def primary_artist(names: Optional[str]) -> str:
    """The primary-artist name from a comma-joined artist_names string —
    EXACTLY the clusters.py rule so every surface groups identically."""
    return (names or "").split(",")[0].strip()


def _mean(vals: list[float]) -> Optional[float]:
    return sum(vals) / len(vals) if vals else None


def artist_rollup(taste_artists: list[dict], metas: dict[str, dict],
                  perceptual: dict[str, dict],
                  artist_meta: dict[str, dict]) -> list[dict[str, Any]]:
    """One card per taste artist (rank order preserved): identity + stored
    metadata (genres/popularity/followers/image via a name→artist_meta match)
    + library coverage + mean perceptual features over THEIR analyzed tracks.
    """
    by_name = { (a.get("artist_name") or "").lower(): a
                for a in artist_meta.values() }
    # primary-artist name → that artist's track ids in the library
    tracks_of: dict[str, list[str]] = {}
    for tid, m in metas.items():
        p = primary_artist(m.get("artist_names")).lower()
        if p:
            tracks_of.setdefault(p, []).append(tid)

    cards: list[dict[str, Any]] = []
    for a in taste_artists:
        name = (a.get("name") or "").strip()
        if not name:
            continue
        am = by_name.get(name.lower(), {})
        tids = tracks_of.get(name.lower(), [])
        analyzed = [t for t in tids if t in perceptual]
        feats = {c: _mean([float(perceptual[t][c]) for t in analyzed
                           if isinstance(perceptual[t].get(c), (int, float))])
                 for c in _CARD_FEATURES}
        cards.append({
            "name": name,
            "artist_id": am.get("artist_id"),          # link only when known
            "genres": am.get("genres") or a.get("genres") or "",
            "popularity": am.get("popularity"),
            "followers": am.get("followers"),
            "image": am.get("image_url"),
            "n_tracks": len(tids),
            "n_analyzed": len(analyzed),
            "feat": feats,
        })
    return cards


# ── genres (stored-copy honesty, journal #9) ─────────────────────────────────
def genre_tokens(genres: Optional[str]) -> list[str]:
    return [g.strip().lower() for g in (genres or "").split(",") if g.strip()]


def filter_by_genre(cards: list[dict], genre: Optional[str]) -> list[dict]:
    """Cards whose stored genres contain the token (case-insensitive).
    An unknown/empty genre filter returns the cards unchanged."""
    g = (genre or "").strip().lower()
    if not g:
        return cards
    return [c for c in cards if g in genre_tokens(c.get("genres"))]


def genre_strip(cards: list[dict], top_n: int = 10) -> dict[str, Any]:
    """The genre comparison strip: token → artist count across the cards,
    plus the coverage honesty numbers (genres known for N of M artists)."""
    counts: dict[str, int] = {}
    covered = 0
    for c in cards:
        toks = genre_tokens(c.get("genres"))
        if toks:
            covered += 1
        for t in set(toks):
            counts[t] = counts.get(t, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
    return {"genres": [{"genre": g, "count": n} for g, n in ranked],
            "covered": covered, "total": len(cards)}


# ── the comparison chart ─────────────────────────────────────────────────────
def comparison_svg(cards: list[dict], column: str, friendly: str,
                   width: int = 640, row_h: int = 26) -> str:
    """ONE ranked-bar SVG: your artists ordered by their mean `column` over
    analyzed tracks. Value labels on every bar (never color-alone); artist
    names escaped (rendered |safe). "" under 2 comparable artists."""
    rows = [(c["name"], c["feat"].get(column), c["n_analyzed"]) for c in cards
            if isinstance(c.get("feat", {}).get(column), (int, float))]
    if len(rows) < 2:
        return ""
    rows.sort(key=lambda r: -r[1])
    vmax = max(v for _, v, _ in rows) or 1.0
    pad_l, pad_r, label_w = 8, 56, 150
    bar_w = width - pad_l - pad_r - label_w
    height = row_h * len(rows) + 10
    parts = [f'<svg viewBox="0 0 {width} {height}" class="artist-cmp" role="img" '
             f'aria-label="your artists compared by mean {escape(friendly)}">']
    for i, (name, val, n) in enumerate(rows):
        y = 5 + i * row_h
        w = max(2.0, (val / vmax) * bar_w)
        label = f"{val:.2f}" if abs(val) < 10 else f"{val:.0f}"
        parts.append(
            f'<text class="cmp-name" x="{pad_l}" y="{y + row_h / 2 + 4:.1f}">{escape(name)}</text>'
            f'<rect class="cmp-bar" x="{pad_l + label_w}" y="{y + 4}" '
            f'width="{w:.1f}" height="{row_h - 10}" rx="3"/>'
            f'<text class="cmp-val" x="{pad_l + label_w + w + 6:.1f}" '
            f'y="{y + row_h / 2 + 4:.1f}">{label} <tspan class="cmp-n">({n})</tspan></text>')
    parts.append("</svg>")
    return "".join(parts)


# ── the artist deep-dive (derived core, D-33) ────────────────────────────────
def your_top_by_artist(artist_name: str, range_ids: dict[str, list[str]],
                       metas: dict[str, dict], limit: int = 5) -> list[dict]:
    """YOUR top tracks by this artist — derived from the /me/top ranks we
    already store (0 API calls, always renders). Order = first appearance
    walking short→medium→long term lists (rank order within each)."""
    target = (artist_name or "").strip().lower()
    if not target:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for window in ("short_term", "medium_term", "long_term"):
        for tid in range_ids.get(window, []):
            if tid in seen:
                continue
            m = metas.get(tid)
            if m and primary_artist(m.get("artist_names")).lower() == target:
                seen.add(tid)
                out.append({"id": tid, "name": m.get("track_name") or tid,
                            "window": window})
                if len(out) >= limit:
                    return out
    return out


def nearest_artists(artist_name: str, features: dict[str, dict],
                    metas: dict[str, dict], k: int = 5,
                    min_tracks: int = 2) -> list[dict[str, Any]]:
    """"Similar in your library": artists ranked by z-scored acoustic-centroid
    distance to the target — who SOUNDS alike here, not Spotify's fan-overlap
    neighbors (the honest related-artists replacement, D-33/derivation map).
    Artists need ≥ min_tracks analyzed tracks to have a stable centroid.
    """
    target = (artist_name or "").strip().lower()
    # group analyzed tracks by primary artist
    by_artist: dict[str, list[str]] = {}
    for tid, m in metas.items():
        if tid not in features:
            continue
        p = primary_artist(m.get("artist_names"))
        if p:
            by_artist.setdefault(p, []).append(tid)
    if target not in {a.lower() for a in by_artist}:
        return []
    # z-score the shared numeric cols across ALL analyzed tracks (coverage-based)
    all_tids = [t for tids in by_artist.values() for t in tids]
    cols = [c for c in _SIMILARITY_COLS
            if sum(isinstance(features[t].get(c), (int, float)) for t in all_tids) >= 3]
    if not cols:
        return []
    stats = {}
    for c in cols:
        vals = [float(features[t].get(c) or 0.0) for t in all_tids]
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        stats[c] = (mean, math.sqrt(var) or 1.0)

    def centroid(tids: list[str]) -> list[float]:
        return [_mean([(float(features[t].get(c) or 0.0) - stats[c][0]) / stats[c][1]
                       for t in tids]) or 0.0 for c in cols]

    cents = {name: centroid(tids) for name, tids in by_artist.items()
             if len(tids) >= min_tracks or name.lower() == target}
    tgt_name = next(n for n in cents if n.lower() == target)
    tgt = cents[tgt_name]
    ranked = []
    for name, vec in cents.items():
        if name.lower() == target:
            continue
        d = math.sqrt(sum((a - b) ** 2 for a, b in zip(tgt, vec, strict=True)))
        ranked.append({"name": name, "distance": round(d, 2),
                       "n_tracks": len(by_artist[name])})
    ranked.sort(key=lambda r: r["distance"])
    return ranked[:k]


# ── R1: the CORPUS-scale artist index (Vision F P4.7.2) ──────────────────────
def corpus_artist_index(metas: dict[str, dict], perceptual: dict[str, dict],
                        artist_meta: dict[str, dict],
                        library_rows: Optional[list[dict]] = None,
                        ) -> dict[str, Any]:
    """Every artist the CORPUS knows, not just the visitor's top ~15.

    `/artists` built its cards from `session["taste"]["artists"]`, so the page
    could only ever show about fifteen while `artist_rollup.parquet` carried
    ~892 — and an anonymous visitor reached none of them. This builds the index
    from the corpus itself, which is also what makes the surface public
    (taste-free, D-18) instead of a private snapshot.

    Grouped by `primary_artist_id` — Spotify's own id, stored on 97% of tracks
    and already the `/artist/{id}` route key. That is NOT a second identity
    system (ground rule 1): `spotify_track_id` remains the only cross-layer
    bridge key, and this id is an attribute we group on.

    Tracks with no id fall back to their primary-artist NAME and are COUNTED,
    never silently folded in: two different artists sharing a name would
    otherwise merge invisibly, which is the failure mode a silent fallback
    always hides.
    """
    by_id = {a.get("artist_id"): a for a in artist_meta.values() if a.get("artist_id")}
    by_name = {(a.get("artist_name") or "").lower(): a for a in artist_meta.values()}
    art_by_id = {r["id"]: r.get("primary_artist_id")
                 for r in (library_rows or []) if r.get("primary_artist_id")}

    groups: dict[str, dict[str, Any]] = {}
    n_name_fallback = 0
    for tid, m in metas.items():
        name = primary_artist(m.get("artist_names"))
        if not name:
            continue
        aid = art_by_id.get(tid)
        if aid:
            key, keyed_by = aid, "id"
        else:
            key, keyed_by = f"name:{name.lower()}", "name"
            n_name_fallback += 1
        g = groups.setdefault(key, {"name": name, "artist_id": aid if aid else None,
                                    "keyed_by": keyed_by, "tids": []})
        g["tids"].append(tid)
        if aid and not g["artist_id"]:
            g["artist_id"], g["keyed_by"] = aid, "id"

    # Fold a name-keyed group into an id-keyed one when the name matches
    # EXACTLY ONE of them. Without this the same artist appears twice — some of
    # Muse's tracks carry no primary_artist_id, so "Muse" rendered as two cards
    # (caught by searching the live index). An AMBIGUOUS name (matching two
    # different ids) is left split on purpose: that is the case where merging
    # would fuse two different artists, which is the whole reason the fallback
    # is counted rather than silent.
    by_name_key: dict[str, list[str]] = {}
    for key, g in groups.items():
        if g["keyed_by"] == "id":
            by_name_key.setdefault(g["name"].lower(), []).append(key)
    n_folded_tracks = 0
    for key in [k for k, g in groups.items() if g["keyed_by"] == "name"]:
        g = groups[key]
        targets = by_name_key.get(g["name"].lower(), [])
        if len(targets) == 1:
            groups[targets[0]]["tids"].extend(g["tids"])
            groups[targets[0]]["n_name_matched"] = (
                groups[targets[0]].get("n_name_matched", 0) + len(g["tids"]))
            n_folded_tracks += len(g["tids"])
            del groups[key]

    cards: list[dict[str, Any]] = []
    for g in groups.values():
        aid = g["artist_id"]
        am = by_id.get(aid) or by_name.get(g["name"].lower(), {})
        analyzed = [t for t in g["tids"] if t in perceptual]
        feats = {c: _mean([float(perceptual[t][c]) for t in analyzed
                           if isinstance(perceptual[t].get(c), (int, float))])
                 for c in _CARD_FEATURES}
        cards.append({
            "name": g["name"],
            "artist_id": aid,
            "genres": am.get("genres") or "",
            "popularity": am.get("popularity"),
            "followers": am.get("followers"),
            "image": am.get("image_url"),
            "n_tracks": len(g["tids"]),
            "n_analyzed": len(analyzed),
            "feat": feats,
            "keyed_by": g["keyed_by"],
            # how many of this artist's tracks were matched by NAME, not id
            "n_name_matched": g.get("n_name_matched", 0),
        })
    cards.sort(key=lambda c: (-c["n_analyzed"], c["name"].lower()))
    return {
        "cards": cards,
        "n_artists": len(cards),
        # Stated, not hidden: how much of the index rests on a name match, and
        # how many artists we cannot link to a page at all.
        "n_name_keyed": sum(1 for c in cards if c["keyed_by"] == "name"),
        "n_tracks_name_matched": n_name_fallback,
        "n_tracks_folded_by_name": n_folded_tracks,
        "n_linkable": sum(1 for c in cards if c["artist_id"]),
        "n_with_genres": sum(1 for c in cards if c["genres"]),
    }


def search_artists(cards: list[dict], q: Optional[str]) -> list[dict]:
    """Substring match on the artist name (case-insensitive). Empty q = all."""
    term = (q or "").strip().lower()
    if not term:
        return list(cards)
    return [c for c in cards if term in c["name"].lower()]


def artists_view(index: dict[str, Any], *, q: str = "", genre: str = "",
                 mine_names: Optional[set[str]] = None) -> dict[str, Any]:
    """Filter the corpus index for one page render.

    Filtering happens over the WHOLE index here; `page_slice` only ever slices
    THIS output, so a page-local sort is unrepresentable — the /library
    discipline, reused rather than reinvented.
    """
    cards = index["cards"]
    if mine_names is not None:
        lower = {n.lower() for n in mine_names}
        cards = [c for c in cards if c["name"].lower() in lower]
    cards = filter_by_genre(cards, genre)
    cards = search_artists(cards, q)
    return {
        "rows": cards,
        "shown": len(cards),
        "total": index["n_artists"],
        "n_linkable": index["n_linkable"],
        "n_with_genres": index["n_with_genres"],
        "n_name_keyed": index["n_name_keyed"],
        "n_folded": index["n_tracks_folded_by_name"],
        "q": q,
        "genre": (genre or "").strip().lower(),
    }


# ── R2/R4 (P4.7.3): albums + within-artist chronological drift ───────────────
_ALBUM_FEATURES = ("tempo", "energy", "brightness", "danceability")


def artist_albums(track_ids: list[str], identity: dict[str, dict],
                  perceptual: dict[str, dict],
                  art: Optional[dict[str, str]] = None) -> list[dict[str, Any]]:
    """This artist's releases, oldest first — the discography R2 unlocks.

    Built entirely from metadata the D-70 backfill captured (album name, type,
    release date), so it costs no API call and needs no MusicBrainz (D-61).

    Grouped by (name, type) and dated by the EARLIEST release seen: the live
    data has "Absolution" under both 2003 and 2004 (regional releases) and
    "Will Of The People" as both an album and a single. Collapsing on name
    alone would fuse an album with its lead single; keeping every release id
    separate would show one record three times.

    HONESTY: the date is Spotify's `release_date`, so a remaster reads as its
    reissue year, not the original recording. Stated in the UI (D-61) rather
    than silently corrected — fixing it properly needs MusicBrainz, which the
    owner deferred.
    """
    art = art or {}
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    n_undated = 0
    for tid in track_ids:
        idt = identity.get(tid) or {}
        name = (idt.get("album_name") or "").strip()
        if not name:
            continue
        kind = (idt.get("album_type") or "album").strip()
        date = (idt.get("album_release_date") or "").strip()
        if not date:
            n_undated += 1
        g = groups.setdefault((name.lower(), kind), {
            "name": name, "type": kind, "date": date, "tids": [],
            "image": None})
        g["tids"].append(tid)
        if date and (not g["date"] or date < g["date"]):
            g["date"] = date
        if not g["image"] and art.get(tid):
            g["image"] = art[tid]

    out: list[dict[str, Any]] = []
    for g in groups.values():
        analyzed = [t for t in g["tids"] if t in perceptual]
        feats = {c: _mean([float(perceptual[t][c]) for t in analyzed
                           if isinstance(perceptual[t].get(c), (int, float))])
                 for c in _ALBUM_FEATURES}
        out.append({
            "name": g["name"], "type": g["type"],
            "date": g["date"], "year": (g["date"] or "")[:4] or None,
            "image": g["image"],
            "n_tracks": len(g["tids"]), "n_analyzed": len(analyzed),
            "feat": feats,
        })
    # Undated releases sort last rather than pretending to be year zero.
    out.sort(key=lambda a: (a["year"] is None, a["year"] or "", a["name"].lower()))
    return out


def artist_drift(albums: list[dict], column: str = "energy",
                 min_albums: int = 3) -> Optional[dict[str, Any]]:
    """How this artist's sound moved across their OWN catalogue (R4a).

    An artist FACT, not a taste fact — valid for an anonymous visitor, unlike
    the listening-window drift on /analytics.

    Returns None under `min_albums` dated, analyzed releases: two points is a
    line through anything, and a "trend" drawn from them would be noise wearing
    a trend's clothes (the journal-#28 degenerate-n rule).
    """
    pts = [a for a in albums
           if a["year"] and a["n_analyzed"] and a["feat"].get(column) is not None]
    if len(pts) < min_albums:
        return None
    first, last = pts[0], pts[-1]
    delta = float(last["feat"][column]) - float(first["feat"][column])
    vals = [float(p["feat"][column]) for p in pts]
    return {
        "column": column,
        "points": [{"year": p["year"], "name": p["name"],
                    "value": float(p["feat"][column])} for p in pts],
        "n": len(pts),
        "from_year": first["year"], "to_year": last["year"],
        "delta": round(delta, 4),
        "min": min(vals), "max": max(vals),
        "direction": "up" if delta > 0 else ("down" if delta < 0 else "flat"),
    }


def artist_signature(track_ids: list[str], features: dict[str, dict],
                     population: list[dict], min_tracks: int = 3
                     ) -> Optional[dict[str, Any]]:
    """This artist's acoustic character vs the corpus, plus their SPREAD (R3).

    Calls `analytics.acoustic_signature` rather than reimplementing it: the
    words ("louder", "brighter") and the ±2σ bar cap live in one registry
    (P4.7.0 / scales.py), and a second copy would drift the day one is retuned.

    The spread is the part a centroid distance structurally cannot say. An
    artist at high within-catalogue variance is a RANGE artist; one at low
    variance is a formula — and "similar in your library" collapses both to a
    single point, so it can never tell them apart.
    """
    from .analytics import acoustic_signature

    rows = [features[t] for t in track_ids if t in features]
    if len(rows) < min_tracks or len(population) < 3:
        return None
    sig = acoustic_signature(rows, population)
    if not sig:
        return None

    # Spread per signature dimension, in the SAME σ units as the signature, so
    # the two numbers are comparable rather than merely adjacent.
    spread: list[dict[str, Any]] = []
    for col, label, _hi, _lo in scales.signature_dims():
        pop = [float(r[col]) for r in population
               if isinstance(r.get(col), (int, float))]
        mine = [float(r[col]) for r in rows if isinstance(r.get(col), (int, float))]
        if len(pop) < 3 or len(mine) < min_tracks:
            continue
        p_mean = sum(pop) / len(pop)
        p_std = (sum((v - p_mean) ** 2 for v in pop) / len(pop)) ** 0.5
        if p_std == 0:
            continue
        m_mean = sum(mine) / len(mine)
        m_std = (sum((v - m_mean) ** 2 for v in mine) / len(mine)) ** 0.5
        spread.append({"feature": label, "sigma": round(m_std / p_std, 2)})
    spread.sort(key=lambda d: -d["sigma"])

    widest = spread[0] if spread else None
    narrowest = spread[-1] if spread else None
    return {
        "signature": sig,
        "spread": spread,
        "n_tracks": len(rows),
        "widest": widest,
        "narrowest": narrowest,
        # >1 means they vary MORE than the corpus does on that dimension.
        "range_artist": bool(widest and widest["sigma"] > 1.0),
    }
