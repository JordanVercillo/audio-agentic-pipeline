# /// script
# requires-python = ">=3.10"
# ///
"""Live-system audit for the running app (complements warehouse-audit=data,
env-verify=environment). Stdlib-only; JSON report; exit 0 unless it can't run.

Run:  uv run .claude/skills/app-verify/verify_app.py [--skip-public]
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DB = REPO / "data" / "feature_cache.db"
MARTS = REPO / "data" / "marts"
SPECTROGRAMS = REPO / "data" / "spectrograms"
PUBLIC = "https://vercilloanalytics.com/healthz"
LOCAL = "http://127.0.0.1:8000/healthz"


def _get(url: str, timeout: float) -> bool:
    try:
        # Cloudflare challenges urllib's default UA — send a browser-ish one.
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 app-verify"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return b'"ok"' in r.read(200) or r.status == 200
    except Exception:
        return False


def main() -> int:
    skip_public = "--skip-public" in sys.argv
    report: dict = {}

    report["webapp_local"] = _get(LOCAL, 3)
    report["public_url"] = None if skip_public else _get(PUBLIC, 12)
    try:
        out = subprocess.run(["sc", "query", "cloudflared"], capture_output=True,
                             text=True, timeout=10).stdout
        report["tunnel_service"] = "RUNNING" in out
    except Exception:
        report["tunnel_service"] = False

    cache: dict = {}
    if DB.exists():
        con = sqlite3.connect(DB)
        try:
            q = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
            cache["track_features"] = q("SELECT count(*) FROM track_features")
            for t in ("track_perceptual", "cluster_models", "track_meta"):
                try:
                    cache[t] = q(f"SELECT count(*) FROM {t}")
                except sqlite3.OperationalError:
                    cache[t] = None
            try:
                cache["jobs_by_status"] = dict(con.execute(
                    "SELECT status, count(*) FROM extraction_jobs GROUP BY status"))
            except sqlite3.OperationalError:
                cache["jobs_by_status"] = {}
        finally:
            con.close()
    report["cache"] = cache
    report["marts"] = sorted(p.name for p in MARTS.glob("*.parquet")) if MARTS.is_dir() else []
    report["spectrograms"] = len(list(SPECTROGRAMS.glob("*.png"))) if SPECTROGRAMS.is_dir() else 0
    report["golden_evals"] = (REPO / "evals" / "golden_taste_v1.jsonl").exists()

    report["flags"] = {
        "WEBAPP_DOWN": not report["webapp_local"],
        "PUBLIC_DOWN": (report["public_url"] is False),
        "TUNNEL_DOWN": not report["tunnel_service"],
        "CACHE_EMPTY": not cache.get("track_features"),
        "MARTS_MISSING": len(report["marts"]) < 3,
        "EVALS_MISSING": not report["golden_evals"],
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
