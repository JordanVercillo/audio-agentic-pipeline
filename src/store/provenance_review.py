"""
provenance_review.py — the Q4 provenance-health flywheel (pure logic).

The mirror of `chat_review` (D-47) for acquisition provenance: take the current
provenance events, CHARACTERIZE each against today's acceptance gate, sample the
ones that want human eyes (escaped — external titles are untrusted), and
aggregate an aggregates-only health report for `evals/runs/`.

`qa_audit.py` proves the INVARIANTS hold (no DJ set, no wrong-title match, 100%
of the aggregate corpus sourced). This is the complementary SAMPLED read on
match QUALITY: of the corpus that predates the strict `match_gate`, how much
would still pass it, and of the tail that wouldn't — is it legitimate remixes
and label uploads, or real misses that want a D-56 repair? A count, not a vibe.

Pure — no I/O, no DB, no network. The caller supplies the rows.
"""

from __future__ import annotations

import html
from collections import Counter
from typing import Any, Optional

from ..ingestion.match_gate import (
    confident_match,
    rejection_reason,
    title_recall,
)

# How much of the song's title must be recognisable in the acquired candidate
# before we stop calling it a real-miss. Below this the SONG NAME isn't there —
# the signal every confirmed wrong-song acquisition shared ("Up & Down" ←
# "Spice Up My Life"). Above it the recording is probably right and only fails
# the strict auto-accept gate on order/spelling/duration/channel.
_TITLE_PRESENT_MIN = 0.6

# The tiers a provenance row falls into. Order = worst-needs-eyes first, so the
# sampler over-weights `review` the way chat_review over-samples the degraded
# fallback turns. These DESCRIBE the row, they are not a verdict: the review
# tier is a worklist for human eyes, not a claim the track is wrong (this tool
# writes nothing — qa_audit owns the hard invariants).
TIER_REVIEW = "review"            # the song's title is NOT recognisable → a real-miss candidate
TIER_TITLE_PRESENT = "title_present"  # fails the strict gate but the song name IS there (remix/edit/order/spelling)
TIER_VERIFIED = "verified"        # passes today's strict auto-accept gate
TIER_OWNER = "owner_supplied"     # a D-56 manual repair — the owner chose it, not the matcher

_TIER_ORDER = (TIER_REVIEW, TIER_TITLE_PRESENT, TIER_VERIFIED, TIER_OWNER)


def _is_manual(row: dict) -> bool:
    return str(row.get("matcher_version") or "").startswith("manual")


def characterize(prov: dict, meta: Optional[dict]) -> dict[str, Any]:
    """Classify ONE current provenance row against today's `match_gate`.

    `meta` is the track's display row (name / artist / duration_ms); a missing
    meta can't be judged, so it lands in `review`. A manual repair is trusted
    without machine judgement — the owner is better evidence than the gate
    (the same call `qa_audit` makes)."""
    name = (meta or {}).get("name") or (meta or {}).get("track_name")
    artist = (meta or {}).get("artist") or (meta or {}).get("artist_names") or ""
    dur_ms = (meta or {}).get("duration_ms")
    expected_s = (dur_ms / 1000.0) if dur_ms else None
    title, channel = prov.get("youtube_title"), prov.get("channel")

    base = {"id": prov.get("spotify_track_id"),
            "confidence": prov.get("match_confidence"),
            "duration_delta_s": prov.get("duration_delta_s"),
            "matcher_version": prov.get("matcher_version")}

    if _is_manual(prov):
        return {**base, "tier": TIER_OWNER, "reason": "owner-supplied source"}
    if not name:
        return {**base, "tier": TIER_REVIEW, "reason": "no metadata to judge the match"}

    cand = {"title": title, "channel": channel,
            "youtube_duration_s": prov.get("youtube_duration_s")}
    recall = title_recall(name, title)
    if confident_match(name, artist, cand, expected_s):
        return {**base, "tier": TIER_VERIFIED, "reason": "passes the current gate",
                "title_recall": round(recall, 2)}

    # In the tail (fails the strict auto-accept gate). The split is by whether
    # the SONG is recognisable, NOT by re-running the gate's own sub-clauses —
    # the gate deliberately rejects right songs on word order ('Black Sheep -
    # Metric'), spelling ('Rumors'/'Rumours') and artist-in-channel-only, and
    # calling those "wrong" would cry wolf. Title present → probably the right
    # recording failing on a technicality; title absent → the real-miss signal.
    if recall >= _TITLE_PRESENT_MIN:
        return {**base, "tier": TIER_TITLE_PRESENT, "title_recall": round(recall, 2),
                "reason": rejection_reason(name, artist, cand, expected_s)}
    return {**base, "tier": TIER_REVIEW, "title_recall": round(recall, 2),
            "reason": "the song's title is not recognisable in the acquired audio"}


