"""snapshot_demo_profile.py — capture the owner's taste as a public demo profile.

Reads the gold warehouse (the owner's top tracks per time_range) → writes
`data/demo_profile.json`, so the "View as guest" mode (H7) can render his full
analytics with NO live Spotify token. Filtered to tracks currently in the
feature cache (a guest can't trigger extraction, so unanalyzed ids would just
show as gaps). Re-run any time to refresh. Real data only — this is the owner's
own listening history, exposed by explicit choice (D-30).

    uv run python scripts/snapshot_demo_profile.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.store.cache import FeatureCache  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
_FACT = _ROOT / "data" / "warehouse" / "modeled" / "fact_listening_features.parquet"
_OUT = _ROOT / "data" / "demo_profile.json"
_RANGES = ("short_term", "medium_term", "long_term")


def main() -> int:
    if not _FACT.exists():
        print(f"no warehouse fact at {_FACT} — run the pipeline first", file=sys.stderr)
        return 1
    con = duckdb.connect()
    cache = FeatureCache(url="sqlite:///data/feature_cache.db")
    cached = set(cache.all_features())
    dupes = cache.duplicate_flags()  # O3a: the snapshot ships pre-canonical

    from src.store.dedup import canonicalize_ids
    range_ids: dict[str, list[str]] = {}
    for rng in _RANGES:
        rows = con.execute(
            "SELECT spotify_track_id FROM read_parquet(?) WHERE time_range = ? ORDER BY rank",
            [str(_FACT), rng]).fetchall()
        range_ids[rng] = canonicalize_ids(
            [r[0] for r in rows if r[0] in cached], dupes)

    artist_rows = con.execute(
        "SELECT primary_artist_name, count(*) c FROM read_parquet(?) "
        "WHERE primary_artist_name IS NOT NULL GROUP BY 1 ORDER BY c DESC LIMIT 15",
        [str(_FACT)]).fetchall()
    artists = [{"name": a, "genres": ""} for a, _ in artist_rows]

    profile = {"generated_at": datetime.now(timezone.utc).isoformat(),
               "range_ids": range_ids, "artists": artists}
    _OUT.write_text(json.dumps(profile, indent=2))
    total = len({t for ids in range_ids.values() for t in ids})
    print(f"wrote {_OUT.name}: {total} cached tracks ("
          + ", ".join(f"{k}={len(v)}" for k, v in range_ids.items())
          + f"); {len(artists)} artists")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
