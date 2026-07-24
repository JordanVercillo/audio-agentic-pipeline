"""
dedup.py — pure near-duplicate detection (Epic O / D-28, inverted by O4).

Detects tracks that are the SAME recording under different spotify_track_ids
(album vs single vs deluxe, two releases of one master). This is a FLAG +
acquisition guard, NEVER a canonical-id join key: the bridge key stays
spotify_track_id. This module owns the single definition of "duplicate" shared
by the serving cache and the warehouse audit; it is stdlib-only on purpose so
the standalone (uv-isolated) audit can exec_module it with no extra deps.

O4 — THE DOCTRINE INVERSION (owner, 2026-07-24): "if a track is in a separate
album or single they should be treated as one; the only difference should be if
there is different audio for a different version — a remix or live version,
acoustic, etc."

The pre-O4 rule did the opposite of that sentence. `normalize_title` STRIPPED
version qualifiers, so a remix and its original landed in one bucket, and what
kept them apart was incidental — a credited remixer changing the artist string,
or a duration gap. Meanwhile exact full-artist-string equality blocked the
release-level merges the owner actually wants. So O4:

  * EXTRACTS the qualifier instead of discarding it (`parse_title`), and merges
    only when base AND version_tag agree — tag EQUALITY, not tag absence, since
    "It Gets Better - Forever Mix" ships on two releases and both carry the tag;
  * is RELEASE-blind and CREDIT-blind on the artist side (O4b), guarded by a
    tight duration window whenever the credit strings disagree;
  * adds a DURATION-LED pass (O4c) so two spellings of one title still merge;
  * reports pairs the metadata calls one recording and the acoustics refuse
    (O4d `find_disagreements`) — a provenance defect, not a dedup decision.

Precision over recall, and the asymmetry is deliberate: a FALSE SPLIT costs one
extra row, while a FALSE MERGE skips a real download AND writes a terminal
`done` job. So an unrecognised qualifier stays in the base (splits), the version
vocabulary stays generous, and the release vocabulary stays stingy.
"""
from __future__ import annotations

import difflib
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional, Sequence

_BRACKET_RE = re.compile(r"[\(\[]([^\)\]]*)[\)\]]")
_DASH_SPLIT_RE = re.compile(r"\s+[-–—]\s+")
_APOS_RE = re.compile("[‘’ʼ']")
_FEAT_TAIL_RE = re.compile(r"\s*\b(?:feat|ft|featuring)\b\.?\s.*$", re.I)
_NONALNUM_RE = re.compile(r"[^a-z0-9]+")

_CREDIT, _VERSION, _RELEASE, _UNKNOWN = "CREDIT", "VERSION", "RELEASE", "UNKNOWN"

# DIFFERENT AUDIO → never merge. `re-?mix\w*` on purpose: this corpus carries
# "Bliss - XX Anniversary RemiXX", which \bremix\b misses. "mix(ed)" is here by
# the owner's 2026-07-24 call: a continuous DJ "- Mixed" edit is different audio
# (132–175 s from its sibling, z-cosine 0.66–0.80), so it splits like a remix.
_VERSION_RE = re.compile(
    r"\b(?:re-?mix\w*|rmx|live|acoustic|unplugged|instrumental|karaoke|demo|"
    r"sessions?|cover|edits?|vip|dub|extended|mix(?:ed|es)?|sped\s*up|slowed|"
    r"reprise|re-?record(?:ed|ing)|taylors\s*version|alternate|bootleg|flip|"
    r"refix|rework|speed\s*garage|take\s*\d+)\b", re.I)
# SAME RECORDING → ignore. This is the release packaging being collapsed, and
# it is deliberately the SHORTER list: a keyword that lands here wrongly causes
# a false merge, the expensive direction.
_RELEASE_RE = re.compile(
    r"\b(?:remaster\w*|deluxe|anniversary|expanded|bonus(?:\s*track)?|"
    r"single\s*version|album\s*version|original\s*version|explicit|clean|"
    r"mono|stereo|re-?issue|special\s*edition|standard)\b", re.I)
# "- From \"Shrek 2\" Soundtrack" / "(from the series Arcane)". Narrow on
# purpose: a bare "- From The Ashes" is a SUBTITLE and must survive.
_FROM_WORK_RE = re.compile(
    r"^from\b.*\b(?:motion\s*picture|soundtrack|series|film|movie|musical)\b"
    r"|^from\s+[\"'“‘]", re.I)
_CREDIT_RE = re.compile(r"^\s*(?:feat|ft|featuring|with|w/|prod|produced\s+by)\b", re.I)

