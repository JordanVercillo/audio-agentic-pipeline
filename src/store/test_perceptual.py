"""
test_perceptual.py — the perceptual-v1 transform, synthetic (VISION_SPECS F1).

Two acoustically-opposite blobs → the derived features must order them the
right way round; measured features must match exact math; sparse rows sit out.
"""

from __future__ import annotations

import math

import pytest

from .cache import FeatureCache
from .perceptual import (
    CATALOG,
    PERCEPTUAL_VERSION,
    catalog_frame,
    compute_perceptual,
    persist_perceptual,
)


def _club(i: float) -> dict:
    """Danceable club blob: ~120 bpm, loud, bright, punchy, regular pulse."""
    return {"tempo_bpm": 118 + i, "rms_mean": 0.30, "rms_std": 0.02,
            "zcr_mean": 0.09, "spectral_centroid_mean": 3000.0,
            "spectral_rolloff_mean": 6000.0, "spectral_flatness_mean": 0.05,
            "harmonic_ratio": 0.35, "onset_strength_mean": 3.0,
            "onset_strength_std": 0.5, "beats_per_sec": 2.0,
            "duration_sec": 200.0, "estimated_key": 7.0, "estimated_mode": "major"}


def _folk(i: float) -> dict:
    """Acoustic folk blob: slow, quiet, dark, harmonic, loose pulse."""
    return {"tempo_bpm": 62 + i, "rms_mean": 0.08, "rms_std": 0.05,
            "zcr_mean": 0.03, "spectral_centroid_mean": 1200.0,
            "spectral_rolloff_mean": 2500.0, "spectral_flatness_mean": 0.01,
            "harmonic_ratio": 0.85, "onset_strength_mean": 0.8,
            "onset_strength_std": 0.9, "beats_per_sec": 1.0,
            "duration_sec": 180.0, "estimated_key": 2.0, "estimated_mode": "minor"}


@pytest.fixture
def corpus(tmp_path):
    cache = FeatureCache(url=f"sqlite:///{tmp_path / 'p.db'}")
    for i in range(5):
        cache.upsert(f"club{i}", _club(i), time_signature=4)   # 4/4 club
        cache.upsert(f"folk{i}", _folk(i), time_signature=3)   # 3/4 folk waltz
    cache.upsert("ghost", {"tempo_bpm": None})  # never-acquired track
    return cache


def test_measured_features_exact(corpus):
    df = compute_perceptual(corpus).set_index("spotify_track_id")
    row = df.loc["club0"]
    assert row["tempo"] == 118.0
    assert row["key"] == 7 and row["mode"] == 1.0          # "major" → 1
    assert df.loc["folk0", "mode"] == 0.0                  # "minor" → 0
    assert row["duration_sec"] == 200.0
    assert row["loudness_db"] == round(20 * math.log10(0.30), 2)  # exact math
    assert row["time_signature"] == 4 and df.loc["folk0", "time_signature"] == 3  # promoted column
    assert (df["version"] == PERCEPTUAL_VERSION).all()


def test_derived_features_order_the_blobs_correctly(corpus):
    df = compute_perceptual(corpus).set_index("spotify_track_id")
    club, folk = df.loc["club2"], df.loc["folk2"]
    assert club["energy"] > folk["energy"]                 # loud+punchy beats quiet
    assert club["danceability"] > folk["danceability"]     # 120bpm regular > 62bpm loose
    assert folk["acousticness"] > club["acousticness"]     # harmonic+dark beats bright
    assert club["brightness"] > folk["brightness"]
    assert folk["dynamics"] > club["dynamics"]             # rms_std 0.05 > 0.02
    for col in ("energy", "danceability", "acousticness", "speechiness",
                "brightness", "punch", "dynamics", "valence_proxy"):
        assert df[col].between(0, 1).all(), col            # calibrated range


def test_ghost_row_sits_out(corpus):
    df = compute_perceptual(corpus)
    assert len(df) == 10 and "ghost" not in set(df["spotify_track_id"])


