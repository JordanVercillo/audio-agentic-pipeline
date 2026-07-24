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

    K2.0 extends the same discipline to the semantic layer (D-49 — the chat's
    analyst views must be provably the same plane the perceptual marts ride):

      PLANE_COHERENCE        track_card's bridge-key set != track_perceptual's
                             (either direction), or duplicate keys in track_card
      SEMANTIC_PARITY        corpus_facts' totals != the marts they summarize
      CLUSTER_PROFILE_DRIFT  cluster_profile's assignment counts/shares are
                             impossible against the corpus (share outside [0,1],
                             n_assigned beyond n_tracks, or an unlabeled row)
      PROVENANCE_ORPHAN      track_provenance (Q1/D-51) carries a bridge key
                             that is NOT an analyzed track — the only real
                             invariant (coverage of OLD tracks is ∅ until the
                             Q3 backfill, so under-coverage is a NOTE, not a
                             flag). O3b: the reference set is track_card ∪ the
                             flagged twins — a track provenanced first and
                             flagged a twin later is analyzed, not an orphan.
      TWIN_LEAKAGE           a flagged duplicate (duplicate_flags mart, O3b)
                             leaked into a canonical-only population —
                             track_perceptual, track_card, or track_provenance

    Marts are an optional derived layer: an absent dir (or an absent semantic
    mart — they land with K2.0 rebuilds) is a note, not a finding.
    Returns (report, warnings, errors, flags).
    """
    report: dict = {}
    warnings: list[str] = []
    errors: list[str] = []
    flags = {"CATALOG_MART_DRIFT": False, "STATS_MART_DRIFT": False,
             "FEATURE_DISTRIBUTION": False, "PLANE_COHERENCE": False,
             "SEMANTIC_PARITY": False, "CLUSTER_PROFILE_DRIFT": False,
             "PROVENANCE_ORPHAN": False, "TWIN_LEAKAGE": False}

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
    # Semantic marts (K2.0) are optional until first rebuilt — absent is silent
    # here (MART_INCOMPLETE would misfire on every pre-K2.0 marts dir).
    for name in ("track_card", "artist_rollup", "corpus_facts", "cluster_profile",
                 "track_provenance", "duplicate_flags"):
        path = marts_dir / f"{name}.parquet"
        if not path.exists():
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
    track_card = frames.get("track_card")
    artist_rollup = frames.get("artist_rollup")
    corpus_facts = frames.get("corpus_facts")
    cluster_profile = frames.get("cluster_profile")
    provenance = frames.get("track_provenance")
    dupe_flags = frames.get("duplicate_flags")
    twin_set: set = (set(dupe_flags["duplicate_id"])
                     if dupe_flags is not None and not dupe_flags.empty else set())

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

    # ── K2.0: the semantic plane ────────────────────────────────────────────
    if track_card is not None and perceptual is not None and BRIDGE in track_card.columns:
        tc_ids = set(track_card[BRIDGE])
        pc_ids = set(perceptual[BRIDGE])
        if tc_ids != pc_ids:
            warnings.append(
                f"marts: track_card<->track_perceptual key sets diverge "
                f"({len(tc_ids - pc_ids)} only in track_card, "
                f"{len(pc_ids - tc_ids)} only in track_perceptual) — PLANE_COHERENCE")
            flags["PLANE_COHERENCE"] = True
        n_dup = int(track_card.duplicated(subset=[BRIDGE]).sum())
        if n_dup:
            errors.append(f"marts/track_card: {n_dup} duplicate {BRIDGE} — PLANE_COHERENCE")
            flags["PLANE_COHERENCE"] = True

    if corpus_facts is not None and not corpus_facts.empty:
        cf = corpus_facts.iloc[0]
        checks = []
        if track_card is not None:
            checks.append(("n_tracks", int(cf.get("n_tracks", -1)), len(track_card)))
            if "feature_valid" in track_card.columns:
                checks.append(("n_feature_valid", int(cf.get("n_feature_valid", -1)),
                               int(track_card["feature_valid"].sum())))
        if artist_rollup is not None:
            checks.append(("n_artists", int(cf.get("n_artists", -1)), len(artist_rollup)))
        for name, claimed, actual in checks:
            if claimed != actual:
                warnings.append(
                    f"marts/corpus_facts.{name} claims {claimed} but the mart it "
                    f"summarizes has {actual} — SEMANTIC_PARITY")
                flags["SEMANTIC_PARITY"] = True

    if cluster_profile is not None and not cluster_profile.empty:
        n_corpus = len(track_card) if track_card is not None else None
        bad: list[str] = []
        if cluster_profile["label"].isna().any() or (cluster_profile["label"] == "").any():
            bad.append("unlabeled cluster row")
        shares = cluster_profile["share_of_corpus"]
        if ((shares < 0) | (shares > 1)).any():
            bad.append("share_of_corpus outside [0,1]")
        if n_corpus is not None and int(cluster_profile["n_assigned"].sum()) > n_corpus:
            bad.append(f"n_assigned sums past the corpus "
                       f"({int(cluster_profile['n_assigned'].sum())} > {n_corpus})")
        if bad:
            warnings.append("marts/cluster_profile: " + "; ".join(bad)
                            + " — CLUSTER_PROFILE_DRIFT")
            flags["CLUSTER_PROFILE_DRIFT"] = True

    # Q1/D-51: provenance is append-only history reduced to current-per-key. The
    # ONLY hard invariant is no orphan (a provenance key must be an analyzed
    # track); coverage of the pre-Q1 corpus is ∅ until the Q3 backfill, so we
    # report under-coverage as a note, never a flag.
    # O3b (red-team #8): flagged twins must be ABSENT from every canonical-only
    # population — presence means the one shared filter drifted somewhere.
    if twin_set:
        for name in ("track_perceptual", "track_card", "track_provenance"):
            frame = frames.get(name)
            if frame is None or frame.empty or BRIDGE not in frame.columns:
                continue
            leaked = twin_set & set(frame[BRIDGE])
            if leaked:
                warnings.append(f"marts/{name}: {len(leaked)} flagged twin(s) "
                                "leaked into a canonical-only mart — TWIN_LEAKAGE")
                flags["TWIN_LEAKAGE"] = True

    if provenance is not None and not provenance.empty and track_card is not None:
        # O3b (red-team #1): twins are analyzed tracks too — a track that got
        # provenance FIRST and its twin flag LATER is no orphan.
        analyzed = set(track_card[BRIDGE]) | twin_set
        prov_keys = set(provenance[BRIDGE])
        orphans = prov_keys - analyzed
        if provenance[BRIDGE].duplicated().any():
            warnings.append("marts/track_provenance: duplicate bridge keys "
                            "(mart must be current-per-key) — PROVENANCE_ORPHAN")
            flags["PROVENANCE_ORPHAN"] = True
        if orphans:
            warnings.append(f"marts/track_provenance: {len(orphans)} provenance "
                            "row(s) for non-analyzed tracks — PROVENANCE_ORPHAN")
            flags["PROVENANCE_ORPHAN"] = True
        # Coverage denominator = CANONICAL analyzed (Q3 red-team #6): dedup
        # twins ride their canonical's audio and are never re-extracted, so
        # counting them makes 100% unreachable and Q4's health metric drift.
        if "duplicate_of" in track_card.columns:
            canonical = set(track_card.loc[track_card["duplicate_of"].isna(), BRIDGE])
        else:
            canonical = set(track_card[BRIDGE])  # card is twin-free post-O3b
        covered = len(prov_keys & canonical)
        report["track_provenance"] = {**report.get("track_provenance", {}),
                                      "coverage": f"{covered}/{len(canonical)} canonical analyzed"}

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
    the acoustic cosine tiebreak lives in the serving layer where vectors exist.

    KNOWN BLIND SPOT — do not read a green flag as "the rule is correct". This
    check runs the shared rule over `dim_tracks`, a population that rule has
    ALREADY filtered, so it reads 0 both when the rule is right and when the rule
    is over-merging: it cannot see a false merge at all. Only the pair-level
    tests in src/store/test_dedup.py can. This flag answers "did a twin leak into
    the catalog", not "is the dedup rule sound"."""
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
        duration_ms=(int(r["duration_ms"]) if pd.notna(r.get("duration_ms")) else None),
        # O4b: dim_tracks already carries the artist id — pass it so the audit
        # keys the artist the same way the serving cache does.
        primary_artist_id=(str(r["primary_artist_id"])
                           if pd.notna(r.get("primary_artist_id")) else None))
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


