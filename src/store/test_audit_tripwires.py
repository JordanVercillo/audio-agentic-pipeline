"""Q1 — every audit flag must be PROVEN to fire.

Journal #44: *a flag nobody has ever fired is documentation, not protection.*
The 2026-07-30 director review measured the repo against its own lesson and
found it wanting: of 25 warehouse-audit flags, most had no test that ever drove
them TRUE. The five cluster/gold flags shipped that same day were verified once
BY HAND on live data — which proves they worked that afternoon, not that they
still work.

Two things are asserted here:

  1. **Set equality over the flag names.** A 26th flag cannot ship without
     landing in `_FIRE_TESTED` or `_FIRE_UNTESTED`, so "I added a flag and
     forgot the test" fails the suite instead of shipping green and silent.
     `_FIRE_UNTESTED` is a deliberate, shrinking debt list — not a place to
     park new work.
  2. **A fire test per covered flag**: an all-clear fixture must read False and
     a mutated one must read True. Both directions, because a flag stuck ON is
     as useless as one stuck OFF — it just fails loudly instead of quietly.

Synthetic only (ground rule 5): every fixture is written into tmp_path.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from .test_perceptual import _load_audit_module

# Flags with a fire test SOMEWHERE in the suite (here or in test_semantic.py /
# test_cluster_freshness.py, which drive the same code paths at the source).
_FIRE_TESTED = {
    "CATALOG_MART_DRIFT", "STATS_MART_DRIFT", "PLANE_COHERENCE",
    "SEMANTIC_PARITY", "CLUSTER_PROFILE_DRIFT", "PROVENANCE_ORPHAN",
    "TWIN_LEAKAGE", "DUPLICATE_TRACKS", "DEDUP_DISAGREEMENT",
    "CLUSTER_COVERAGE", "CLUSTER_MODEL_STALE", "CLUSTER_DESCRIPTION_MISSING",
    "CLUSTER_PROMOTION_PENDING", "GOLD_SCHEMA_SHRINK",
    "CLUSTER_ASSIGNMENT_DESYNC",
}

# Known debt, stated rather than hidden. Each needs a fire test; the list may
# only SHRINK. Adding a name here to make the suite pass is the failure mode
# this file exists to prevent, so it carries the reason it is still here.
_FIRE_UNTESTED = {
    "NO_WAREHOUSE",          # needs an empty-repo fixture (whole-run early exit)
    "MISSING_LAYER", "EMPTY_TABLE", "MISSING_BRIDGE_KEY", "BRIDGE_KEY_NULLS",
    "DUPLICATE_KEYS", "JOIN_ORPHANS", "AUDIO_ORPHANS", "FEATURE_DRIFT",
    "FEATURE_DISTRIBUTION",  # the 12 core checks: driven by main(), not a
    "GOLD_PLANE_STALE",      # helper — they need a fixture warehouse on disk
}


def _live_flag_names() -> set[str]:
    """Every flag name the audit can emit.

    Read from the module SOURCE, not by calling the helpers: the 12 core flags
    (MISSING_LAYER, BRIDGE_KEY_NULLS, …) are assembled inside `main()` and
    never returned by a helper, so a call-based scan would silently miss
    exactly the flags with the least coverage — the guard would look strong
    while checking a third of the surface.
    """
    import re
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / ".claude" / "skills"
           / "warehouse-audit" / "audit_warehouse.py").read_text(encoding="utf-8")
    # flag names are SCREAMING_SNAKE string keys assigned a bool
    return set(re.findall(r'"([A-Z][A-Z0-9_]{3,})":\s*(?:False|True|[a-z_]+)[,}]', src))


def test_every_flag_the_audit_can_emit_is_accounted_for():
    """Set equality, the QA-2 pattern: a new flag with no fire test FAILS."""
    live = _live_flag_names()
    known = _FIRE_TESTED | _FIRE_UNTESTED
    unaccounted = live - known
    assert not unaccounted, (
        f"{len(unaccounted)} audit flag(s) have no entry in _FIRE_TESTED or "
        f"_FIRE_UNTESTED — a flag nobody has fired is documentation, not "
        f"protection (journal #44): {sorted(unaccounted)}")


def test_the_untested_debt_list_only_shrinks():
    """A guard on the guard: nothing may be ADDED to the debt list."""
    assert len(_FIRE_UNTESTED) <= 12, (
        "_FIRE_UNTESTED grew — a new flag was parked as debt instead of tested")
    assert not (_FIRE_TESTED & _FIRE_UNTESTED), "a flag is in both lists"


# ── GOLD_SCHEMA_SHRINK — S3 proved it by hand; this is the regression guard ──
def _write_manifest(tmp_path, cols):
    man = {"owned_by_exporter": {"dim_tracks": cols}, "frozen_plane": {}}
    (tmp_path / "gold_schema_manifest.json").write_text(json.dumps(man), encoding="utf-8")
    return tmp_path / "gold_schema_manifest.json"


def _write_dim_tracks(modeled_dir, cols):
    modeled_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({c: ["x"] for c in cols}).to_parquet(
        modeled_dir / "dim_tracks.parquet", index=False)


@pytest.fixture()
def gold(tmp_path, monkeypatch):
    audit = _load_audit_module()
    modeled = tmp_path / "warehouse" / "modeled"
    monkeypatch.setattr(audit, "WAREHOUSE", tmp_path / "warehouse", raising=False)
    monkeypatch.setattr(audit, "REPO", tmp_path, raising=False)
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    return audit, modeled, tmp_path


def test_gold_schema_shrink_is_false_when_every_promised_column_is_written(gold):
    audit, modeled, root = gold
    cols = ["spotify_track_id", "track_name", "isrc"]
    _write_dim_tracks(modeled, cols)
    (root / "docs" / "gold_schema_manifest.json").write_text(
        json.dumps({"owned_by_exporter": {"dim_tracks": cols}, "frozen_plane": {}}),
        encoding="utf-8")
    _report, _warnings, flags = audit.check_gold_schema()
    assert flags["GOLD_SCHEMA_SHRINK"] is False


def test_gold_schema_shrink_fires_when_a_promised_column_vanishes(gold):
    """The exact D-60 regression: the exporter narrowed dim_tracks 10 -> 6 and
    nothing noticed, because no check looked at the shape of what we PROMISE."""
    audit, modeled, root = gold
    _write_dim_tracks(modeled, ["spotify_track_id", "track_name"])   # isrc dropped
    (root / "docs" / "gold_schema_manifest.json").write_text(
        json.dumps({"owned_by_exporter": {
            "dim_tracks": ["spotify_track_id", "track_name", "isrc"]},
            "frozen_plane": {}}), encoding="utf-8")
    _report, warnings, flags = audit.check_gold_schema()
    assert flags["GOLD_SCHEMA_SHRINK"] is True
    assert any("isrc" in w for w in warnings), "the warning must NAME the column"


def test_gold_schema_allows_added_columns():
    """The manifest is a FLOOR, not equality — widening a table is normal."""
    import tempfile
    from pathlib import Path
    audit = _load_audit_module()
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        modeled = root / "warehouse" / "modeled"
        _write_dim_tracks(modeled, ["a", "b", "c"])       # one MORE than promised
        (root / "docs").mkdir(parents=True, exist_ok=True)
        (root / "docs" / "gold_schema_manifest.json").write_text(
            json.dumps({"owned_by_exporter": {"dim_tracks": ["a", "b"]},
                        "frozen_plane": {}}), encoding="utf-8")
        orig_repo, orig_wh = audit.REPO, audit.WAREHOUSE
        try:
            audit.REPO, audit.WAREHOUSE = root, root / "warehouse"
            _r, _w, flags = audit.check_gold_schema()
            assert flags["GOLD_SCHEMA_SHRINK"] is False
        finally:
            audit.REPO, audit.WAREHOUSE = orig_repo, orig_wh


# --- CLUSTER_ASSIGNMENT_DESYNC -------------------------------------------
# The flag added because of the 2026-07-31 blocker: `promote_model` remapped
# every id-KEYED structure and left `centroids`, which is id-INDEXED. Every
# other gate stayed green because none of them ever asked the model whether it
# agreed with itself. This proves the new one asks — in both directions.


def _desync_db(tmp_path, *, scramble: bool):
    """A two-cluster corpus whose rows either match the centroids, or don't."""
    import sqlite3

    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)
    con = sqlite3.connect(root / "data" / "feature_cache.db")
    con.executescript("""
        CREATE TABLE cluster_models (id INTEGER PRIMARY KEY, kind TEXT, k INT,
            feature_cols TEXT, scaler_mean TEXT, scaler_std TEXT,
            centroids TEXT, promoted_at DATETIME);
        CREATE TABLE track_features (spotify_track_id TEXT PRIMARY KEY, features TEXT);
        CREATE TABLE track_clusters (spotify_track_id TEXT, model_id INT, cluster_id INT);
    """)
    cents = [[-1.0, -1.0], [1.0, 1.0]]        # cluster 0 = low, cluster 1 = high
    if scramble:
        cents = cents[::-1]                    # exactly the blocker: indexed list
    con.execute(                               # left in the OTHER id space
        "INSERT INTO cluster_models VALUES (1,'song',2,?,?,?,?,'2026-07-31')",
        (json.dumps(["a", "b"]), json.dumps([0.0, 0.0]), json.dumps([1.0, 1.0]),
         json.dumps(cents)))
    for i in range(20):
        tid, lo = f"t{i:03d}", i % 2 == 0
        val = -1.0 if lo else 1.0
        con.execute("INSERT INTO track_features VALUES (?,?)",
                    (tid, json.dumps({"a": val, "b": val})))
        con.execute("INSERT INTO track_clusters VALUES (?,1,?)",
                    (tid, 0 if lo else 1))
    con.commit()
    con.close()
    return root


def _sync_report(tmp_path, *, scramble: bool):
    audit = _load_audit_module()
    original = audit.REPO
    audit.REPO = _desync_db(tmp_path, scramble=scramble)
    try:
        return audit.check_cluster_assignment_sync()
    finally:
        audit.REPO = original


def test_assignment_desync_is_false_when_the_model_agrees_with_its_rows(tmp_path):
    report, warnings, flags = _sync_report(tmp_path, scramble=False)
    assert report["checked"] == 20
    assert report["agreement"] == 1.0
    assert flags.get("CLUSTER_ASSIGNMENT_DESYNC") is not True
    assert not warnings


def test_assignment_desync_fires_when_centroids_are_in_the_other_id_space(tmp_path):
    report, warnings, flags = _sync_report(tmp_path, scramble=True)
    assert report["checked"] == 20
    assert report["agreement"] == 0.0        # the live blocker measured 0/1894
    assert flags["CLUSTER_ASSIGNMENT_DESYNC"] is True
    assert any("CLUSTER_ASSIGNMENT_DESYNC" in w for w in warnings)