def characterize_all(prov_rows: list[dict], metas: dict[str, dict]) -> list[dict]:
    """Characterize every current provenance row (caller supplies current-per-key,
    twin-free rows — the mart's own shape). Returns rows enriched with tier."""
    return [{**characterize(p, metas.get(p.get("spotify_track_id"))),
             "youtube_title": p.get("youtube_title"), "channel": p.get("channel"),
             "youtube_url": p.get("youtube_url")}
            for p in prov_rows]


# ── sampling (deterministic, over-weight the tier that needs eyes) ────────────
_STRATA: list[tuple[str, int]] = [
    (TIER_REVIEW, 12),        # the whole point — the miss candidates
    (TIER_TITLE_PRESENT, 5),  # spot-check that "title present" really is the right song
    (TIER_VERIFIED, 3),       # a few passes, to confirm the gate isn't rubber-stamping
]


def stratified_sample(characterized: list[dict], size: int = 20) -> list[dict]:
    """Deterministic stratified sample (input order preserved within a tier).
    Fill each stratum to target, then spill remaining slots in tier order. A
    thin stratum contributes what it has — never blocks (mirrors chat_review)."""
    picked: list[dict] = []
    seen: set[str] = set()

    def _key(r: dict) -> str:
        return str(r.get("id"))

    for tier, target in _STRATA:
        n = 0
        for r in characterized:
            if n >= target or len(picked) >= size:
                break
            if r.get("tier") == tier and _key(r) not in seen:
                picked.append(r)
                seen.add(_key(r))
                n += 1
    for tier in _TIER_ORDER:                # spill, worst-first
        for r in characterized:
            if len(picked) >= size:
                break
            if r.get("tier") == tier and _key(r) not in seen:
                picked.append(r)
                seen.add(_key(r))
    return picked[:size]


def render_worksheet(sampled: list[dict], metas: dict[str, dict]) -> list[dict]:
    """One ESCAPED card per sampled row — youtube_title/channel are external,
    untrusted text (the Q2 |safe lesson): a track whose YouTube title is
    `<script>` must render inert in any worksheet viewer."""
    cards = []
    for r in sampled:
        m = metas.get(r.get("id")) or {}
        cards.append({
            "id": r.get("id"),
            "tier": r.get("tier"),
            "reason": r.get("reason"),
            "confidence": r.get("confidence"),
            "duration_delta_s": r.get("duration_delta_s"),
            "track": html.escape(str(m.get("name") or m.get("track_name") or "")),
            "artist": html.escape(str(m.get("artist") or m.get("artist_names") or "")),
            "youtube_title": html.escape(str(r.get("youtube_title") or "")),
            "channel": html.escape(str(r.get("channel") or "")),
            "youtube_url": html.escape(str(r.get("youtube_url") or "")),
            # blanks the human fills: is this the right recording?
            "verdict": None, "notes": None,
        })
    return cards


