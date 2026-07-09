"""
seed_cache.py — warm the feature cache from the owner warehouse (APP_SPEC Epic A).

Loads the owner's already-extracted 77-dim features
(data/warehouse/modeled/fact_listening_features.parquet) into the shared cache,
plus track metadata, so the pilot demo shows analyzed songs immediately and
popular tracks are pre-warmed for the first real visitors. Idempotent (upsert).

    uv run python scripts/seed_cache.py
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

import pandas as pd  # noqa: E402

from src.store.cache import FeatureCache  # noqa: E402

_MODELED = _ROOT / "data" / "warehouse" / "modeled"
_RAW_AUDIO = _ROOT / "data" / "raw_audio"
_SPECTROGRAM_DIR = _ROOT / "data" / "spectrograms"


def _make_spectrogram(track_id: str) -> str | None:
    """Render a spectrogram from an existing owner MP3, if present (reuses the worker)."""
    mp3 = _RAW_AUDIO / f"{track_id}.mp3"
    if not mp3.exists():
        return None
    try:
        from src.dsp.audio_loader import load_audio
        from src.store.extractor import make_mel_spectrogram
        return str(make_mel_spectrogram(load_audio(mp3), _SPECTROGRAM_DIR / f"{track_id}.png"))
    except Exception:  # noqa: BLE001
        return None


def _clean(v):
    if pd.isna(v):
        return None
    return v.item() if hasattr(v, "item") else v  # numpy scalar → python


def main() -> int:
    parser = argparse.ArgumentParser(description="Warm the feature cache from the warehouse.")
    parser.add_argument("--spectrograms", action="store_true",
                        help="also render spectrograms from existing data/raw_audio MP3s")
    args = parser.parse_args()

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
    n_spec = n_seeded = n_ghost = 0
    for _, row in distinct.iterrows():
        tid = row["spotify_track_id"]
        features = {c: _clean(row[c]) for c in feature_cols}
        # Meta is kept for every track (the worker can search for it later),
        # but a metadata-only warehouse row (never-downloaded track) must NOT
        # seed features: the cache would report it "analyzed, forever empty"
        # and the queue could never repair it (journal #13's ghost).
        meta.append({
            "spotify_track_id": tid,
            "track_name": _clean(row.get("track_name")),
            "artist_names": _clean(row.get("artist_names") or row.get("primary_artist_name")),
        })
        if features.get("tempo_bpm") is None:  # the DSP never ran on this row
            n_ghost += 1
            continue
        spec_uri = _make_spectrogram(tid) if args.spectrograms else None
        n_spec += 1 if spec_uri else 0
        cache.upsert(tid, features, spectrogram_uri=spec_uri,
                     source="owner-warehouse", dsp_version="77dim-v1")
        n_seeded += 1
    cache.remember_meta(meta)
    ghost_note = f", {n_ghost} metadata-only skipped" if n_ghost else ""
    print(f"Seeded {n_seeded} tracks into the feature cache "
          f"({n_spec} spectrograms{ghost_note}) — db: {cache.engine.url}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
