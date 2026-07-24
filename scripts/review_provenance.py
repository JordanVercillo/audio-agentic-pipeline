"""
review_provenance.py — the Q4 provenance-health review (the last Epic-Q slice).

The mirror of `review_chat_logs.py` for acquisition provenance. `qa_audit.py`
proves the INVARIANTS (no DJ set, no wrong-title match, 100% of the aggregate
corpus sourced); this is the SAMPLED read on match QUALITY: of the corpus that
predates the strict match_gate, how much would still pass it, and is the tail
that wouldn't legit remixes/label uploads or real misses that want a repair?

    uv run python scripts/review_provenance.py --report      # aggregates -> evals/runs/
    uv run python scripts/review_provenance.py --sample 20   # a gitignored eyeball worksheet

The report is aggregates-only (no external titles — safe to commit). Worksheets
live under data/provenance_review/ (gitignored — untrusted external text never
reaches the public repo, rule 7 / the Q2 |safe lesson). Read-only: no downloads,
no writes to the corpus, no network.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.store import provenance_review as pr  # noqa: E402
from src.store.cache import FeatureCache  # noqa: E402

_WORKSHEETS = _ROOT / "data" / "provenance_review"
_RUNS = _ROOT / "evals" / "runs"


def _current_events(cache: FeatureCache) -> list[dict]:
    """The provenance MART's shape, computed live: the latest event per bridge
    key, twins excluded (a twin rides its canonical). Mirrors
    semantic.build_provenance_mart so the report never reads a stale parquet."""
    twins = cache.twin_ids()
    seen: set[str] = set()
    current: list[dict] = []
    for r in cache.all_provenance():          # newest-first
        tid = r.get("spotify_track_id")
        if tid in seen or tid in twins:
            continue
        seen.add(tid)
        current.append(r)
    return current


def _metas(cache: FeatureCache) -> dict[str, dict]:
    """name + artist + duration_ms per track, for the match-quality judgement."""
    base = cache.all_meta()
    durs = cache.all_durations_ms()
    return {tid: {**m, "duration_ms": durs.get(tid)} for tid, m in base.items()}


def _n_canonical(cache: FeatureCache) -> int:
    """Canonical analyzed tracks — the coverage denominator (analyzed − twins)."""
    return len(set(cache.all_features()) - cache.twin_ids())


def cmd_report(cache: FeatureCache) -> int:
    events = _current_events(cache)
    if not events:
        print("no provenance events yet — nothing to review.")
        return 0
    ch = pr.characterize_all(events, _metas(cache))
    report = pr.aggregate(ch, n_canonical=_n_canonical(cache))
    text = pr.format_report(report)
    print(text)
    _RUNS.mkdir(parents=True, exist_ok=True)
    out = _RUNS / f"{date.today().isoformat()}_provenance_review.txt"
    out.write_text(text + "\n", encoding="utf-8")
    print(f"\nwrote aggregates-only report -> {out}")
    return 0


def cmd_sample(cache: FeatureCache, size: int) -> int:
    metas = _metas(cache)
    ch = pr.characterize_all(_current_events(cache), metas)
    cards = pr.render_worksheet(pr.stratified_sample(ch, size), metas)
    if not cards:
        print("no provenance events to sample.")
        return 0
    _WORKSHEETS.mkdir(parents=True, exist_ok=True)
    out = _WORKSHEETS / f"{date.today().isoformat()}_worksheet.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for c in cards:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    n_review = sum(1 for c in cards if c["tier"] == pr.TIER_REVIEW)
    print(f"wrote {len(cards)} cards ({n_review} in the review tier) -> {out}")
    print("open each: does 'youtube_title' look like 'track' by 'artist'? "
          "a real miss → repair it via /library?filter=needs-source.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Q4 provenance-health review.")
    p.add_argument("--report", action="store_true",
                   help="aggregates-only health report -> evals/runs/")
    p.add_argument("--sample", type=int, metavar="N",
                   help="write a gitignored eyeball worksheet of N stratified cards")
    args = p.parse_args()
    cache = FeatureCache()
    if args.sample:
        return cmd_sample(cache, args.sample)
    if args.report:
        return cmd_report(cache)
    p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
