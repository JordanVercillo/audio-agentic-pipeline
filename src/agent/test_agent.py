"""
test_agent.py — Agent Access Layer tests (synthetic warehouse only)
====================================================================
SPEC P5 acceptance: tool functions unit-tested against a synthetic gold
layer; injection guard rejects non-SELECT; the DuckDB sandbox blocks file
access even if the guard were bypassed. No MCP runtime, no real warehouse.
"""

import json

import duckdb
import pandas as pd
import pytest

from src.agent.warehouse_agent import WarehouseAgent, is_safe_sql


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Synthetic gold layer
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.fixture()
def warehouse(tmp_path):
    modeled = tmp_path / "modeled"
    artifacts = tmp_path / "artifacts"
    modeled.mkdir()
    artifacts.mkdir()

    fact = pd.DataFrame([
        {"spotify_track_id": "t1", "time_range": "short_term", "rank": 1,
         "track_name": "Loud One", "primary_artist_name": "Artist A",
         "tempo_bpm": 150.0, "rms_mean": 0.9},
        {"spotify_track_id": "t2", "time_range": "short_term", "rank": 2,
         "track_name": "Quiet One", "primary_artist_name": "Artist B",
         "tempo_bpm": 90.0, "rms_mean": 0.2},
        {"spotify_track_id": "t1", "time_range": "long_term", "rank": 5,
         "track_name": "Loud One", "primary_artist_name": "Artist A",
         "tempo_bpm": 150.0, "rms_mean": 0.9},
    ])
    fact.to_parquet(modeled / "fact_listening_features.parquet", index=False)

    dim_tracks = pd.DataFrame([
        {"spotify_track_id": "t1", "track_name": "Loud One", "explicit": True},
        {"spotify_track_id": "t2", "track_name": "Quiet One", "explicit": False},
    ])
    dim_tracks.to_parquet(modeled / "dim_tracks.parquet", index=False)

    col_desc = pd.DataFrame([
        {"column_name": "spotify_track_id", "description": "Universal join key."},
        {"column_name": "rms_mean", "description": "Perceived loudness (energy)."},
        {"column_name": "tempo_bpm", "description": "Estimated tempo in BPM."},
    ])
    col_desc.to_parquet(modeled / "column_descriptions.parquet", index=False)

    (artifacts / "insights.json").write_text(
        json.dumps({"schema_version": 1, "drift": {"score": 0.14}}), encoding="utf-8")

    with WarehouseAgent(modeled_dir=modeled, artifacts_dir=artifacts) as agent:
        yield agent


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Layer 1: statement guard
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestSqlGuard:
    @pytest.mark.parametrize("sql", [
        "SELECT * FROM fact_listening_features",
        "select track_name from dim_tracks where explicit",
        "WITH t AS (SELECT * FROM dim_tracks) SELECT count(*) FROM t",
        "SELECT * FROM fact_listening_features;",          # single trailing ;
        "SELECT 1 -- a trailing comment",
    ])
    def test_accepts_read_queries(self, sql):
        ok, reason = is_safe_sql(sql)
        assert ok, reason

    @pytest.mark.parametrize("sql,needle", [
        ("INSERT INTO dim_tracks VALUES ('x')", "SELECT/WITH"),
        ("UPDATE dim_tracks SET explicit=true", "SELECT/WITH"),
        ("DELETE FROM dim_tracks", "SELECT/WITH"),
        ("DROP TABLE dim_tracks", "SELECT/WITH"),
        ("CREATE TABLE x AS SELECT 1", "SELECT/WITH"),
        ("ATTACH 'evil.db'", "SELECT/WITH"),
        ("PRAGMA database_list", "SELECT/WITH"),
        ("SELECT 1; DROP TABLE dim_tracks", "single statement"),
        ("SELECT 1; SELECT 2", "single statement"),
        ("SELECT * FROM read_parquet('/etc/passwd')", "Forbidden"),
        ("SELECT * FROM read_csv('C:/Windows/win.ini')", "Forbidden"),
        ("SELECT * FROM glob('*')", "Forbidden"),
        ("SELECT 1; SET enable_external_access=true", "single statement"),
        ("", "Empty"),
        ("-- just a comment", "only comments"),
    ])
    def test_rejects_dangerous_queries(self, sql, needle):
        ok, reason = is_safe_sql(sql)
        assert not ok
        assert needle.lower() in reason.lower()

    def test_comment_hidden_second_statement_rejected(self):
        # A forbidden op hidden after a comment-terminated line must not slip through.
        ok, reason = is_safe_sql("SELECT 1 --\n; DROP TABLE dim_tracks")
        assert not ok


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Layer 2: DuckDB sandbox (hard boundary)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestSandbox:
    def test_file_read_blocked_even_bypassing_guard(self, warehouse):
        # Reach past the statement guard straight to the sealed connection:
        # the sandbox itself must refuse arbitrary file access.
        con = warehouse._con
        with pytest.raises(duckdb.Error):
            con.execute("SELECT * FROM read_csv('C:/Windows/win.ini')").fetchall()

    def test_config_cannot_be_reenabled(self, warehouse):
        con = warehouse._con
        with pytest.raises(duckdb.Error):
            con.execute("SET enable_external_access=true")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Tools
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestSchema:
    def test_lists_content_tables_with_descriptions(self, warehouse):
        schema = warehouse.get_schema()
        assert schema["bridge_key"] == "spotify_track_id"
        assert "fact_listening_features" in schema["tables"]
        assert "dim_tracks" in schema["tables"]
        assert "column_descriptions" not in schema["tables"]  # metadata, not content

        fact = schema["tables"]["fact_listening_features"]
        assert fact["row_count"] == 3
        rms = next(c for c in fact["columns"] if c["name"] == "rms_mean")
        assert "loudness" in rms["description"].lower()


