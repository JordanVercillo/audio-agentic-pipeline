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

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
WAREHOUSE = REPO / "data" / "warehouse"
RAW_AUDIO = REPO / "data" / "raw_audio"
MARTS = REPO / "data" / "marts"
LAYERS = ("staging", "cleansed", "modeled")
BRIDGE = "spotify_track_id"

# The feature_stats mart's required schema (VISION_SPECS F2).
STATS_REQUIRED = {"column", "tier", "n", "mean", "std", "min",
                  "p5", "p25", "p50", "p75", "p95", "max",
                  "bin_edges", "bin_counts"}
# Non-feature columns that may appear in feature/fact tables: identifiers,
# tonal class labels, and numeric track METADATA (duration_ms/rank/explicit
# come from Spotify, not DSP — they must not count as DSP features).
META_COLS = {BRIDGE, "time_range", "track_name", "artist_names", "fetched_at",
             "estimated_key", "estimated_mode",
             "duration_ms", "rank", "explicit"}

# Metadata columns that ARE documented in column_descriptions but aren't DSP
# features. Subtracted from the documented set to get the expected feature
# contract (D-4: the gold layer ships its own contract via column_descriptions;
# the audit verifies the feature tables match it EXACTLY — no ± tolerance).
NON_FEATURE_DESCRIBED = {
    BRIDGE, "time_range", "rank", "track_name", "artist_names",
    "primary_artist_name", "album_name", "duration_ms", "explicit",
    "estimated_key", "estimated_mode",
}


def _load_expected_features():
    """Expected DSP feature columns = everything documented in the gold layer's
    column_descriptions minus the known metadata. Returns None when
    column_descriptions is absent (e.g. a pre-modeled run)."""
    path = WAREHOUSE / "modeled" / "column_descriptions.parquet"
    if not path.exists():
        return None
    try:
        return set(pd.read_parquet(path)["column_name"]) - NON_FEATURE_DESCRIBED
    except Exception:
        return None


def table_summary(path: Path):
    df = pd.read_parquet(path)
    return df, {"rows": int(len(df)), "cols": int(df.shape[1])}


def check_marts(marts_dir: Path):
    """Audit the derived feature marts (VISION_SPECS F2) — the D-4 exact-list
    discipline applied to the perceptual layer:

      CATALOG_MART_DRIFT  feature_catalog's columns != track_perceptual's
                          feature columns (exact, both directions)
      STATS_MART_DRIFT    feature_stats' feature set != the catalog's, a
                          required stat column is missing, or a histogram's
                          bin_counts don't sum to its n

    Marts are an optional derived layer: an absent dir is a note, not a
    finding. Returns (report, warnings, errors, flags).
    """
    report: dict = {}
    warnings: list[str] = []
    errors: list[str] = []
    flags = {"CATALOG_MART_DRIFT": False, "STATS_MART_DRIFT": False,
             "FEATURE_DISTRIBUTION": False}

    if not marts_dir.is_dir() or not any(marts_dir.glob("*.parquet")):
        warnings.append("data/marts/ not built (optional — run scripts/build_feature_marts.py)")
        return report, warnings, errors, flags

    frames: dict[str, pd.DataFrame] = {}
    for name in ("feature_catalog", "track_perceptual", "feature_stats"):
        path = marts_dir / f"{name}.parquet"
        if not path.exists():
            warnings.append(f"marts/{name}.parquet missing — MART_INCOMPLETE")
            continue
        try:
            df = pd.read_parquet(path)
        except Exception as e:
            errors.append(f"marts/{name}.parquet: unreadable parquet: {e}")
            continue
        frames[name] = df
        report[name] = {"rows": int(len(df)), "cols": int(df.shape[1])}

    catalog = frames.get("feature_catalog")
    perceptual = frames.get("track_perceptual")
    stats = frames.get("feature_stats")

    if catalog is not None and perceptual is not None:
        cat_cols = set(catalog["column"])
        # population_n is per-row provenance (the calibration population), not a feature.
        mart_cols = set(perceptual.columns) - {BRIDGE, "version", "population_n"}
        missing = sorted(cat_cols - mart_cols)
        extra = sorted(mart_cols - cat_cols)
        if missing or extra:
            parts = []
            if missing:
                parts.append(f"cataloged but absent from the mart: {missing[:4]}")
            if extra:
                parts.append(f"in the mart but uncataloged: {extra[:4]}")
            warnings.append(
                f"marts: catalog<->track_perceptual mismatch — {'; '.join(parts)}"
                " — CATALOG_MART_DRIFT")
            flags["CATALOG_MART_DRIFT"] = True
        if BRIDGE in perceptual.columns:
            n_dup = int(perceptual.duplicated(subset=[BRIDGE]).sum())
            if n_dup:
                errors.append(f"marts/track_perceptual: {n_dup} duplicate {BRIDGE}")
                flags["CATALOG_MART_DRIFT"] = True

    if stats is not None:
        missing_cols = sorted(STATS_REQUIRED - set(stats.columns))
        if missing_cols:
            warnings.append(
                f"marts/feature_stats missing required columns {missing_cols[:6]}"
                " — STATS_MART_DRIFT")
            flags["STATS_MART_DRIFT"] = True
        elif catalog is not None:
            cat_cols = set(catalog["column"])
            stat_cols = set(stats["column"])
            missing = sorted(cat_cols - stat_cols)
            extra = sorted(stat_cols - cat_cols)
            if missing or extra:
                parts = []
                if missing:
                    parts.append(f"no stats for: {missing[:4]}")
                if extra:
                    parts.append(f"stats for uncataloged: {extra[:4]}")
                warnings.append(
                    f"marts: catalog<->feature_stats mismatch — {'; '.join(parts)}"
                    " — STATS_MART_DRIFT")
                flags["STATS_MART_DRIFT"] = True
            bad_bins = [
                str(r["column"]) for _, r in stats.iterrows()
                if int(sum(r["bin_counts"])) != int(r["n"])
            ]
            if bad_bins:
                errors.append(
                    f"marts/feature_stats: bin_counts don't sum to n for {bad_bins[:4]}"
                    " — STATS_MART_DRIFT")
                flags["STATS_MART_DRIFT"] = True

    if stats is not None and not (STATS_REQUIRED - set(stats.columns)):
        dist_warnings = check_distributions(stats)
        if dist_warnings:
            warnings.extend(dist_warnings)
            flags["FEATURE_DISTRIBUTION"] = True

    return report, warnings, errors, flags


