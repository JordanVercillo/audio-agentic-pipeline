"""
mcp_server.py — MCP server exposing the gold warehouse to agents (SPEC P5)
===========================================================================
A thin FastMCP (stdio) wrapper around ``WarehouseAgent`` (the tested core in
``warehouse_agent.py``). Registers three read-only tools so any MCP client —
Claude Desktop, Claude Code — can explore Jordan's music-taste warehouse.

Run directly:
    python -m src.agent.mcp_server

Register in Claude Desktop / Code (see docs/AGENT_ACCESS.md):
    {
      "mcpServers": {
        "vercillo-warehouse": {
          "command": "C:/Users/jverc/anaconda3/python.exe",
          "args": ["-m", "src.agent.mcp_server"],
          "cwd": "C:/Users/jverc/audio-agentic-pipeline"
        }
      }
    }

The heavy lifting (DuckDB sandbox, SQL guard, schema introspection) lives in
the core; this file only maps methods to MCP tools and owns process lifetime.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Allow `python -m src.agent.mcp_server` and `python src/agent/mcp_server.py`.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from src.agent.warehouse_agent import WarehouseAgent  # noqa: E402

# MCP servers speak JSON-RPC on stdout — logs MUST go to stderr only.
logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format="%(levelname)-7s %(name)s — %(message)s")
logger = logging.getLogger("vercillo-warehouse-mcp")

mcp = FastMCP("vercillo-warehouse")

_agent: WarehouseAgent | None = None


def _get_agent() -> WarehouseAgent:
    """Lazy singleton so a missing warehouse becomes a clean per-tool error
    instead of crashing the server at registration time."""
    global _agent
    if _agent is None:
        _agent = WarehouseAgent()
    return _agent


@mcp.tool()
def get_schema() -> dict:
    """Describe the music-taste warehouse: every table, its columns with
    types and plain-English descriptions, row counts, and the join key.

    CALL THIS FIRST, before writing any SQL — it tells you exactly which
    tables and columns exist (e.g. fact_listening_features holds the 77-dim
    acoustic features per track × time_range; dim_artists holds genres;
    cluster_assignments holds the taste-map clusters) so your query_warehouse
    calls are correct on the first try.
    """
    try:
        return _get_agent().get_schema()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


@mcp.tool()
def query_warehouse(sql: str, max_rows: int = 200) -> dict:
    """Run a READ-ONLY SQL SELECT against the gold warehouse and get rows back.

    Use this to answer specific questions about the listener's taste —
    highest-energy track per time range, genre distribution, tracks that
    persist across all three time windows, acoustic averages, etc. Call
    get_schema() first so you use real table and column names.

    Only a single SELECT/WITH statement is allowed; writes, DDL, file access,
    and multiple statements are rejected. Returns {ok, columns, rows,
    row_count, truncated}; on a bad query, {ok: False, error} with a readable
    reason so you can fix and retry.
    """
    return _get_agent().query_warehouse(sql, max_rows=max_rows)


@mcp.tool()
def get_insights() -> dict:
    """Return the precomputed taste-insights document (drift score, cluster
    summaries, persistent favorites, superlatives, genre profile).

    Prefer this over ad-hoc SQL for high-level "what's my taste like / how
    has it drifted" questions — it's the same deterministic analysis behind
    the portfolio report, already computed. Drop to query_warehouse() only
    when you need something the insights don't already contain.
    """
    try:
        return _get_agent().get_insights()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def main() -> None:
    logger.info("Starting vercillo-warehouse MCP server (stdio)…")
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
