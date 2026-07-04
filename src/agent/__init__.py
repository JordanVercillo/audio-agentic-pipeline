"""
src.agent — Agent Access Layer (SPEC P5)
=========================================
Exposes the gold warehouse to AI agents through three read-only tools:

    get_schema()          → self-describing table/column metadata
    query_warehouse(sql)  → SELECT-only DuckDB over the gold Parquet
    get_insights()        → the precomputed insights.json (schema v1)

``WarehouseAgent`` is the pure, dependency-light retrieval core (DuckDB +
pandas only) — unit-tested against a synthetic warehouse and reused by both
the MCP server (`mcp_server.py`) and, later, P8's RAG layer. The MCP runtime
is NOT imported here, so tests never need it.
"""

from .warehouse_agent import WarehouseAgent, is_safe_sql

__all__ = ["WarehouseAgent", "is_safe_sql"]
