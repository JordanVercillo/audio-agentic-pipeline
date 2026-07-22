"""
warehouse_agent.py — Retrieval core for the Agent Access Layer (SPEC P5)
=========================================================================
Read-only, self-describing access to the gold warehouse for AI agents.
Pure DuckDB + pandas — no MCP runtime, so it's unit-testable and reusable
(the MCP server wraps it; P8's RAG will too).

Security model (two independent layers — defense in depth):

    1. Statement guard (`is_safe_sql`): the query must be a SINGLE statement
       beginning with SELECT or WITH, with no dangerous verbs or file-reading
       table functions. Gives clear errors and states the read-only contract.

    2. DuckDB sandbox (the hard boundary): the gold Parquet is loaded into
       NATIVE in-memory tables, then ``enable_external_access=false`` +
       ``lock_configuration=true`` are set. After that the connection cannot
       read/write any file, reach the network, install extensions, attach
       databases, or re-enable any of the above — verified: arbitrary file
       reads raise PermissionException, re-enabling raises InvalidInputException.
       The DB is in-memory and ephemeral, so there is nothing to corrupt.

Even a query that somehow slips past layer 1 can only read the ephemeral
copy of the user's own gold tables — it cannot escape to the filesystem.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Optional, Union

import duckdb

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MODELED_DIR = _PROJECT_ROOT / "data" / "warehouse" / "modeled"
ARTIFACTS_DIR = _PROJECT_ROOT / "artifacts"

BRIDGE_KEY = "spotify_track_id"
DEFAULT_MAX_ROWS = 200

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STATEMENT GUARD (layer 1)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)

# Verbs that mutate state or touch the filesystem/network, plus DuckDB's
# file-reading table functions. Whole-word, case-insensitive. None of these
# occur in a legitimate read query over this schema. K2b additions: pragma_*()
# table functions (the \bPRAGMA\b verb check can't see `pragma_show_tables` —
# the underscore is a word character) and the parquet-introspection family.
_FORBIDDEN = re.compile(
    r"\b("
    r"INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|REPLACE|"
    r"ATTACH|DETACH|COPY|PRAGMA|INSTALL|LOAD|SET|RESET|CALL|"
    r"EXPORT|IMPORT|VACUUM|CHECKPOINT|"
    r"read_parquet|read_csv|read_csv_auto|read_json|read_json_auto|"
    r"read_text|read_blob|parquet_scan|csv_scan|glob|"
    r"pragma_\w+|parquet_metadata|parquet_schema|parquet_file_metadata|"
    r"parquet_kv_metadata|sniff_csv"
    r")\b",
    re.IGNORECASE,
)


def _strip_comments(sql: str) -> str:
    return _LINE_COMMENT.sub(" ", _BLOCK_COMMENT.sub(" ", sql))


def is_safe_sql(sql: str) -> tuple[bool, str]:
    """
    Return (ok, reason). A safe query is a single SELECT/WITH statement with
    no forbidden verbs or file functions.

    Note: comment-stripping is not string-literal-aware, so a `;` or a
    forbidden word inside a quoted literal is treated conservatively (query
    rejected). That's acceptable — the DuckDB sandbox is the real boundary
    and over-rejection is safe.
    """
    if not sql or not sql.strip():
        return False, "Empty query."

    stripped = _strip_comments(sql).strip()
    if not stripped:
        return False, "Query is only comments."

    # Single statement only: allow one optional trailing ';'.
    if stripped.endswith(";"):
        stripped = stripped[:-1].rstrip()
    if ";" in stripped:
        return False, "Only a single statement is allowed (no ';' chaining)."

    first = stripped.split(None, 1)[0].upper() if stripped.split() else ""
    if first not in ("SELECT", "WITH"):
        return False, f"Only SELECT/WITH queries are allowed (got '{first}')."

    m = _FORBIDDEN.search(stripped)
    if m:
        return False, f"Forbidden keyword or function: '{m.group(0)}'."

    return True, "ok"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  WAREHOUSE AGENT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class WarehouseAgent:
    """
    Read-only agent-facing accessor over the gold warehouse.

    Loads every ``*.parquet`` in the modeled dir into a locked-down in-memory
    DuckDB (see module docstring). Construct once; the connection is reused
    across calls. Call :meth:`close` when done (or use as a context manager).
    """

    def __init__(
        self,
        modeled_dir: Optional[Union[str, Path]] = None,
        artifacts_dir: Optional[Union[str, Path]] = None,
        tables: Optional[list[str]] = None,
    ) -> None:
        """``tables`` (K2b) is a hard allowlist of table stems to load — the
        chat engine passes the 5 semantic marts so the two surfaces can share
        this class while seeing different data. None = every parquet in the
        dir (the MCP server's frozen-star-schema behavior, unchanged)."""
        self.modeled_dir = Path(modeled_dir or MODELED_DIR)
        self.artifacts_dir = Path(artifacts_dir or ARTIFACTS_DIR)
        self._allowlist = None if tables is None else set(tables)
        self._tables: list[str] = []
        self._con = self._build_connection()

    # ── setup / teardown ──────────────────────────────────────────────────
    def _build_connection(self) -> duckdb.DuckDBPyConnection:
        if not self.modeled_dir.is_dir():
            raise FileNotFoundError(f"Modeled dir not found: {self.modeled_dir}")
        parquets = sorted(self.modeled_dir.glob("*.parquet"))
        if self._allowlist is not None:
            # allowlisted-but-absent is fine (cluster_profile only exists once
            # a model is trained) — absence shows in the schema, honestly
            parquets = [p for p in parquets if p.stem in self._allowlist]
        if not parquets:
            raise FileNotFoundError(
                f"No gold Parquet tables in {self.modeled_dir} — run the pipeline first.")

        con = duckdb.connect(":memory:")
        for pq in parquets:
            table = pq.stem
            # Native table copy while external access is still permitted.
            con.execute(
                f'CREATE TABLE "{table}" AS SELECT * FROM read_parquet(?)',
                [str(pq)],
            )
            self._tables.append(table)

        # Seal the sandbox: no file/network access, and lock it so a query
        # can never re-enable it.
        con.execute("SET enable_external_access=false")
        con.execute("SET lock_configuration=true")
        logger.info("WarehouseAgent ready: %d tables loaded, sandbox locked.",
                    len(self._tables))
        return con

    def close(self) -> None:
        try:
            self._con.close()
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self) -> "WarehouseAgent":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ── tool 1: schema ────────────────────────────────────────────────────
    def get_schema(self) -> dict:
        """
        Self-describing metadata: every gold table, its columns + DuckDB
        types, agent-readable descriptions (from ``column_descriptions``),
        and row counts. This is what lets an agent write a correct query
        without seeing the data first.
        """
        descriptions = self._column_descriptions()
        tables: dict[str, dict] = {}
        for table in self._tables:
            if table == "column_descriptions":
                continue  # metadata table, not queryable content
            cols = self._con.execute(f'DESCRIBE "{table}"').fetchall()
            n = self._con.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            tables[table] = {
                "row_count": int(n),
                "columns": [
                    {"name": c[0], "type": c[1],
                     "description": descriptions.get(c[0], "")}
                    for c in cols
                ],
            }
        return {
            "bridge_key": BRIDGE_KEY,
            "bridge_key_note": (
                f"'{BRIDGE_KEY}' is the universal join key across all tables. "
                "The fact table's grain is (spotify_track_id, time_range)."
            ),
            "time_ranges": ["short_term (~4 weeks)", "medium_term (~6 months)",
                            "long_term (all time)"],
            "tables": tables,
        }

    def _column_descriptions(self) -> dict[str, str]:
        if "column_descriptions" not in self._tables:
            return {}
        rows = self._con.execute(
            'SELECT column_name, description FROM column_descriptions').fetchall()
        return {r[0]: r[1] for r in rows}

    # ── tool 2: query ─────────────────────────────────────────────────────
    def query_warehouse(self, sql: str, max_rows: int = DEFAULT_MAX_ROWS,
                        timeout_s: Optional[float] = None) -> dict:
        """
        Run a read-only SELECT and return structured rows.

        ``timeout_s`` (K2b) arms an interrupt watchdog: DuckDB has no
        statement-timeout setting (verified 1.5.4), and an LLM can emit a
        `WITH RECURSIVE` that hangs forever past any regex — the watchdog
        calls ``connection.interrupt()``, which stops the query and leaves
        the connection usable.

        Returns a dict: ``{ok, columns, rows, row_count, truncated}`` on
        success, or ``{ok: False, error}`` on a rejected/failed query. Never
        raises for a bad query — agents get a readable error to retry from.
        """
        ok, reason = is_safe_sql(sql)
        if not ok:
            return {"ok": False, "error": f"Query rejected: {reason}"}

        timer: Optional[threading.Timer] = None
        if timeout_s is not None:
            timer = threading.Timer(timeout_s, self._con.interrupt)
            timer.daemon = True
            timer.start()
        try:
            cur = self._con.execute(sql)
            fetched = cur.fetchmany(max_rows + 1)  # +1 sentinel for truncation
            columns = [d[0] for d in cur.description] if cur.description else []
        except duckdb.InterruptException:
            return {"ok": False,
                    "error": f"Query timed out after {timeout_s}s — simplify it."}
        except Exception as exc:  # noqa: BLE001 — surface DB errors to the agent
            return {"ok": False, "error": f"Query failed: {exc}"}
        finally:
            if timer is not None:
                timer.cancel()

        truncated = len(fetched) > max_rows
        rows = [list(r) for r in fetched[:max_rows]]
        return {
            "ok": True,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
        }

    # ── tool 3: insights ──────────────────────────────────────────────────
    def get_insights(self) -> dict:
        """Return the precomputed insights document (SPEC P2, schema v1)."""
        path = self.artifacts_dir / "insights.json"
        if not path.exists():
            return {"ok": False,
                    "error": "insights.json not found — run scripts/build_insights.py."}
        return json.loads(path.read_text(encoding="utf-8"))