# ── aggregation (aggregates-only — NO external titles reach evals/runs/) ──────
def _bucketize(values: list[float], edges: list[float]) -> dict[str, int]:
    """Count values into half-open buckets [e0,e1), … , [e_last, inf)."""
    out: dict[str, int] = {}
    labelled = [(f"<{edges[0]}", lambda v: v < edges[0])]
    for a, b in zip(edges, edges[1:], strict=False):
        labelled.append((f"{a}-{b}", (lambda v, a=a, b=b: a <= v < b)))
    labelled.append((f">={edges[-1]}", lambda v: v >= edges[-1]))
    for lab, _ in labelled:
        out[lab] = 0
    for v in values:
        if v is None:
            continue
        for lab, pred in labelled:
            if pred(v):
                out[lab] += 1
                break
    return out


def aggregate(characterized: list[dict], *, n_canonical: int) -> dict[str, Any]:
    """Aggregates-only health report. No raw titles — safe to commit."""
    total = len(characterized)
    tiers = Counter(r.get("tier") for r in characterized)
    machine = [r for r in characterized if r.get("tier") != TIER_OWNER]
    tail = [r for r in machine if r.get("tier") in (TIER_REVIEW, TIER_TITLE_PRESENT)]
    matcher = Counter(r.get("matcher_version") for r in characterized)

    conf = [r.get("confidence") for r in machine if isinstance(r.get("confidence"), (int, float))]
    deltas = [abs(r["duration_delta_s"]) for r in machine
              if isinstance(r.get("duration_delta_s"), (int, float))]

    n_verified = tiers.get(TIER_VERIFIED, 0)
    pct_verified = round(100.0 * n_verified / len(machine), 1) if machine else 0.0
    n_title_present = tiers.get(TIER_TITLE_PRESENT, 0)
    n_review = tiers.get(TIER_REVIEW, 0)
    tail_n = len(tail)
    return {
        "n_current": total,
        "n_canonical": n_canonical,
        "coverage_pct": round(100.0 * total / n_canonical, 1) if n_canonical else 0.0,
        "tiers": {t: tiers.get(t, 0) for t in _TIER_ORDER},
        "machine_matched": len(machine),
        "pct_pass_current_gate": pct_verified,
        "tail": {
            "n": tail_n,
            "title_present": n_title_present,
            "review": n_review,
            "pct_of_machine": round(100.0 * tail_n / len(machine), 1) if machine else 0.0,
        },
        "confidence_buckets": _bucketize(conf, [0.3, 0.5, 0.7, 0.9]),
        "abs_duration_delta_s_buckets": _bucketize(deltas, [3, 10, 30, 120]),
        "matcher_versions": dict(sorted(matcher.items())),
    }


def format_report(report: dict, *, gate_version: str = "match_gate-v1") -> str:
    t = report["tiers"]
    lines = [
        f"== provenance health -- {report['n_current']} current events "
        f"| gate {gate_version} ==",
        f"  coverage      {report['n_current']}/{report['n_canonical']} canonical "
        f"({report['coverage_pct']}%)",
        f"  tiers         verified {t[TIER_VERIFIED]} · title_present "
        f"{t[TIER_TITLE_PRESENT]} · review {t[TIER_REVIEW]} · owner {t[TIER_OWNER]}",
        f"  pass gate     {report['pct_pass_current_gate']}% of "
        f"{report['machine_matched']} machine-matched would re-pass today",
        f"  the tail      {report['tail']['n']} fail the gate "
        f"({report['tail']['pct_of_machine']}% of machine) -> "
        f"{report['tail']['title_present']} title-present (likely right) · "
        f"{report['tail']['review']} want-a-look (title not recognisable)",
        "  confidence    " + " · ".join(
            f"{k}:{v}" for k, v in report["confidence_buckets"].items()),
        "  |dur delta|s  " + " · ".join(
            f"{k}:{v}" for k, v in report["abs_duration_delta_s_buckets"].items()),
        "  matchers      " + " · ".join(
            f"{k}:{v}" for k, v in report["matcher_versions"].items()),
    ]
    return "\n".join(lines)
