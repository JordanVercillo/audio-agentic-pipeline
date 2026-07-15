"""seed_artist_meta.py — one-time seed of the artist_meta cache table (P3.1/D-36).

Copies the warehouse's enriched artist rows (dim_artists: genres/followers/
images, built by the pipeline's /artists backfill) into the serving cache, so
the /artists surfaces have genre data BEFORE each user's next login tops it up.
Idempotent (remember_artists upserts, preserve-if-absent); dim_artists is a
seed, not a serving path — after this, dashboard logins keep artist_meta fresh.

    uv run python scripts/seed_artist_meta.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.store.cache import FeatureCache  # noqa: E402

_DIM = Path(__file__).resolve().parent.parent / "data" / "warehouse" / "modeled" / "dim_artists.parquet"


def main() -> int:
    if not _DIM.exists():
        print(f"no dim_artists at {_DIM} — run the pipeline first", file=sys.stderr)
        return 1
    df = pd.read_parquet(_DIM)
    items = [{k: (None if pd.isna(v) else v) for k, v in row.items()}
             for row in df.to_dict("records")]
    cache = FeatureCache()
    cache.remember_artists(items)
    stored = cache.all_artist_meta()
    with_genres = sum(1 for a in stored.values() if a["genres"])
    print(f"seeded artist_meta: {len(stored)} artists stored "
          f"({with_genres} with genres — the honest coverage ceiling, journal #9)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