_DIGITS_RE = re.compile(r"\d+")
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
# Noise INSIDE a tag: "Acoustic" and "Acoustic Version" are one version;
# "2011 Remaster" and "Remastered" are one release.
_TAG_NOISE_RE = re.compile(r"\b(?:version|the|a|an|of)\b", re.I)

# Real dupes in this corpus differ by <1.1s (measured: max 1048 ms across all 35
# true twin pairs); ±7s tolerates a remaster while base+tag+artist stays the
# strong gate.
DEFAULT_DURATION_WINDOW_MS = 7000
# O4b: when the two full credit strings DISAGREE we have given up the artist
# guard, and the version tag is the only metadata guard left. Measured on the
# live corpus, every credit-differing same-base pair is a REMIX of its partner —
# one of them only 6860 ms away, INSIDE the normal window. So credit-blind
# merges demand a tight, PRESENT duration agreement. Cost: 0 real merges.
CREDIT_BLIND_WINDOW_MS = 1500
# Reject-only tiebreak over the caller's z-scored vectors: an acoustically
# distant pair (a cover, a different same-titled song) is NOT merged. Measured:
# true twins 0.9826–1.0000, real version pairs −0.24…+0.68, random pairs 0.275%
# above this line.
DEFAULT_COSINE_MIN = 0.95
# O4c: how alike two parsed BASES must be for an exact-duration match to merge.
# Measured on the live corpus, the wanted pairs score 0.941/0.980 and the next
# candidate down is 0.333 — this sits in an empty band 0.60 wide.
DEFAULT_TITLE_SIMILARITY_MIN = 0.80