# Plausible physical ranges per measured feature (journal #21: validate an
# estimator by its DISTRIBUTION against a domain prior — unit tests prove the
# code does what you wrote; only the corpus shape reveals a wrong definition).
_PLAUSIBLE = {
    "tempo": (30.0, 300.0),          # bpm — beat trackers octave-err beyond this
    "loudness_db": (-80.0, 0.001),   # dBFS can't exceed 0 for normalized audio
    "duration_sec": (10.0, 3600.0),  # a "track" under 10 s / over 1 h is suspect
    "key": (0.0, 11.0),              # pitch classes
    "mode": (0.0, 1.0),
    "time_signature": (2.0, 7.0),    # the estimator only emits 3..7 (+4 default)
}


def check_distributions(stats: pd.DataFrame) -> list[str]:
    """Distribution-sanity warnings over feature_stats (FEATURE_DISTRIBUTION).

    Soft by design: these are "a domain expert would squint" checks, not schema
    violations — bounds per measured feature, 0–1 range for calibrated tiers,
    degenerate (zero-spread) populations, and the journal-#19/#21 prior that 4/4
    must be the modal meter in any sizable corpus.
    """
    out: list[str] = []
    for _, r in stats.iterrows():
        col, n = str(r["column"]), int(r["n"])
        lo, hi = float(r["min"]), float(r["max"])
        if r.get("tier") in ("derived", "experimental") and (lo < 0.0 or hi > 1.0):
            out.append(f"marts/feature_stats: calibrated feature {col} outside 0–1 "
                       f"[{lo}, {hi}] — FEATURE_DISTRIBUTION")
        bounds = _PLAUSIBLE.get(col)
        if bounds and (lo < bounds[0] or hi > bounds[1]):
            out.append(f"marts/feature_stats: {col} range [{lo}, {hi}] outside "
                       f"plausible {list(bounds)} — FEATURE_DISTRIBUTION")
        if n >= 20 and float(r["std"]) == 0.0:
            out.append(f"marts/feature_stats: {col} has zero spread across {n} "
                       f"tracks (broken upstream?) — FEATURE_DISTRIBUTION")
        if col == "time_signature" and n >= 20:
            edges, counts = list(r["bin_edges"]), list(r["bin_counts"])
            four = next((i for i in range(len(counts))
                         if edges[i] <= 4.0 < edges[i + 1]), None)
            if four is not None and counts[four] != max(counts):
                out.append("marts/feature_stats: 4/4 is not the modal meter — "
                           "implausible for a music corpus (journal #19) — "
                           "FEATURE_DISTRIBUTION")
    return out


