"""
backfill_track_identity.py — capture ISRC + album identity for cached tracks (D-70).

`fetchers._track_to_record` has always built `isrc`, `album_id`, `album_type`
and `album_release_date`; `remember_meta` discarded them, so the serving cache
never had them: measured 2026-07-30, isrc was set on 0 of 2,357 meta rows. The
109 ISRCs that exist anywhere live only in the old Parquet staging snapshots
(~150 top-tracks rows, never the playlist imports).

Why it matters twice over:
  * **ISRC is the bridge** into MusicBrainz -> the AcousticBrainz CC0 dump.
    Phase 5's headline coverage number cannot be measured without it — run
    against the cache today it would read 0%.
  * **album_release_date EXPLAINS the misses** (the dump is frozen 2022-06-23,
    so every later release is a guaranteed miss) and unlocks Epic R's album
    chronology.

Same shape as backfill_popularity.py: GET /tracks batched 50 ids/call, so the
whole corpus is ~40 calls. Absent-safe (a track missing a field keeps NULL),
idempotent, and preserve-if-absent at the write.

    uv run python scripts/backfill_track_identity.py           # tracks missing an ISRC
    uv run python scripts/backfill_track_identity.py --force   # refresh ALL tracks
    uv run python scripts/backfill_track_identity.py --limit 100
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

from src.ingestion.auth import get_user_spotify  # noqa: E402
from src.ingestion.guardrails import safe_api_call  # noqa: E402
from src.store.cache import FeatureCache  # noqa: E402

_FIELDS = ("isrc", "album_id", "album_type", "album_release_date")


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill ISRC + album identity (D-70).")
    ap.add_argument("--force", action="store_true",
                    help="refresh even tracks that already have an ISRC")
    ap.add_argument("--limit", type=int, default=None, help="cap tracks processed")
    args = ap.parse_args()

    cache = FeatureCache()
    have = cache.all_track_identity()
    todo = sorted(t for t, v in have.items() if args.force or not v.get("isrc"))
    if args.limit:
        todo = todo[:args.limit]

    covered = sum(1 for v in have.values() if v.get("isrc"))
    print(f"corpus: {len(have)} known tracks · {covered} with an ISRC "
          f"({covered / len(have):.1%})" if have else "corpus: empty")
    if not todo:
        print("nothing to do.")
        return 0
    print(f"fetching {len(todo)} track(s) in {(len(todo) + 49) // 50} batched call(s)…")

    sp = get_user_spotify()
    got = {f: 0 for f in _FIELDS}
    failed = 0
    for i in range(0, len(todo), 50):          # API maximum is 50 ids per request
        batch = todo[i:i + 50]
        results, err = safe_api_call(sp.tracks, batch,
                                     label=f"GET /tracks?ids=… ({len(batch)} ids)")
        if results is None:
            failed += len(batch)
            print(f"  batch failed: {err}")
            continue
        items = []
        for tid, track in zip(batch, results.get("tracks", []), strict=True):
            if not track:
                continue                        # gone from Spotify — absent-safe
            album = track.get("album") or {}
            rec = {"spotify_track_id": tid,
                   "isrc": (track.get("external_ids") or {}).get("isrc"),
                   "album_id": album.get("id"),
                   "album_type": album.get("album_type"),
                   "album_release_date": album.get("release_date")}
            for f in _FIELDS:
                if rec[f]:
                    got[f] += 1
            items.append(rec)
        if items:
            cache.remember_meta(items)          # preserve-if-absent
        print(f"  batch {i // 50 + 1}: {len(items)} track(s) written")

    after = cache.all_track_identity()
    now_covered = sum(1 for v in after.values() if v.get("isrc"))
    print("\ncaptured this run: " + " · ".join(f"{f} {got[f]}" for f in _FIELDS))
    if failed:
        print(f"failed: {failed} track(s) (re-run to retry)")
    print(f"ISRC coverage: {covered} -> {now_covered} of {len(after)} "
          f"({now_covered / len(after):.1%})" if after else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