def _strip_diacritics(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def _classify(segment: str) -> str:
    """CREDIT / VERSION / RELEASE / UNKNOWN for ONE extracted segment.

    VERSION wins ties on purpose ("XX Anniversary RemiXX" is a remix, not a
    reissue): mistaking a remix for release packaging is the expensive error.
    UNKNOWN is the safe default — the segment goes back into the base, so an
    unrecognised qualifier splits rather than merges."""
    if _CREDIT_RE.search(segment):
        return _CREDIT
    if _VERSION_RE.search(segment):
        return _VERSION
    if _RELEASE_RE.search(segment) or _FROM_WORK_RE.search(segment):
        return _RELEASE
    return _UNKNOWN


def _norm_tag(segment: str) -> str:
    t = _TAG_NOISE_RE.sub(" ", _YEAR_RE.sub(" ", segment.lower()))
    return " ".join(_NONALNUM_RE.sub(" ", t).split())


def parse_title(name: Optional[str]) -> tuple[str, str]:
    """(base, version_tag) — the O4a contract.

    base        the recording's name, release/credit packaging removed
    version_tag ' + '-joined sorted VERSION qualifiers ('' = the plain take)

    A merge requires BOTH to be equal. The tag is the normalized qualifier TEXT,
    not the matched keyword, which is what makes tag equality the rule:

        "It Gets Better - Forever Mix" ×2   → ("it gets better", "forever mix") → merge
        "Air Maxes" / "Air Maxes - KETTAMA MIX" → tags "" vs "kettama mix"     → split
        "Shapes (Oh Will)"                 → ("shapes oh will", "")  subtitle survives
        "JOY (If You Want)" / "JOY (By My Side)" → different bases    → split

    Pure, deterministic, stdlib-only."""
    if not name:
        return "", ""
    s = _APOS_RE.sub("", _strip_diacritics(str(name)))
    tags: set[str] = set()

    def _bracket(m: "re.Match[str]") -> str:
        inner = m.group(1)
        kind = _classify(inner)
        if kind == _VERSION:
            tags.add(_norm_tag(inner))
            return " "
        if kind in (_CREDIT, _RELEASE):
            return " "
        return f" {inner} "        # a real subtitle survives: "Shapes (Oh Will)"

    s = _BRACKET_RE.sub(_bracket, s)

    # Peel " - " tails right-to-left, STOPPING at the first non-qualifier, so
    # "Undone - The Sweater Song" keeps its subtitle while "X - Remastered -
    # Live" gives up both.
    while True:
        parts = _DASH_SPLIT_RE.split(s)
        if len(parts) < 2:
            break
        kind = _classify(parts[-1])
        if kind == _VERSION:
            tags.add(_norm_tag(parts[-1]))
        elif kind not in (_CREDIT, _RELEASE):
            break
        s = " - ".join(parts[:-1])

    s = _FEAT_TAIL_RE.sub(" ", s)
    base = " ".join(_NONALNUM_RE.sub(" ", s.lower()).split())
    return base, " + ".join(sorted(t for t in tags if t))


def normalize_title(name: Optional[str]) -> str:
    """The O4a base. Kept under its old name because the cache and the audit
    both import it — but its MEANING inverted: it no longer strips version
    qualifiers, it separates them (see `parse_title`). One definition, not two."""
    return parse_title(name)[0]


def normalize_artist(artist: Optional[str]) -> str:
    """Conservative: lowercase + strip diacritics/punct only. Deliberately does
    NOT split multi-artist strings — over-splitting risks FALSE merges."""
    if not artist:
        return ""
    s = _strip_diacritics(str(artist)).lower()
    return " ".join(_NONALNUM_RE.sub(" ", s).split())


def _leading_artist(artist: Optional[str]) -> str:
    """The normalized LEADING credit (O4b), so an album's "A" matches a single's
    "A, B". Known limitation: an artist whose NAME contains a comma ("Tyler, The
    Creator") truncates — acceptable because primary_artist_id wins whenever both
    sides carry one, and base+tag+duration must still agree."""
    return normalize_artist((artist or "").split(",")[0])


@dataclass(frozen=True)
class DedupRecord:
    track_id: str
    title: str
    artist: str
    duration_ms: Optional[int] = None
    vector: Optional[Sequence[float]] = None  # z-scored acoustic vector (tiebreak)
    is_cached: bool = False                    # has analyzed features → canonical-preferred
    # O4b — appended LAST with a default on purpose: the cache builds records
    # POSITIONALLY and the uv-isolated audit builds them with keywords. A field
    # inserted anywhere else breaks the audit at import time.
    primary_artist_id: Optional[str] = None


@dataclass(frozen=True)
class DuplicateCluster:
    canonical_id: str          # the spotify_track_id others REFERENCE (not a new id)
    members: tuple[str, ...]   # sorted, includes the canonical

    @property
    def duplicate_ids(self) -> tuple[str, ...]:
        return tuple(m for m in self.members if m != self.canonical_id)


@dataclass(frozen=True)
class Disagreement:
    """O4d — a pair the METADATA says is one recording and the ACOUSTICS refuse."""
    track_id_a: str            # sorted, so the pair has one stable identity
    track_id_b: str
    z_cosine: float
    duration_delta_ms: Optional[int]


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


def _title_similarity(a: str, b: str) -> float:
    """difflib ratio over the parsed BASES. Character-level on purpose: the real
    cases are a spelling variant ("Lookin'"/"Looking") and a spacing variant
    ("Airmaxes"/"Air Maxes") — a token-set score rates the second 0.33."""
    return difflib.SequenceMatcher(None, a, b).ratio()


def _same_numbering(a: str, b: str) -> bool:
    """Numbers in a title are IDENTITY, not spelling. "Club 0"/"Club 1" score
    0.83 on difflib and "Part 1"/"Part 2" score 0.83 — high enough to clear any
    similarity floor loose enough to catch a real spelling variant. So the
    duration-led pass additionally demands that the digit sequences match; a
    differing number means a differing track, full stop."""
    return _DIGITS_RE.findall(a) == _DIGITS_RE.findall(b)


def _artist_ok(a: DedupRecord, b: DedupRecord) -> bool:
    """Release-blind, credit-blind artist agreement (O4b). album_name never gates
    a merge — it is the thing being collapsed."""
    if a.primary_artist_id and b.primary_artist_id:
        return a.primary_artist_id == b.primary_artist_id
    la, lb = _leading_artist(a.artist), _leading_artist(b.artist)
    return bool(la) and la == lb


def _within_window(a: DedupRecord, b: DedupRecord, w: int,
                   credit_blind_w: int = CREDIT_BLIND_WINDOW_MS) -> bool:
    if normalize_artist(a.artist) != normalize_artist(b.artist):
        # Credit-blind: the full strings differ, so the tag is the last guard.
        if a.duration_ms is None or b.duration_ms is None:
            return False
        return abs(int(a.duration_ms) - int(b.duration_ms)) <= credit_blind_w
    # Unknown duration collapses to a base+tag+artist match (already strong).
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
    title_similarity_min: float = DEFAULT_TITLE_SIMILARITY_MIN,
    credit_blind_window_ms: int = CREDIT_BLIND_WINDOW_MS,
) -> list[DuplicateCluster]:
    """Cluster same-recording tracks across TWO keyings under ONE union-find, so
    the result is the connected components rather than an artifact of iteration
    order. Deterministic; singletons excluded."""
    parsed = {r.track_id: parse_title(r.title) for r in records}
    parent = {r.track_id: r.track_id for r in records}

    def _pair_ok(a: DedupRecord, b: DedupRecord) -> bool:
        return (_artist_ok(a, b)
                and _within_window(a, b, duration_window_ms, credit_blind_window_ms)
                and _acoustically_ok(a, b, cosine_min))

    # pass 1 — (base, version_tag) keyed
    buckets: dict[tuple[str, str], list[DedupRecord]] = {}
    for r in records:
        base, tag = parsed[r.track_id]
        if base:
            buckets.setdefault((base, tag), []).append(r)
    for rs in buckets.values():
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                if _pair_ok(rs[i], rs[j]):
                    parent[_find(parent, rs[i].track_id)] = _find(parent, rs[j].track_id)

    # pass 2 — O4c duration-led: EXACT duration equality makes two differently
    # SPELLED titles a candidate ("Here's Lookin'"/"Here's Looking"; "Airmaxes"/
    # "Air Maxes"). Bucketed on duration alone (tiny groups) so the artist rule
    # stays in ONE place. Still requires equal version tags, the title floor and
    # every pass-1 guard.
    dur_buckets: dict[int, list[DedupRecord]] = {}
    for r in records:
        if r.duration_ms is not None:
            dur_buckets.setdefault(int(r.duration_ms), []).append(r)
    for rs in dur_buckets.values():
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                a, b = rs[i], rs[j]
                if _find(parent, a.track_id) == _find(parent, b.track_id):
                    continue
                (abase, atag), (bbase, btag) = parsed[a.track_id], parsed[b.track_id]
                if not abase or not bbase or atag != btag:
                    continue
                if not _same_numbering(abase, bbase):
                    continue
                if _title_similarity(abase, bbase) < title_similarity_min:
                    continue
                if _pair_ok(a, b):
                    parent[_find(parent, a.track_id)] = _find(parent, b.track_id)

    groups: dict[str, list[DedupRecord]] = {}
    for r in records:
        groups.setdefault(_find(parent, r.track_id), []).append(r)
    clusters = [DuplicateCluster(canonical_id=min(m, key=_canonical_key).track_id,
                                 members=tuple(sorted(x.track_id for x in m)))
                for m in groups.values() if len(m) >= 2]
    clusters.sort(key=lambda c: c.members)
    return clusters


