"""
drain_repair_queue.py — unattended pass over the needs-source repair queue (QA2).

The queue holds tracks whose audio was refused (wrong version, wrong song, no
plausible candidate) plus the wrong-song acquisitions the quarantine removed.
Draining it by hand is the D-56 flow — paste a link or upload a file. This
script does the part a machine may honestly do: re-search each track and take
the audio ONLY when the evidence is unambiguous.

The bar (`re_extract.repair_acquire`, owner call 2026-07-23) is deliberately
stricter than live ingestion: the artist's own or "X - Topic" channel, the
song's title contained in the video's, length within 10 s, no remake markers.
Measured on the real 72-track queue that admits 5 with zero known-wrong; the
looser live bar admitted 11 including an Ableton remake and two wrong songs.
Nobody reviews these writes, so they must not need reviewing.

    uv run python scripts/drain_repair_queue.py --dry-run   # decide, write nothing
    uv run python scripts/drain_repair_queue.py             # drain for real
    uv run python scripts/drain_repair_queue.py --limit 5

--dry-run performs the searches and prints the verdict per track WITHOUT
downloading, extracting or writing — the safe way to see what a real run would
do. Everything else goes through the Q3 swap discipline: atomic on success
only, provenance as the resume marker, failures to the ledger.
"""

import argparse
import logging
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.ingestion.match_gate import (  # noqa: E402
    rejection_reason,
    select_confident,
)
from src.store.cache import FeatureCache  # noqa: E402
from src.store.re_extract import (  # noqa: E402
    _REPAIR_TOL_S,
    Ledger,
    _search_all_variants,
    repair_acquire,
    run,
)

_DATA = _ROOT / "data"


def needs_source_ids(cache: FeatureCache, ledger: Ledger) -> list[str]:
    """The repair queue: ledgered failures no provenance row has since resolved
    (the same definition the webapp's owner tab uses)."""
    done = {r["spotify_track_id"] for r in cache.all_provenance()}
    return [t for t in sorted(ledger.failed_ids()) if t not in done]


def dry_run(cache: FeatureCache, ids: list[str]) -> int:
    """Search + judge every queued track, write nothing.

    Uses the SAME search path as the real run (`_search_all_variants`) and the
    same artist string. An earlier version searched only the primary artist
    while the runner searched the full credit list, so the two disagreed about
    which tracks were repairable — a dry run that does not predict the real run
    is worse than none."""
    accepted = 0
    for i, tid in enumerate(ids, 1):
        meta = cache.get_meta(tid) or {}
        name = meta.get("track_name")
        artist = meta.get("artist_names") or ""
        dur_ms = meta.get("duration_ms")
        expected = (dur_ms / 1000.0) if dur_ms else None
        if not name:
            print(f"{i:>3}/{len(ids)} SKIP    {tid} — no metadata")
            continue
        cands = _search_all_variants(name, artist, expected)
        chosen = select_confident(cands, name, artist, expected,
                                  require_channel=True, tol_s=_REPAIR_TOL_S)
        if chosen is not None:
            accepted += 1
            print(f"{i:>3}/{len(ids)} ACCEPT  {name!r} — {artist}\n"
                  f"          {chosen['title']!r} | {chosen.get('channel')!r} "
                  f"| {chosen.get('youtube_duration_s') or 0:.0f}s "
                  f"vs {expected or 0:.0f}s")
        else:
            top = max(cands, key=lambda c: c.get("score") or 0) if cands else None
            why = rejection_reason(name, artist, top, expected,
                                   require_channel=True, tol_s=_REPAIR_TOL_S)
            print(f"{i:>3}/{len(ids)} manual  {name!r} — {artist}: {why}")
    print(f"\ndry run: {accepted} of {len(ids)} would be repaired automatically; "
          f"{len(ids) - accepted} need the D-56 manual flow")
    return 0


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    parser = argparse.ArgumentParser(
        description="Drain the needs-source queue at the channel-verified bar.")
    parser.add_argument("--dry-run", action="store_true",
                        help="search + judge only; download and write nothing")
    parser.add_argument("--limit", type=int, default=None,
                        help="cap the tracks attempted this invocation")
    args = parser.parse_args()

    cache = FeatureCache()
    ledger = Ledger(_DATA / "re_extract_ledger.json")
    ids = needs_source_ids(cache, ledger)
    if args.limit:
        ids = ids[:args.limit]
    if not ids:
        print("the repair queue is empty")
        return 0
    print(f"repair queue: {len(ids)} tracks\n")

    if args.dry_run:
        return dry_run(cache, ids)

    logging.getLogger().setLevel(logging.INFO)
    # F3 (red-team): a dedicated scratch dir — NEVER data/raw_audio, where the
    # download would overwrite a pre-existing {id}.mp3 and the transient-delete
    # would then destroy a file this run didn't create.
    scratch = _DATA / "tmp_reextract"
    scratch.mkdir(parents=True, exist_ok=True)
    summary = run(cache,
                  audio_dir=scratch,
                  spectrogram_dir=_DATA / "spectrograms",
                  ledger=ledger,
                  limit=None,
                  retry_failed=True,      # the queue IS the ledgered failures
                  targets=ids,            # incl. quarantined (no features)
                  acquire=repair_acquire,
                  marts_dir=_DATA / "marts")
    print(f"\ndrained: {summary['ok']} repaired · {summary['failed']} still "
          f"need a manual source · {summary['elapsed_s']}s")
    if summary["ok"]:
        print("\nthe repaired tracks changed the corpus — next:\n"
              "  1. uv run python scripts/train_clusters.py\n"
              "  2. uv run python scripts/describe_clusters.py --force\n"
              "  3. uv run .claude/skills/warehouse-audit/audit_warehouse.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