def test_persist_and_read_back(corpus):
    df = compute_perceptual(corpus)
    n = persist_perceptual(corpus, df)
    assert n == 10
    got = corpus.get_perceptual(["club0", "ghost"])
    assert set(got) == {"club0"}
    assert got["club0"]["tempo"] == 118.0 and "danceability" in got["club0"]
    # idempotent rerun
    assert persist_perceptual(corpus, df) == 10
    assert len(corpus.all_perceptual()) == 10


def test_catalog_integrity():
    cat = catalog_frame()
    assert set(cat["tier"]) == {"measured", "derived", "experimental"}
    assert len(cat) == len(CATALOG) == cat["column"].nunique()
    # every catalog column is actually produced by the transform
    cache_cols = {"spotify_track_id", "version"}
    produced = set(compute_perceptual_cols())
    assert set(cat["column"]) <= produced - cache_cols
    # experimental features carry a caveat in their description
    exp = cat[cat["tier"] == "experimental"]
    assert all("proxy" in d.lower() or "heuristic" in d.lower()
               for d in exp["description"])


def compute_perceptual_cols() -> list[str]:
    """The transform's output columns, derived from a tiny in-memory run."""
    cache = FeatureCache(url="sqlite://")  # in-memory
    for i in range(4):
        cache.upsert(f"a{i}", _club(i))
        cache.upsert(f"b{i}", _folk(i))
    return list(compute_perceptual(cache).columns)


def test_empty_cache_returns_empty_frame(tmp_path):
    cache = FeatureCache(url=f"sqlite:///{tmp_path / 'empty.db'}")
    df = compute_perceptual(cache)
    assert df.empty


# ── the feature_stats distribution mart (F2) ────────────────────────────────
def _stats_frame(corpus):
    from .perceptual import compute_feature_stats
    return compute_feature_stats(compute_perceptual(corpus))


def test_feature_stats_one_row_per_catalog_feature(corpus):
    stats = _stats_frame(corpus)
    assert set(stats["column"]) == {c["column"] for c in CATALOG}
    assert (stats["n"] == 10).all()  # ghost sat out upstream


def test_feature_stats_percentiles_ordered_and_bins_sum(corpus):
    stats = _stats_frame(corpus).set_index("column")
    for col, row in stats.iterrows():
        assert row["min"] <= row["p5"] <= row["p25"] <= row["p50"] \
            <= row["p75"] <= row["p95"] <= row["max"], col
        assert sum(row["bin_counts"]) == row["n"], col
        assert len(row["bin_counts"]) == len(row["bin_edges"]) - 1, col


def test_feature_stats_binning_rules(corpus):
    stats = _stats_frame(corpus).set_index("column")
    assert stats.loc["mode", "bin_edges"] == [-0.5, 0.5, 1.5]           # 2 bins
    assert len(stats.loc["key", "bin_counts"]) == 12                    # pitch classes
    dance = stats.loc["danceability", "bin_edges"]
    assert dance[0] == 0.0 and dance[-1] == 1.0 and len(dance) == 21    # fixed 0–1
    tempo = stats.loc["tempo", "bin_edges"]
    assert tempo[0] == 62.0 and tempo[-1] == 122.0                      # population min–max
    ts = stats.loc["time_signature"]                                   # F-v2b: discrete meters
    assert ts["bin_edges"] == [1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5]
    assert ts["n"] == 10 and ts["min"] == 3.0 and ts["max"] == 4.0 and sum(ts["bin_counts"]) == 10