def find_disagreements(
    records: Sequence[DedupRecord], *,
    duration_window_ms: int = DEFAULT_DURATION_WINDOW_MS,
    cosine_min: float = DEFAULT_COSINE_MIN,
    credit_blind_window_ms: int = CREDIT_BLIND_WINDOW_MS,
) -> list[Disagreement]:
    """O4d — same base, same version_tag, same artist, inside the window, BOTH
    cached, and z-cosine BELOW cosine_min: the ONLY gate that refused the merge
    is the acoustic one. That is not a dedup decision — it means at least one of
    the two acquisitions is the wrong audio (D-59's failure mode wearing a
    different id).

    Precision over recall, deliberately: it requires BOTH vectors (a
    half-analyzed pair is silent, never accusatory) and only considers
    TITLE-keyed candidates — an exact-duration coincidence is far too weak a
    claim of "one recording" to accuse an acquisition of being wrong. It will
    MISS disagreements rather than cry wolf at a track that is fine."""
    parsed = {r.track_id: parse_title(r.title) for r in records}
    buckets: dict[tuple[str, str], list[DedupRecord]] = {}
    for r in records:
        base, tag = parsed[r.track_id]
        if base and r.vector is not None:
            buckets.setdefault((base, tag), []).append(r)
    out: list[Disagreement] = []
    for rs in buckets.values():
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                a, b = rs[i], rs[j]
                if not (_artist_ok(a, b)
                        and _within_window(a, b, duration_window_ms,
                                           credit_blind_window_ms)):
                    continue
                cos = _cosine(a.vector, b.vector)
                if cos >= cosine_min:
                    continue                      # merged — not a disagreement
                x, y = sorted((a.track_id, b.track_id))
                delta = (None if a.duration_ms is None or b.duration_ms is None
                         else abs(int(a.duration_ms) - int(b.duration_ms)))
                out.append(Disagreement(x, y, round(cos, 6), delta))
    out.sort(key=lambda d: (d.track_id_a, d.track_id_b))
    return out


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
