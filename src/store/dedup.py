"""
dedup.py — pure near-duplicate detection (Epic O / D-28).

Detects tracks that are the SAME recording under different spotify_track_ids
(remaster vs original, two album releases). This is a FLAG + acquisition guard,
NEVER a canonical-id join key: the bridge key stays spotify_track_id. This module
owns the single definition of "duplicate" shared by the serving cache and the
warehouse audit; it is stdlib-only on purpose so the standalone (uv-isolated)
audit can exec_module it with no extra deps.

Precision over recall: the cost of a FALSE positive is skipping a real download,
so the rules bias toward missing a dupe rather than merging two distinct tracks.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional, Sequence

# Same-recording variants collapse to one normalized title; distinct-song safety
# comes from the " - " / "(...)" gate (only strip qualifiers, never plain words).
_PAREN_RE = re.compile(r"[\(\[][^\)\]]*[\)\]]")
_VERSION_TAIL_RE = re.compile(
    r"\s+[-–]\s+.*\b(?:remaster(?:ed)?|live|acoustic|radio\s*edit|remix|mix|mono|"
    r"stereo|single\s*version|album\s*version|deluxe|bonus|re-?recorded|"
    r"anniversary|edit|version|demo|session)\b.*$", re.I)
_FEAT_RE = re.compile(r"\s*[\(\[]?\s*\b(?:feat|ft|featuring)\b\.?\s.*$", re.I)
_NONALNUM_RE = re.compile(r"[^a-z0-9]+")

# Real dupes in this corpus differ by <1.1s; ±7s tolerates a remaster/edit while
# the exact name+artist match remains the strong gate. Tunable on real data.
DEFAULT_DURATION_WINDOW_MS = 7000
# Reject-only tiebreak: when BOTH tracks are cached, an acoustically-distant pair
# (a cover, a genuinely different same-titled song) is NOT merged. Lenient so it
# never wrongly rejects a true dupe. Tunable (journal-style) on the corpus.
DEFAULT_COSINE_MIN = 0.95


def _strip_diacritics(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def normalize_title(name: Optional[str]) -> str:
    """Lowercased, diacritic-/punct-stripped title with feat./remaster/live/edit
    qualifiers removed. Empty string for a missing title (never a dupe candidate)."""
    if not name:
        return ""
    s = _strip_diacritics(str(name)).lower()
    s = _PAREN_RE.sub(" ", s)          # (Remastered 2011) / [Live] / (feat. X)
    s = _VERSION_TAIL_RE.sub(" ", s)   # " - 2019 Remaster" / " - Live at Wembley"
    s = _FEAT_RE.sub(" ", s)           # "feat. X" not in parens
    s = _NONALNUM_RE.sub(" ", s)
    return " ".join(s.split())


def normalize_artist(artist: Optional[str]) -> str:
    """Conservative: lowercase + strip diacritics/punct only. Deliberately does
    NOT split multi-artist strings — over-splitting risks FALSE merges."""
    if not artist:
        return ""
    s = _strip_diacritics(str(artist)).lower()
    return " ".join(_NONALNUM_RE.sub(" ", s).split())


@dataclass(frozen=True)
class DedupRecord:
    track_id: str
    title: str
    artist: str
    duration_ms: Optional[int] = None
    vector: Optional[Sequence[float]] = None  # acoustic vector (cosine tiebreak)
    is_cached: bool = False                    # has analyzed features → canonical-preferred


@dataclass(frozen=True)
class DuplicateCluster:
    canonical_id: str          # the spotify_track_id others REFERENCE (not a new id)
    members: tuple[str, ...]   # sorted, includes the canonical

    @property
    def duplicate_ids(self) -> tuple[str, ...]:
        return tuple(m for m in self.members if m != self.canonical_id)


def _find(parent: dict[str, str], x: str) -> str:
    """Union-find root with path compression (module-level so it never closes
    over a loop variable — B023)."""
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    num = sum(x * y for x, y in zip(a, b, strict=False))
    da = math.sqrt(sum(x * x for x in a))
    db = math.sqrt(sum(y * y for y in b))
    return 0.0 if da == 0 or db == 0 else num / (da * db)


def _within_window(a: DedupRecord, b: DedupRecord, w: int) -> bool:
    # Unknown duration collapses to a name+artist match (the exact normalized
    # name+artist match is already a strong signal).
    if a.duration_ms is None or b.duration_ms is None:
        return True
    return abs(int(a.duration_ms) - int(b.duration_ms)) <= w


def _acoustically_ok(a: DedupRecord, b: DedupRecord, cmin: float) -> bool:
    # Tiebreak fires ONLY when both are cached; reject-only (raises precision).
    if a.vector is None or b.vector is None:
        return True
    return _cosine(a.vector, b.vector) >= cmin


def _canonical_key(r: DedupRecord):
    # Prefer the cached (analyzed) track, then the longer take, then smallest id.
    return (not r.is_cached, -(r.duration_ms or -1), r.track_id)


def find_duplicate_clusters(
    records: Sequence[DedupRecord], *,
    duration_window_ms: int = DEFAULT_DURATION_WINDOW_MS,
    cosine_min: float = DEFAULT_COSINE_MIN,
) -> list[DuplicateCluster]:
    """Cluster same-recording tracks. Deterministic; singletons excluded."""
    buckets: dict[tuple[str, str], list[DedupRecord]] = {}
    for r in records:
        t = normalize_title(r.title)
        if not t:
            continue
        buckets.setdefault((t, normalize_artist(r.artist)), []).append(r)

    clusters: list[DuplicateCluster] = []
    for rs in buckets.values():
        if len(rs) < 2:
            continue
        parent = {r.track_id: r.track_id for r in rs}
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                if _within_window(rs[i], rs[j], duration_window_ms) and \
                        _acoustically_ok(rs[i], rs[j], cosine_min):
                    parent[_find(parent, rs[i].track_id)] = _find(parent, rs[j].track_id)

        groups: dict[str, list[DedupRecord]] = {}
        for r in rs:
            groups.setdefault(_find(parent, r.track_id), []).append(r)
        for members in groups.values():
            if len(members) < 2:
                continue
            canon = min(members, key=_canonical_key).track_id
            clusters.append(DuplicateCluster(
                canonical_id=canon,
                members=tuple(sorted(m.track_id for m in members))))
    clusters.sort(key=lambda c: c.members)
    return clusters


def canonicalize_ids(ids: Sequence[str], dupe_map: dict[str, str]) -> list[str]:
    """Map each id to its canonical and dedupe PRESERVING first-occurrence order
    (O3a): a twin whose canonical already appeared is dropped; a twin appearing
    before its canonical takes the canonical's identity at the twin's rank.
    Pure — the one canonicalization every range_ids producer shares."""
    out: list[str] = []
    seen: set[str] = set()
    for tid in ids:
        canon = dupe_map.get(tid, tid)
        if canon not in seen:
            seen.add(canon)
            out.append(canon)
    return out


def canonicalize_range_ids(range_ids: dict[str, list[str]],
                           dupe_map: dict[str, str]) -> dict[str, list[str]]:
    """canonicalize_ids per time-range window (the taste plane's producers)."""
    return {w: canonicalize_ids(ids, dupe_map) for w, ids in (range_ids or {}).items()}


def duplicate_of_map(records: Sequence[DedupRecord], **kw) -> dict[str, str]:
    """{duplicate_id: canonical_id} for every non-canonical member. This is what
    the cache stores in TrackMeta.duplicate_of — canonical is always an existing
    spotify_track_id in the same cluster."""
    out: dict[str, str] = {}
    for c in find_duplicate_clusters(records, **kw):
        for d in c.duplicate_ids:
            out[d] = c.canonical_id
    return out