def check_dedup_disagreement(marts_dir: Path):
    """DEDUP_DISAGREEMENT (O4d): pairs the metadata calls one recording and the
    acoustics refuse — same base title, same version tag, same artist, inside the
    duration window, both analyzed, and yet acoustically distant. At least one of
    the two acquisitions is the wrong audio.

    The COUNT is advisory (a note, never a failure — same class as
    DUPLICATE_TRACKS): a disagreement is a provenance defect for a human to
    repair, not a broken invariant.

    The HARD assertion is MUTUAL EXCLUSIVITY: a pair may be a duplicate OR a
    disagreement, never both. Both marts are produced from ONE cosine_min in
    dedup.py, so a pair appearing in both means the merger and the detector have
    drifted apart — which is exactly the regression that would let a wrong
    acquisition get merged away and stop being visible.

    Deliberately does NOT assert that either id is in track_card: the live case's
    guilty partner is source-unvalidated (B2) and appears in no canonical mart,
    so a membership assertion would false-fire on the very first real run."""
    warns: list[str] = []
    flags = {"DEDUP_DISAGREEMENT": False}
    path = marts_dir / "dedup_disagreements.parquet"
    if not path.exists():
        return {}, warns, flags
    df = pd.read_parquet(path)
    report = {"n_pairs": int(len(df))}
    if df.empty:
        return report, warns, flags

    pairs = {tuple(sorted((str(a), str(b))))
             for a, b in zip(df["track_id_a"], df["track_id_b"])}
    hard: list[str] = []
    if (df["track_id_a"] == df["track_id_b"]).any():
        hard.append("a pair references one id twice")
    if len(pairs) != len(df):
        hard.append("duplicate pair rows (must be one row per unordered pair)")

    dedup = _load_dedup()
    if dedup is not None and (df["z_cosine"] >= dedup.DEFAULT_COSINE_MIN).any():
        hard.append(f"a pair scores >= cosine_min ({dedup.DEFAULT_COSINE_MIN}) — "
                    "the detector and the merger disagree on the threshold")

    fpath = marts_dir / "duplicate_flags.parquet"
    if fpath.exists():
        ff = pd.read_parquet(fpath)
        merged = {tuple(sorted((str(d), str(c))))
                  for d, c in zip(ff["duplicate_id"], ff["canonical_id"])}
        both = pairs & merged
        if both:
            hard.append(f"{len(both)} pair(s) are BOTH merged and disagreeing")

    if hard:
        warns.append("marts\\dedup_disagreements: " + "; ".join(hard)
                     + " — DEDUP_DISAGREEMENT")
        flags["DEDUP_DISAGREEMENT"] = True
    else:
        warns.append(f"marts\\dedup_disagreements: {len(df)} pair(s) where the "
                     "metadata says one recording and the acoustics disagree — at "
                     "least one acquisition per pair wants human eyes (note, not "
                     "a failure)")
    return report, warns, flags


