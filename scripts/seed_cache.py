"""
seed_cache.py — warm the feature cache from the owner warehouse (APP_SPEC Epic A).

Loads the owner's already-extracted 77-dim features
(data/warehouse/modeled/fact_listening_features.parquet) into the shared cache,
plus track metadata, so the pilot demo shows analyzed songs immediately and
popular tracks are pre-warmed for the first real visitors. Idempotent (upsert).

    uv run python scripts/seed_cache.py
"""

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

import pandas as pd  # noqa: E402

from src.store.cache import FeatureCache  # noqa: E402

_MODELED = _ROOT / "data" / "warehouse" / "modeled"


def _clean(v):
    if pd.isna(v):
        return None
    return v.item() if hasattr(v, "item") else v  # numpy scalar → python


def main() -> int:
    fact_path = _MODELED / "fact_listening_features.parquet"
    if not fact_path.exists():
        print(f"No warehouse at {fact_path} — run scripts/run_pipeline.py first.")
        return 1

    fact = pd.read_parquet(fact_path)
    distinct = fact.drop_duplicates(subset="spotify_track_id")
    feature_cols = [c for c in fact.columns
                    if c not in ("spotify_track_id", "time_range", "rank")]

    cache = FeatureCache()
    meta: list[dict] = []
    for _, row in distinct.iterrows():
        tid = row["spotify_track_id"]
        features = {c: _clean(row[c]) for c in feature_cols}
        cache.upsert(tid, features, source="owner-warehouse", dsp_version="77dim-v1")
        meta.append({
            "spotify_track_id": tid,
            "track_name": _clean(row.get("track_name")),
            "artist_names": _clean(row.get("artist_names") or row.get("primary_artist_name")),
        })
    cache.remember_meta(meta)
    print(f"Seeded {len(distinct)} tracks into the feature cache "
          f"(db: {cache.engine.url}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
