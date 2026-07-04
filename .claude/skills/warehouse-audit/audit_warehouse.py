# /// script
# requires-python = ">=3.10"
# dependencies = ["pandas>=2.0", "pyarrow>=14.0"]
# ///
"""Medallion warehouse data-quality audit for the audio-agentic-pipeline.

Deterministic checks over data/warehouse/{staging,cleansed,modeled} + raw audio:
  - layer/table presence and row counts
  - bridge-key (`spotify_track_id`) presence, nulls, duplicate semantics
  - fact <-> dimension join coverage (orphan detection)
  - DSP feature-column count vs the 77-dim contract
  - raw_audio/*.mp3 <-> metadata orphans (both directions)

Prints one JSON report to stdout. Exit 0 even with findings (the report is
the result); exit 1 only if the audit itself cannot run.

Run from the repo root:  uv run .claude/skills/warehouse-audit/audit_warehouse.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
WAREHOUSE = REPO / "data" / "warehouse"
RAW_AUDIO = REPO / "data" / "raw_audio"
LAYERS = ("staging", "cleansed", "modeled")
BRIDGE = "spotify_track_id"
EXPECTED_FEATURE_COLS = 77  # CLAUDE_INSTRUCTIONS.md — the DSP contract

# Non-feature columns that may appear in feature/fact tables: identifiers,
# tonal class labels, and numeric track METADATA (duration_ms/rank/explicit
# come from Spotify, not DSP — they must not count toward the 77-dim contract).
META_COLS = {BRIDGE, "time_range", "track_name", "artist_names", "fetched_at",
             "estimated_key", "estimated_mode",
             "duration_ms", "rank", "explicit"}


def table_summary(path: Path):
    df = pd.read_parquet(path)
    return df, {"rows": int(len(df)), "cols": int(df.shape[1])}


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    layers: dict[str, dict] = {}
    tables: dict[str, pd.DataFrame] = {}  # "layer/name" -> df

    if not WAREHOUSE.is_dir() or not any(WAREHOUSE.rglob("*.parquet")):
        print(json.dumps({
            "layers": {}, "audio": {"mp3_count": len(list(RAW_AUDIO.glob("*.mp3"))) if RAW_AUDIO.is_dir() else 0},
            "errors": [], "warnings": ["data/warehouse/ has no parquet tables"],
            "flags": {"NO_WAREHOUSE": True},
        }, indent=2))
        return 0

    # --- inventory + per-table checks -------------------------------------
    missing_layer = False
    empty_table = False
    missing_bridge = False
    key_nulls = False
    dup_keys = False
    feature_drift = False

    for layer in LAYERS:
        ldir = WAREHOUSE / layer
        files = sorted(ldir.glob("*.parquet")) if ldir.is_dir() else []
        layers[layer] = {"tables": {}}
        if not files:
            warnings.append(f"layer '{layer}' has no tables")
            missing_layer = True
            continue
        for f in files:
            try:
                df, summ = table_summary(f)
            except Exception as e:  # unreadable parquet is a hard finding
                errors.append(f"{layer}/{f.name}: unreadable parquet: {e}")
                continue
            tables[f"{layer}/{f.stem}"] = df
            layers[layer]["tables"][f.stem] = summ

            if summ["rows"] == 0:
                warnings.append(f"{layer}/{f.name}: 0 rows")
                empty_table = True
                continue

            name = f.stem.lower()
            if "artist" in name and BRIDGE not in df.columns:
                pass  # artist tables key on artist ids — bridge not expected
            elif "time_range" in name and BRIDGE not in df.columns:
                pass  # dim_time_range keys on time_range
            elif "description" in name and BRIDGE not in df.columns:
                pass  # column_descriptions is reference metadata, keyed on column names
            elif BRIDGE not in df.columns:
                warnings.append(f"{layer}/{f.name}: no '{BRIDGE}' column")
                missing_bridge = True
            else:
                n_null = int(df[BRIDGE].isna().sum())
                if n_null:
                    errors.append(f"{layer}/{f.name}: {n_null} null {BRIDGE}")
                    key_nulls = True
                # uniqueness semantics: composite with time_range when present,
                # plain unique for dims/features
                key = [BRIDGE, "time_range"] if "time_range" in df.columns else [BRIDGE]
                n_dup = int(df.duplicated(subset=key).sum())
                if n_dup:
                    errors.append(f"{layer}/{f.name}: {n_dup} duplicate rows on {key}")
                    dup_keys = True

            # feature contract: tables that look like feature/fact tables
            if "feature" in name or name.startswith("fact"):
                n_feat = int(sum(
                    pd.api.types.is_numeric_dtype(df[c]) and c not in META_COLS
                    for c in df.columns
                ))
                layers[layer]["tables"][f.stem]["numeric_feature_cols"] = n_feat
                if n_feat and abs(n_feat - EXPECTED_FEATURE_COLS) > 7:
                    warnings.append(
                        f"{layer}/{f.name}: {n_feat} numeric feature cols "
                        f"(contract ~{EXPECTED_FEATURE_COLS}) — FEATURE_DRIFT"
                    )
                    feature_drift = True

    # --- fact <-> dim join coverage ----------------------------------------
    join_orphans = False
    fact = next((df for k, df in tables.items()
                 if k.startswith("modeled/") and "fact" in k.lower()), None)
    dim_tracks = next((df for k, df in tables.items()
                       if k.startswith("modeled/") and "dim" in k.lower()
                       and "track" in k.lower()), None)
    if fact is not None and dim_tracks is not None and BRIDGE in fact.columns \
            and BRIDGE in dim_tracks.columns:
        orphans = set(fact[BRIDGE].dropna()) - set(dim_tracks[BRIDGE].dropna())
        if orphans:
            errors.append(
                f"modeled: {len(orphans)} fact rows with no dim_tracks match "
                f"(e.g. {sorted(orphans)[:3]})"
            )
            join_orphans = True

    # --- audio <-> metadata orphans -----------------------------------------
    audio_orphans = False
    mp3_ids = {p.stem for p in RAW_AUDIO.glob("*.mp3")} if RAW_AUDIO.is_dir() else set()
    meta_ids: set[str] = set()
    for k, df in tables.items():
        if "track" in k.lower() and BRIDGE in df.columns:
            meta_ids |= set(df[BRIDGE].dropna().astype(str))
    audio = {"mp3_count": len(mp3_ids)}
    if mp3_ids and meta_ids:
        unknown_files = mp3_ids - meta_ids
        undownloaded = meta_ids - mp3_ids
        audio["mp3_not_in_metadata"] = len(unknown_files)
        audio["metadata_without_mp3"] = len(undownloaded)
        if unknown_files:
            warnings.append(f"{len(unknown_files)} mp3 files with no metadata row")
            audio_orphans = True
        if undownloaded:
            warnings.append(f"{len(undownloaded)} tracks not yet downloaded (soft)")

    flags = {
        "NO_WAREHOUSE": False,
        "MISSING_LAYER": missing_layer,
        "EMPTY_TABLE": empty_table,
        "MISSING_BRIDGE_KEY": missing_bridge,
        "BRIDGE_KEY_NULLS": key_nulls,
        "DUPLICATE_KEYS": dup_keys,
        "JOIN_ORPHANS": join_orphans,
        "AUDIO_ORPHANS": audio_orphans,
        "FEATURE_DRIFT": feature_drift,
    }
    print(json.dumps({"layers": layers, "audio": audio, "errors": errors,
                      "warnings": warnings, "flags": flags}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