class TestQuery:
    def test_answers_a_taste_question(self, warehouse):
        # "Highest-energy track in short_term?"
        res = warehouse.query_warehouse(
            "SELECT track_name, rms_mean FROM fact_listening_features "
            "WHERE time_range='short_term' ORDER BY rms_mean DESC LIMIT 1")
        assert res["ok"]
        assert res["columns"] == ["track_name", "rms_mean"]
        assert res["rows"][0][0] == "Loud One"
        assert res["row_count"] == 1
        assert res["truncated"] is False

    def test_rejected_query_returns_error_not_raises(self, warehouse):
        res = warehouse.query_warehouse("DROP TABLE dim_tracks")
        assert res["ok"] is False
        assert "rejected" in res["error"].lower()
        # table still intact
        assert warehouse.query_warehouse("SELECT count(*) FROM dim_tracks")["rows"][0][0] == 2

    def test_bad_sql_returns_error_not_raises(self, warehouse):
        res = warehouse.query_warehouse("SELECT nonexistent_col FROM dim_tracks")
        assert res["ok"] is False
        assert "failed" in res["error"].lower()

    def test_truncation_flag(self, warehouse):
        res = warehouse.query_warehouse(
            "SELECT * FROM fact_listening_features", max_rows=1)
        assert res["row_count"] == 1
        assert res["truncated"] is True


class TestInsights:
    def test_serves_insights_json(self, warehouse):
        ins = warehouse.get_insights()
        assert ins["schema_version"] == 1
        assert ins["drift"]["score"] == 0.14

    def test_missing_insights_returns_error(self, tmp_path):
        modeled = tmp_path / "m"
        modeled.mkdir()
        pd.DataFrame([{"spotify_track_id": "t1"}]).to_parquet(
            modeled / "dim_tracks.parquet", index=False)
        with WarehouseAgent(modeled_dir=modeled, artifacts_dir=tmp_path / "none") as agent:
            res = agent.get_insights()
        assert res["ok"] is False
        assert "not found" in res["error"].lower()


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
