"""
repair_missing_meta.py — restore metadata for playlist members we recorded as
ids but never named, and re-open the jobs that died for want of it
(owner report 2026-07-28).

THE DAMAGE. Playlist membership records every id an import pages over, but
`remember_meta` only saw the tracks that click actually queued. So a track
beyond the cap got a membership row with NO name. The backlog pass then
enqueued it, the acquisition path had nothing to search for, and it burned three
attempts and dead-lettered as "no track metadata for the audio search" — 214
tracks, ~200 of them in one playlist.

Both halves are fixed in the app (every paged record is stored, and nothing
unsearchable is ever enqueued), but the tracks already lost need repairing:
their names must be fetched and their dead-letters re-opened.

CHEAP BY DESIGN: metadata comes from GET /tracks?ids= in batches of 50, so a
268-track playlist costs 6 API calls rather than re-walking 21 pages.

    uv run python scripts/repair_missing_meta.py            # DRY RUN (default)
    uv run python scripts/repair_missing_meta.py --execute  # fetch + reopen

Only tracks that are BOTH unnamed and a recorded playlist member are touched;
a job that failed for any other reason keeps its error and its attempt count.
"""

import argparse
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

from sqlalchemy import select  # noqa: E402

from src.store.cache import JOB_FAILED, JOB_QUEUED, FeatureCache  # noqa: E402
from src.store.models import ExtractionJob  # noqa: E402

_BATCH = 50          # GET /tracks?ids= caps at 50


def unnamed_members(cache: FeatureCache) -> list[str]:
    """Recorded playlist members with no stored track_name."""
    members = {t for ids in cache.playlist_track_ids().values() for t in ids}
    if not members:
        return []
    return sorted(members - cache.searchable_ids(sorted(members)))


def _reopen(cache: FeatureCache, ids: list[str]) -> list[str]:
    """Re-queue jobs that died for want of metadata. Attempts RESET here — and
    only here — because the three failures were ours, not the track's: it was
    never actually searched for."""
    if not ids:
        return []
    out = []
    with cache._Session() as s:
        for job in s.execute(select(ExtractionJob).where(
                ExtractionJob.spotify_track_id.in_(ids),
                ExtractionJob.status == JOB_FAILED)).scalars().all():
            if "no track metadata" not in (job.last_error or ""):
                continue          # a real failure keeps its error and attempts
            job.status = JOB_QUEUED
            job.attempts = 0
            job.last_error = ""
            out.append(job.spotify_track_id)
        s.commit()
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true",
                        help="actually fetch metadata and re-open jobs")
    args = parser.parse_args()

    cache = FeatureCache()
    ids = unnamed_members(cache)
    dead = cache.dead_lettered_ids()
    print(f"{len(ids)} recorded playlist member(s) have no name")
    print(f"   of those, {len(set(ids) & dead)} are dead-lettered")
    print(f"   API cost to repair: {-(-len(ids) // _BATCH)} batched /tracks call(s)")

    if not ids:
        print("\nnothing to repair.")
        return 0
    if not args.execute:
        print("\nDRY RUN — nothing changed. Re-run with --execute.")
        return 0

    from src.ingestion import fetch_batch_metadata
    from src.ingestion.auth import get_user_spotify

    sp = get_user_spotify()
    named = 0
    for i in range(0, len(ids), _BATCH):
        chunk = ids[i:i + _BATCH]
        try:
            df = fetch_batch_metadata(chunk, sp=sp)
        except Exception as exc:  # noqa: BLE001 — a bad batch must not kill the rest
            print(f"   batch {i // _BATCH + 1} failed ({exc}) — continuing")
            continue
        recs = [] if df is None or df.empty else [
            r for r in df.to_dict("records")
            if isinstance(r.get("spotify_track_id"), str) and r.get("track_name")]
        if recs:
            cache.remember_meta(recs)
            named += len(recs)
        print(f"   batch {i // _BATCH + 1}: named {len(recs)} of {len(chunk)}")

    still = set(unnamed_members(cache))
    reopened = _reopen(cache, [t for t in ids if t not in still])
    print(f"\nnamed {named} track(s); re-opened {len(reopened)} dead-lettered job(s)")
    print(f"{len(still)} still unnamed (Spotify returned nothing — likely removed "
          f"or region-locked)")
    print("NEXT: the worker picks the re-opened ones up on its next poll.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
