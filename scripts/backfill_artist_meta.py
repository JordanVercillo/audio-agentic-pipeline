"""
backfill_artist_meta.py — fetch artist metadata for EVERY artist in the corpus.

Why (director review, 2026-07-30): R1 made `/artists` a public 902-artist index
and rendered a link wherever a TRACK carried a `primary_artist_id`. But
`/artist/{id}` resolves through `artist_meta`, which had only 73 rows — so
**826 of 891 links bounced back to /artists** while the page's own caption
asserted they worked. Two components, two rules for "linkable", one claim
(journal #27).

The caption is now derived from what actually resolves, which makes it honest
and the page worse. This makes it honest AND good: `GET /artists?ids=` batched
50 at a time, so ~18 calls for the whole corpus. Genres stay sparse — that is
Spotify's own ceiling (journal #9), and the page already says so.

    uv run python scripts/backfill_artist_meta.py
    uv run python scripts/backfill_artist_meta.py --limit 100
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill artist_meta for the corpus.")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--force", action="store_true",
                    help="refetch artists we already have")
    args = ap.parse_args()

    cache = FeatureCache()
    have = set(cache.all_artist_meta())
    wanted = {r["primary_artist_id"] for r in cache.library_rows()
              if r.get("primary_artist_id")}
    todo = sorted(wanted if args.force else (wanted - have))
    if args.limit:
        todo = todo[:args.limit]

    print(f"corpus artists: {len(wanted)} · already stored: {len(have)} · "
          f"to fetch: {len(todo)}")
    if not todo:
        print("nothing to do.")
        return 0

    sp = get_user_spotify()
    stored = failed = 0
    for i in range(0, len(todo), 50):          # API maximum is 50 ids per request
        batch = todo[i:i + 50]
        res, err = safe_api_call(sp.artists, batch,
                                 label=f"GET /artists?ids=… ({len(batch)})")
        if res is None:
            failed += len(batch)
            print(f"  batch failed: {err}")
            continue
        items = []
        for a in res.get("artists", []):
            if not a:
                continue                        # absent-safe
            items.append({
                "artist_id": a.get("id"),
                "artist_name": a.get("name"),
                "genres": ", ".join(a.get("genres") or []),
                "popularity": a.get("popularity"),
                "followers": (a.get("followers") or {}).get("total"),
                "image_url": (a.get("images") or [{}])[0].get("url"),
            })
        if items:
            cache.remember_artists(items)       # preserve-if-absent
            stored += len(items)
        print(f"  batch {i // 50 + 1}: {len(items)} artist(s)")

    after = cache.all_artist_meta()
    with_genres = sum(1 for a in after.values() if a.get("genres"))
    print(f"\nartist_meta: {len(have)} -> {len(after)} rows "
          f"({with_genres} with genres — Spotify's own sparse ceiling, journal #9)")
    if failed:
        print(f"failed: {failed} (re-run to retry)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
