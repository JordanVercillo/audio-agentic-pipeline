"""
backfill_popularity.py — fetch last-seen Spotify popularity for cached tracks
(slice P). Unlike the audio backfills this one DOES call Spotify — GET /tracks
(an allowed endpoint), batched 50 ids/call, so the whole corpus is ~3 calls.

popularity is deprecated-NOT-removed upstream (journal #20): captured as
optional fetched CONTEXT — never an acoustic feature, never an ML input.
Absent-safe: a track the API no longer values simply keeps NULL. Idempotent
(re-running refreshes the last-seen values via remember_meta).

    uv run python scripts/backfill_popularity.py            # tracks missing popularity
    uv run python scripts/backfill_popularity.py --force    # refresh ALL tracks
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
from src.ingestion.guardrails import safe_api_call, throttle  # noqa: E402
from src.store.cache import FeatureCache  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill Spotify popularity (fetched context).")
    parser.add_argument("--force", action="store_true",
                        help="refresh even for tracks that already have a value")
    args = parser.parse_args()

    cache = FeatureCache()
    all_ids = sorted(cache.all_meta())
    have = cache.all_popularity()
    ids = all_ids if args.force else [t for t in all_ids if t not in have]
    if not ids:
        print(f"nothing to do — {len(have)}/{len(all_ids)} tracks already have popularity.")
        return 0

    sp = get_user_spotify()
    done = absent = failed = 0
    for i in range(0, len(ids), 50):  # API maximum is 50 ids per request
        batch = ids[i:i + 50]
        results, err = safe_api_call(sp.tracks, batch,
                                     label=f"GET /tracks?ids=… (batch of {len(batch)})")
        if results is None:
            failed += len(batch)
            print(f"  batch failed: {err}")
            continue
        items = []
        for tid, track in zip(batch, results.get("tracks", []), strict=True):
            pop = (track or {}).get("popularity")
            if pop is None:
                absent += 1  # removed upstream for this track — keep NULL, honest
                continue
            items.append({"spotify_track_id": tid, "popularity": pop})
        cache.remember_meta(items)  # preserve-if-absent: names/albums untouched
        done += len(items)
        throttle(0.2)

    print(f"popularity backfill: {done} updated, {absent} absent upstream, "
          f"{failed} failed — corpus baseline now {len(cache.all_popularity())} "
          f"of {len(all_ids)} tracks — db: {cache.engine.url}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