def _load_dedup():
    """Load the stdlib-only src/store/dedup.py BY PATH (the pattern the tests use
    for verify_app.py) so the audit shares ONE definition of 'duplicate' with the
    serving cache — no `src` import, no extra deps in the uv-isolated audit."""
    path = REPO / "src" / "store" / "dedup.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("dedup", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # @dataclass resolves annotations via sys.modules
    spec.loader.exec_module(mod)
    return mod


def check_duplicates(modeled_dir: Path):
    """DUPLICATE_TRACKS (Epic O / D-28): report clusters of likely near-duplicate
    tracks (same normalized name+artist within a duration window) in dim_tracks.
    Advisory — dupes are a data-quality SIGNAL, not an invariant break, so this is
    a WARNING (zero errors), same severity class as AUDIO_ORPHANS. Metadata-only;
    the acoustic cosine tiebreak lives in the serving layer where vectors exist."""
    report: dict = {}
    warns: list[str] = []
    flags = {"DUPLICATE_TRACKS": False}
    path = modeled_dir / "dim_tracks.parquet"
    dedup = _load_dedup()
    if not path.exists() or dedup is None:
        return report, warns, flags
    df = pd.read_parquet(path)
    if BRIDGE not in df.columns or "track_name" not in df.columns:
        return report, warns, flags
    records = [dedup.DedupRecord(
        track_id=str(r[BRIDGE]), title=r.get("track_name"),
        artist=r.get("artist_names") or r.get("primary_artist_name"),
        duration_ms=(int(r["duration_ms"]) if pd.notna(r.get("duration_ms")) else None))
        for _, r in df.iterrows()]
    clusters = dedup.find_duplicate_clusters(records)
    report["n_clusters"] = len(clusters)
    report["n_duplicate_tracks"] = sum(len(c.duplicate_ids) for c in clusters)
    if clusters:
        names = {str(r[BRIDGE]): str(r.get("track_name")) for _, r in df.iterrows()}
        sample = [f"{names.get(c.canonical_id, c.canonical_id)!r} "
                  f"({len(c.members)} copies)" for c in clusters[:5]]
        warns.append(
            f"dim_tracks: {len(clusters)} near-duplicate cluster(s), "
            f"{report['n_duplicate_tracks']} redundant track(s) — e.g. {sample} "
            "— DUPLICATE_TRACKS")
        flags["DUPLICATE_TRACKS"] = True
    return report, warns, flags


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
    expected_features = _load_expected_features()  # None until the gold layer exists

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

            # feature contract: tables that look like feature/fact tables.
            # EXACT-list verification against the documented contract (D-4):
            # every documented feature must be present, and no undocumented
            # numeric feature may appear.
            if "feature" in name or name.startswith("fact"):
                actual = {c for c in df.columns
                          if pd.api.types.is_numeric_dtype(df[c]) and c not in META_COLS}
                layers[layer]["tables"][f.stem]["numeric_feature_cols"] = len(actual)
                if expected_features is not None and actual:
                    missing = sorted(expected_features - actual)
                    extra = sorted(actual - expected_features)
                    if missing or extra:
                        parts = []
                        if missing:
                            parts.append(f"missing {len(missing)} (e.g. {missing[:4]})")
                        if extra:
                            parts.append(f"undocumented {len(extra)} (e.g. {extra[:4]})")
                        warnings.append(
                            f"{layer}/{f.name}: feature-contract mismatch vs "
                            f"column_descriptions — {'; '.join(parts)} — FEATURE_DRIFT"
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

    # --- derived feature marts (VISION_SPECS F2) ----------------------------
    marts_report, m_warnings, m_errors, m_flags = check_marts(MARTS)
    warnings.extend(m_warnings)
    errors.extend(m_errors)

    # --- near-duplicate tracks (Epic O / D-28) ------------------------------
    dup_report, d_warnings, d_flags = check_duplicates(WAREHOUSE / "modeled")
    warnings.extend(d_warnings)

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
        **m_flags,
        **d_flags,
    }
    print(json.dumps({"layers": layers, "audio": audio, "marts": marts_report,
                      "duplicates": dup_report, "errors": errors,
                      "warnings": warnings, "flags": flags}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