def check_plane_agreement(modeled_dir: Path, marts_dir: Path):
    """GOLD_PLANE_STALE (D-60): the batch gold catalog and the serving marts must
    describe the SAME canonical corpus.

    `dim_tracks` (materialized from the cache by `export_gold_from_cache.py`) and
    `track_card` (the serving analyst mart) are each the current canonical,
    twin-free, source-validated population. If their bridge-key sets diverge, the
    gold plane is STALE — the exporter didn't run after the corpus changed, which
    is the exact two-plane divergence D-60 exists to prevent. Standalone (parquet
    only, no DB — the audit can't read the serving SQLite)."""
    warns: list[str] = []
    flags = {"GOLD_PLANE_STALE": False}
    dt_path, tc_path = modeled_dir / "dim_tracks.parquet", marts_dir / "track_card.parquet"
    if not dt_path.exists() or not tc_path.exists():
        return warns, flags     # a pre-D-60 warehouse has no catalog fact to compare
    dt, tc = pd.read_parquet(dt_path), pd.read_parquet(tc_path)
    if BRIDGE not in dt.columns or BRIDGE not in tc.columns:
        return warns, flags
    # the gold catalog only claims to track fact_track_features' population; if
    # dim_tracks still carries the pre-D-60 vintage (a fact-only frozen plane),
    # there's nothing to agree with yet.
    if not (modeled_dir / "fact_track_features.parquet").exists():
        return warns, flags
    dt_ids, tc_ids = set(dt[BRIDGE].dropna()), set(tc[BRIDGE].dropna())
    if dt_ids != tc_ids:
        warns.append(
            f"modeled/dim_tracks vs marts/track_card: catalog planes diverge "
            f"({len(dt_ids - tc_ids)} only in gold, {len(tc_ids - dt_ids)} only in "
            f"serving) — run scripts/export_gold_from_cache.py — GOLD_PLANE_STALE")
        flags["GOLD_PLANE_STALE"] = True
    return warns, flags


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
    # The coverage invariant is checked against the CURRENT catalog fact
    # (fact_track_features, D-60 — materialized from the serving cache). The
    # historical fact_listening_features is a self-contained Jul-4 drift snapshot
    # (it denormalizes track_name/artist into the fact and its vintage predates
    # the current dedup), so it is NOT pinned to the current dim_tracks — a few
    # of its tracks are now flagged twins/quarantined and that's honest history,
    # not an orphan. Older warehouses (no track-grain fact) fall back to the only
    # fact present.
    join_orphans = False
    fact = next((df for k, df in tables.items()
                 if k.startswith("modeled/") and "fact_track_features" in k.lower()), None)
    if fact is None:
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

    # --- metadata-says-one / acoustics-say-two (O4d) ------------------------
    dis_report, dis_warnings, dis_flags = check_dedup_disagreement(MARTS)
    warnings.extend(dis_warnings)

    # --- gold catalog <-> serving marts agreement (D-60) --------------------
    pa_warnings, pa_flags = check_plane_agreement(WAREHOUSE / "modeled", MARTS)
    warnings.extend(pa_warnings)

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
        **dis_flags,
        **pa_flags,
    }
    print(json.dumps({"layers": layers, "audio": audio, "marts": marts_report,
                      "duplicates": dup_report, "disagreements": dis_report,
                      "errors": errors,
                      "warnings": warnings, "flags": flags}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
