"""
build_feature_marts.py — build the analytic feature marts (VISION_SPECS Epic F).

    uv run python scripts/build_feature_marts.py

F1 scope: the perceptual-v1 transform over every cached track → the cache's
track_perceptual table + Parquet marts under data/marts/:
    track_perceptual.parquet   bridge key + every catalog feature + version
    feature_catalog.parquet    the feature picker's source (name, tier, unit, docs)

Idempotent — rerun as the cache grows; percentile-calibrated columns are
recomputed against the current population (that's why `version` travels on
every row). F2 adds feature_stats (distribution mart) here.
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

from src.store.cache import FeatureCache  # noqa: E402
from src.store.perceptual import PERCEPTUAL_VERSION, rebuild_marts  # noqa: E402

_MARTS = _ROOT / "data" / "marts"

if __name__ == "__main__":
    cache = FeatureCache()
    result = rebuild_marts(cache, _MARTS)
    if result["n_tracks"] == 0:
        print("no complete cached tracks — seed or extract first")
        sys.exit(1)
    df, catalog, stats = result["perceptual"], result["catalog"], result["stats"]

    print(f"{PERCEPTUAL_VERSION}: {result['n_tracks']} tracks transformed "
          f"({len(catalog)} catalog features: "
          f"{(catalog['tier'] == 'measured').sum()} measured, "
          f"{(catalog['tier'] == 'derived').sum()} derived, "
          f"{(catalog['tier'] == 'experimental').sum()} experimental); "
          f"feature_stats: {len(stats)} rows")
    meta = cache.all_meta()
    sample = df.nlargest(3, "danceability")[
        ["spotify_track_id", "tempo", "loudness_db", "energy", "danceability"]]
    print("\nmost danceable in the cache:")
    for _, r in sample.iterrows():
        name = (meta.get(r["spotify_track_id"]) or {}).get("track_name", r["spotify_track_id"])
        print(f"  {name[:34]:34s} tempo={r['tempo']:.0f}bpm "
              f"loud={r['loudness_db']}dB energy={r['energy']:.2f} "
              f"dance={r['danceability']:.2f}")
