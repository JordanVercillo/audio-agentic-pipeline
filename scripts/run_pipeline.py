"""
run_pipeline.py — Full 8-Step Pipeline Orchestrator
====================================================
Drives the complete medallion build from the Spotify API to the Gold star
schema and the insight artifacts:

    | Step | Function                  | What it does                                    |
    |------|---------------------------|-------------------------------------------------|
    | 1    | step_1_fetch_metadata()   | Fetch top tracks + artists (3 time ranges, PKCE)|
    | 2    | step_2_stage_metadata()   | Land raw metadata into Staging Parquet          |
    | 3    | step_3_download_audio()   | Download MP3s from YouTube (idempotent)         |
    | 4    | step_4_extract_features() | Extract 77D features from MP3s (idempotent)     |
    | 5    | step_5_stage_features()   | Verify features landed in Staging (Bronze)      |
    | 6    | step_6_build_cleansed()   | Validate, type-cast, deduplicate (Silver)       |
    | 7    | step_7_build_modeled()    | Build star schema — fact + dimensions (Gold)    |
    | 8    | step_8_build_insights()   | insights.json + INSIGHTS.md (SPEC P2)           |

Usage:
    python scripts/run_pipeline.py                              # full run
    python scripts/run_pipeline.py --skip-download --skip-extract  # metadata-only smoke
    python scripts/run_pipeline.py --limit 5                    # small run (5 tracks/range)
    python scripts/run_pipeline.py --clean                      # clear warehouse only

Notes:
    - Reruns are idempotent: existing MP3s and already-extracted features are
      skipped (file cache + cleansed-Parquet cache). Staging accumulates
      snapshots; the Cleansed layer deduplicates across them.
    - First run opens a browser for Spotify PKCE login (no client secret
      needed). Credentials come from env vars / .env — never from code.
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Paths / imports ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

WAREHOUSE_DIR = PROJECT_ROOT / "data" / "warehouse"
STAGING_DIR = WAREHOUSE_DIR / "staging"
CLEANSED_DIR = WAREHOUSE_DIR / "cleansed"
MODELED_DIR = WAREHOUSE_DIR / "modeled"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)


def clean_warehouse() -> None:
    """Remove all Parquet files from the three warehouse layers (not raw audio)."""
    print("\n🧹 Cleaning warehouse...")
    total = 0
    for layer_dir in [STAGING_DIR, CLEANSED_DIR, MODELED_DIR]:
        if layer_dir.exists():
            files = list(layer_dir.glob("*.parquet"))
            for f in files:
                f.unlink()
                total += 1
            print(f"   {layer_dir.name:10s} → removed {len(files)} file(s)")
        else:
            layer_dir.mkdir(parents=True, exist_ok=True)
            print(f"   {layer_dir.name:10s} → created (empty)")
    print(f"   Total: {total} file(s) removed")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  THE 7 STEPS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def step_1_fetch_metadata(limit: int):
    """Fetch top tracks + artists across all 3 time ranges via PKCE auth."""
    print("\n" + "=" * 60)
    print("  STEP 1/8 — Fetch Spotify metadata (PKCE)")
    print("=" * 60)

    from src.ingestion.auth import get_user_spotify
    from src.ingestion.fetchers import (
        fetch_top_tracks, fetch_top_artists, fetch_artists_by_ids,
    )
    from src.ingestion.guardrails import throttle

    import pandas as pd

    print("🔐 Authenticating with Spotify (opens browser on first run)...")
    sp = get_user_spotify()
    me = sp.me()
    print(f"   ✅ Authenticated as: {me.get('display_name', 'Unknown')} ({me['id']})")

    all_tracks, all_artists = [], []
    for tr in ["short_term", "medium_term", "long_term"]:
        tracks_df = fetch_top_tracks(time_range=tr, limit=limit, sp=sp)
        artists_df = fetch_top_artists(time_range=tr, limit=limit, sp=sp)
        throttle(0.2)
        if not tracks_df.empty:
            all_tracks.append(tracks_df)
        if not artists_df.empty:
            all_artists.append(artists_df)

    tracks = pd.concat(all_tracks, ignore_index=True) if all_tracks else pd.DataFrame()
    artists = pd.concat(all_artists, ignore_index=True) if all_artists else pd.DataFrame()

    if tracks.empty:
        print("❌ No tracks returned from the Spotify API. Is this account "
              "registered in the app's Developer Dashboard?")
        sys.exit(1)

    # Genre-coverage backfill: top tracks are made by artists who aren't
    # always in the top-artists list — batch-fetch the missing ones so
    # dim_artists carries genres for every primary artist.
    have = set(artists["artist_id"]) if not artists.empty else set()
    missing = [a for a in tracks["primary_artist_id"].dropna().unique() if a not in have]
    if missing:
        print(f"   🔎 {len(missing)} primary artists not in top-artists — backfilling genres")
        backfill = fetch_artists_by_ids(missing, sp=sp)
        if not backfill.empty:
            artists = pd.concat([artists, backfill], ignore_index=True)

    print(f"\n   📊 Fetched {len(tracks)} track entries "
          f"({tracks['spotify_track_id'].nunique()} unique), "
          f"{len(artists)} artist entries")
    return tracks, artists


def step_2_stage_metadata(tracks_df, artists_df, snapshot_label: str) -> None:
    """Land raw metadata into the Staging (Bronze) layer with lineage."""
    print("\n" + "=" * 60)
    print("  STEP 2/8 — Land metadata in Staging (Bronze)")
    print("=" * 60)

    from src.warehouse.staging import land_staging_tracks, land_staging_artists

    land_staging_tracks(tracks_df, output_dir=STAGING_DIR, snapshot_label=snapshot_label)
    if not artists_df.empty:
        land_staging_artists(artists_df, output_dir=STAGING_DIR, snapshot_label=snapshot_label)


def step_3_download_audio(tracks_df, skip: bool):
    """Download MP3 audio for every fetched track (idempotent, rate-limited)."""
    print("\n" + "=" * 60)
    print("  STEP 3/8 — Download audio (YouTube → MP3)")
    print("=" * 60)

    if skip:
        print("   ⏭️  SKIPPED (--skip-download) — using cached MP3s if present")
        return None

    from src.ingestion.audio_downloader import download_audio_for_tracks

    unique = tracks_df.drop_duplicates(subset=["spotify_track_id"]).reset_index(drop=True)
    print(f"   🎯 {len(unique)} unique tracks to acquire")
    summary = download_audio_for_tracks(unique)

    if not summary.empty:
        counts = summary["download_status"].value_counts().to_dict()
        print(f"   📊 Download summary: {counts}")
    return summary


def step_4_extract_features(tracks_df, skip: bool):
    """Extract 77-dim DSP features from downloaded MP3s (idempotent)."""
    print("\n" + "=" * 60)
    print("  STEP 4/8 — Extract DSP features (77-dim)")
    print("=" * 60)

    if skip:
        print("   ⏭️  SKIPPED (--skip-extract) — using cached features if present")
        return None

    from src.dsp.collection_extractor import extract_features_for_collection

    # Landing to Staging + Cleansed happens inside the collection extractor
    # (its documented contract) — step 5 verifies the result.
    features_df = extract_features_for_collection(tracks_df=tracks_df)
    print(f"   📊 Newly extracted feature rows: {len(features_df)}")
    return features_df


def step_5_stage_features() -> None:
    """Verify DSP features landed in Staging (landing runs inside step 4)."""
    print("\n" + "=" * 60)
    print("  STEP 5/8 — Verify features in Staging (Bronze)")
    print("=" * 60)

    from src.warehouse.staging import list_staging_files

    inventory = list_staging_files(STAGING_DIR)
    if inventory.empty:
        print("   ⚠️  Staging layer is empty")
        return
    feature_files = inventory[inventory["file_name"].str.startswith("features_raw")] \
        if "file_name" in inventory.columns else inventory
    print(f"   📋 Staging inventory ({len(inventory)} file(s) total):")
    print("   " + inventory.to_string(index=False).replace("\n", "\n   "))
    if feature_files.empty:
        print("   ⚠️  No feature files staged yet (expected on --skip-extract runs)")


def step_6_build_cleansed() -> None:
    """Rebuild the Cleansed (Silver) layer: dedup, type enforcement, nulls."""
    print("\n" + "=" * 60)
    print("  STEP 6/8 — Build Cleansed layer (Silver)")
    print("=" * 60)

    from src.warehouse.cleansed import (
        build_cleansed_tracks, build_cleansed_features, build_cleansed_artists,
    )

    build_cleansed_tracks(staging_dir=STAGING_DIR, output_dir=CLEANSED_DIR)
    print()
    build_cleansed_artists(staging_dir=STAGING_DIR, output_dir=CLEANSED_DIR)
    print()
    build_cleansed_features(staging_dir=STAGING_DIR, output_dir=CLEANSED_DIR)


def step_7_build_modeled() -> None:
    """Build the Gold star schema: fact + dimensions + agent column descriptions."""
    print("\n" + "=" * 60)
    print("  STEP 7/8 — Build star schema (Gold)")
    print("=" * 60)

    from src.warehouse.modeled import build_star_schema

    build_star_schema(cleansed_dir=CLEANSED_DIR, output_dir=MODELED_DIR)


def step_8_build_insights() -> None:
    """Generate insights.json + INSIGHTS.md from the gold layer (SPEC P2)."""
    print("\n" + "=" * 60)
    print("  STEP 8/8 — Build insights (artifacts)")
    print("=" * 60)

    import pandas as pd

    fact_path = MODELED_DIR / "fact_listening_features.parquet"
    if not fact_path.exists():
        print("   ⏭️  SKIPPED — no fact table yet")
        return
    # Metadata-only warehouses (smoke runs) have no DSP columns — drift math
    # needs them, so skip politely rather than erroring the smoke.
    fact_cols = pd.read_parquet(fact_path, engine="pyarrow").columns
    if "rms_mean" not in fact_cols:
        print("   ⏭️  SKIPPED — fact table has no DSP features yet "
              "(rerun without --skip-extract)")
        return

    from src.analysis.insights import build_and_write_insights

    build_and_write_insights()


def print_warehouse_summary() -> None:
    """Print the final per-layer Parquet inventory."""
    print("\n📊 Warehouse Summary:")
    print("   " + "─" * 50)
    for layer_dir in [STAGING_DIR, CLEANSED_DIR, MODELED_DIR]:
        files = sorted(layer_dir.glob("*.parquet")) if layer_dir.exists() else []
        total_kb = sum(f.stat().st_size for f in files) / 1024
        print(f"\n   {layer_dir.name.upper()} ({len(files)} files, {total_kb:.1f} KB)")
        for f in files:
            print(f"      {f.name:50s} {f.stat().st_size / 1024:7.1f} KB")
    print("\n   " + "─" * 50)


def main() -> None:
    # Ensure emoji/unicode output works on Windows
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Full 7-step pipeline orchestrator")
    parser.add_argument("--clean", action="store_true",
                        help="Clear warehouse Parquet files and exit (keeps raw audio)")
    parser.add_argument("--skip-download", action="store_true",
                        help="Skip YouTube audio download (use cached MP3s)")
    parser.add_argument("--skip-extract", action="store_true",
                        help="Skip DSP feature extraction (use cached features)")
    parser.add_argument("--limit", type=int, default=50, metavar="N",
                        help="Top tracks/artists per time range (1-50, default 50)")
    args = parser.parse_args()

    print("=" * 60)
    print("  🎧 Temporal Audio Pipeline — 8-step orchestrator")
    print("=" * 60)

    if args.clean:
        clean_warehouse()
        print("\n   Done (clean only).")
        return

    start = time.time()
    snapshot_label = f"run_{datetime.now():%Y%m%d_%H%M%S}"
    print(f"   Snapshot label: {snapshot_label}")
    print(f"   Flags: limit={args.limit}, skip_download={args.skip_download}, "
          f"skip_extract={args.skip_extract}")

    tracks_df, artists_df = step_1_fetch_metadata(limit=args.limit)
    step_2_stage_metadata(tracks_df, artists_df, snapshot_label)
    step_3_download_audio(tracks_df, skip=args.skip_download)
    step_4_extract_features(tracks_df, skip=args.skip_extract)
    step_5_stage_features()
    step_6_build_cleansed()
    step_7_build_modeled()
    step_8_build_insights()

    print_warehouse_summary()
    print(f"   ✅ Pipeline complete in {time.time() - start:.1f}s\n")


if __name__ == "__main__":
    main()