# ── rebuild_marts: the single rebuild entry point (script + worker) ─────────
def test_rebuild_marts_writes_all_three_and_persists(corpus, tmp_path):
    from .perceptual import rebuild_marts
    marts = tmp_path / "marts"
    result = rebuild_marts(corpus, marts)
    assert result["n_tracks"] == 10
    for name in ("track_perceptual", "feature_catalog", "feature_stats"):
        assert (marts / f"{name}.parquet").exists(), name
    assert not list(marts.glob("*.tmp"))        # atomic writes leave no temp files
    assert len(corpus.all_perceptual()) == 10   # cache table persisted too
    # rerun after the population grows — a worker drain does exactly this
    corpus.upsert("club9", _club(9))
    assert rebuild_marts(corpus, marts)["n_tracks"] == 11
    import pandas as pd
    assert len(pd.read_parquet(marts / "track_perceptual.parquet")) == 11


def test_rebuild_marts_empty_cache_writes_nothing(tmp_path):
    from .perceptual import rebuild_marts
    cache = FeatureCache(url=f"sqlite:///{tmp_path / 'e.db'}")
    assert rebuild_marts(cache, tmp_path / "marts")["n_tracks"] == 0
    assert not (tmp_path / "marts").exists()


# ── the audit extension (F2): catalog↔mart parity checks ───────────────────
def _load_audit_module():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / ".claude" / "skills" \
        / "warehouse-audit" / "audit_warehouse.py"
    spec = importlib.util.spec_from_file_location("audit_warehouse", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_marts(tmp_path, corpus, *, drop_stat_row=False, extra_mart_col=False):
    from .perceptual import catalog_frame, compute_feature_stats
    df = compute_perceptual(corpus)
    if extra_mart_col:
        df["rogue_feature"] = 0.5  # in the mart, not in the catalog
    marts = tmp_path / "marts"
    marts.mkdir()
    df.to_parquet(marts / "track_perceptual.parquet", index=False)
    catalog_frame().to_parquet(marts / "feature_catalog.parquet", index=False)
    stats = compute_feature_stats(df)
    if drop_stat_row:
        stats = stats[stats["column"] != "danceability"]
    stats.to_parquet(marts / "feature_stats.parquet", index=False)
    return marts


# Every check_marts flag, all-clear — the exact-dict discipline (a NEW flag
# must be added here deliberately, with its own positive test).
_ALL_MART_FLAGS_FALSE = {
    "CATALOG_MART_DRIFT": False, "STATS_MART_DRIFT": False,
    "FEATURE_DISTRIBUTION": False, "PLANE_COHERENCE": False,
    "SEMANTIC_PARITY": False, "CLUSTER_PROFILE_DRIFT": False,
    "PROVENANCE_ORPHAN": False,
}


def test_audit_marts_green_on_good_marts(corpus, tmp_path):
    audit = _load_audit_module()
    report, warnings, errors, flags = audit.check_marts(_write_marts(tmp_path, corpus))
    assert flags == _ALL_MART_FLAGS_FALSE
    assert not errors
    assert report["track_perceptual"]["rows"] == 10


def test_audit_marts_catches_catalog_drift(corpus, tmp_path):
    audit = _load_audit_module()
    marts = _write_marts(tmp_path, corpus, extra_mart_col=True)
    _, warnings, _, flags = audit.check_marts(marts)
    assert flags["CATALOG_MART_DRIFT"] is True
    assert any("uncataloged" in w for w in warnings)


def test_audit_marts_catches_stats_drift(corpus, tmp_path):
    audit = _load_audit_module()
    marts = _write_marts(tmp_path, corpus, drop_stat_row=True)
    _, warnings, _, flags = audit.check_marts(marts)
    assert flags["STATS_MART_DRIFT"] is True
    assert any("no stats for" in w for w in warnings)


def test_audit_marts_absent_is_a_note_not_a_finding(tmp_path):
    audit = _load_audit_module()
    report, warnings, errors, flags = audit.check_marts(tmp_path / "nope")
    assert flags == _ALL_MART_FLAGS_FALSE
    assert not errors and any("not built" in w for w in warnings)


# ── DUPLICATE_TRACKS (Epic O / D-28) ─────────────────────────────────────────
def _write_dim_tracks(tmp_path, rows):
    import pandas as pd
    modeled = tmp_path / "modeled"
    modeled.mkdir()
    pd.DataFrame(rows).to_parquet(modeled / "dim_tracks.parquet", index=False)
    return modeled


def test_audit_flags_duplicate_tracks(tmp_path):
    audit = _load_audit_module()
    modeled = _write_dim_tracks(tmp_path, [
        {"spotify_track_id": "a", "track_name": "Hysteria", "artist_names": "Muse", "duration_ms": 210000},
        {"spotify_track_id": "b", "track_name": "Hysteria - Remastered 2019", "artist_names": "Muse", "duration_ms": 210500},
        {"spotify_track_id": "c", "track_name": "Uprising", "artist_names": "Muse", "duration_ms": 300000}])
    report, warns, flags = audit.check_duplicates(modeled)
    assert flags["DUPLICATE_TRACKS"] is True                  # advisory flag fires
    assert report["n_clusters"] == 1 and report["n_duplicate_tracks"] == 1
    assert any("DUPLICATE_TRACKS" in w for w in warns)


def test_audit_duplicate_tracks_clean_when_all_unique(tmp_path):
    audit = _load_audit_module()
    modeled = _write_dim_tracks(tmp_path, [
        {"spotify_track_id": "a", "track_name": "Hysteria", "artist_names": "Muse", "duration_ms": 210000},
        {"spotify_track_id": "b", "track_name": "Uprising", "artist_names": "Muse", "duration_ms": 300000}])
    _, warns, flags = audit.check_duplicates(modeled)
    assert flags["DUPLICATE_TRACKS"] is False and not warns


def test_audit_duplicate_tracks_absent_is_a_note(tmp_path):
    audit = _load_audit_module()
    report, warns, flags = audit.check_duplicates(tmp_path / "nope")
    assert flags == {"DUPLICATE_TRACKS": False} and report == {} and not warns


# ── distribution sanity (journal #21, operationalized) ──────────────────────
def test_population_n_stamped(corpus):
    df = compute_perceptual(corpus)
    assert (df["population_n"] == 10).all()          # every row knows its calibration n
    persist_perceptual(corpus, df)
    got = corpus.get_perceptual(["club0"])["club0"]
    assert got["population_n"] == 10                 # travels into the cache payload


def test_distribution_checks_pass_on_good_corpus(corpus):
    from .perceptual import compute_feature_stats
    audit = _load_audit_module()
    stats = compute_feature_stats(compute_perceptual(corpus))
    assert audit.check_distributions(stats) == []


def test_distribution_checks_catch_implausible_shapes(corpus):
    from .perceptual import compute_feature_stats
    audit = _load_audit_module()
    stats = compute_feature_stats(compute_perceptual(corpus))

    bad = stats.copy()
    bad.loc[bad["column"] == "tempo", "min"] = 5.0     # octave-error territory
    assert any("tempo" in w for w in audit.check_distributions(bad))

    bad = stats.copy()
    bad.loc[bad["column"] == "energy", "max"] = 1.7    # calibrated tier out of 0–1
    assert any("energy" in w for w in audit.check_distributions(bad))

    bad = stats.copy()
    bad.loc[bad["column"] == "tempo", ["std", "n"]] = [0.0, 25]  # zero spread at n>=20
    assert any("zero spread" in w for w in audit.check_distributions(bad))


def test_distribution_checks_flag_non_modal_four(corpus):
    # journal #19's bug, as the audit would have seen it: 2/4 dominating.
    from .perceptual import compute_feature_stats
    audit = _load_audit_module()
    stats = compute_feature_stats(compute_perceptual(corpus))
    idx = stats.index[stats["column"] == "time_signature"][0]
    counts = list(stats.at[idx, "bin_counts"])
    counts[0], counts[2] = 15, 2                      # meter 2 dominates, 4 rare
    stats.at[idx, "bin_counts"] = counts
    stats.at[idx, "n"] = int(sum(counts))
    assert any("modal meter" in w for w in audit.check_distributions(stats))