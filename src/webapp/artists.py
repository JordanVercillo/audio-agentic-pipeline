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
