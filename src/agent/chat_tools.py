"""
chat_tools.py — the K2b engine: read-only SQL over the SEMANTIC marts for the
/chat tool loop (D-49). Wraps :class:`WarehouseAgent` (same two-layer security:
statement guard + sealed in-memory sandbox) pointed at ``data/marts`` with a
hard table allowlist — the MCP server stays on the frozen star schema,
untouched, and the chat never sees a non-semantic mart.

Postures that are the point:
  - PER-SESSION construction, never a singleton: the marts are copied into
    memory at construction, so a long-lived instance freezes at yesterday's
    corpus AND holds nothing open (the worker's atomic os.replace mart rebuild
    keeps working on Windows — proven by test).
  - ``MAX_ROWS`` is clamped HERE, server-side — never trusted from the model.
  - Every query runs under an interrupt watchdog (DuckDB has no
    statement-timeout setting — verified 1.5.4; an LLM can emit a
    ``WITH RECURSIVE`` that no regex catches).
  - The schema card is PINNED prose assembled from the tables actually loaded
    (schema discovery would spend a precious depth turn; absence — e.g. no
    cluster_profile before a model is trained — shows up honestly as absence).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Union

from .warehouse_agent import WarehouseAgent

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MARTS_DIR = _PROJECT_ROOT / "data" / "marts"

# The chat's whole queryable world — the D-49 semantic layer, nothing else.
CHAT_TABLES = ("feature_dictionary", "track_card", "artist_rollup",
               "corpus_facts", "cluster_profile")
MAX_ROWS = 20          # render clamp — the model's requested LIMIT is irrelevant
QUERY_TIMEOUT_S = 5.0

# Pinned one-line analyst notes per table (the ~350-token card, with columns
# appended from the live DESCRIBE at construction — names/types can't drift).
_TABLE_NOTES = {
    "feature_dictionary": "what every feature column means, its unit/tier, and "
                          "the caveats you must repeat (one row per feature)",
    "track_card": "one row per track in the listener's library — features, "
                  "percentile ranks, name/artist, popularity; filter "
                  "feature_valid = TRUE for any superlative",
    "artist_rollup": "one row per artist — n_tracks, n_analyzed, genres, "
                     "mean_energy/mean_tempo; match names with "
                     "artist_name ILIKE '%…%'",
    "corpus_facts": "one row of library totals — track/artist counts, hours, "
                    "duration and tempo medians",
    "cluster_profile": "one row per sound cluster — label, n_assigned, "
                       "share_of_corpus (clusters cover only the assigned "
                       "share, say so), acoustic means",
}


class ChatDataTools:
    """The /chat loop's only data access. Construct per request/turn, close
    when done (or use as a context manager)."""

    def __init__(self, marts_dir: Optional[Union[str, Path]] = None,
                 timeout_s: float = QUERY_TIMEOUT_S) -> None:
        self.timeout_s = timeout_s
        self._agent = WarehouseAgent(modeled_dir=marts_dir or MARTS_DIR,
                                     tables=list(CHAT_TABLES))

    # ── lifecycle ────────────────────────────────────────────────────────────
    def close(self) -> None:
        self._agent.close()

    def __enter__(self) -> "ChatDataTools":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ── the pinned schema card ───────────────────────────────────────────────
    def schema_card(self) -> str:
        """One line per LOADED table: pinned analyst note + live columns."""
        lines = []
        for table in self._agent._tables:
            cols = self._agent._con.execute(f'DESCRIBE "{table}"').fetchall()
            col_s = ", ".join(f"{c[0]} {c[1]}" for c in cols)
            lines.append(f"- {table} ({_TABLE_NOTES.get(table, '')}): {col_s}")
        return "\n".join(lines)

    # ── query + render ───────────────────────────────────────────────────────
    def run_query(self, sql: str) -> dict[str, Any]:
        """Guarded, clamped, watchdogged. The clamp and timeout are THIS
        layer's numbers — nothing the model wrote is trusted."""
        return self._agent.query_warehouse(sql, max_rows=MAX_ROWS,
                                           timeout_s=self.timeout_s)

    @staticmethod
    def render_result(result: dict[str, Any]) -> str:
        """The compact text block the model reads back (and ChatLog stores).
        Errors render as retryable feedback; floats are trimmed for tokens
        (and so answers don't parrot 273.033701-style noise)."""
        if not result.get("ok"):
            return f"SQL ERROR: {result.get('error', 'unknown error')}"
        cols = result.get("columns") or []
        rows = result.get("rows") or []
        head = f"RESULT: {len(rows)} row(s)"
        if result.get("truncated"):
            head += f" (truncated to the first {MAX_ROWS})"
        if not rows:
            return head
        def _cell(v: Any) -> str:
            if v is None:
                return "NULL"
            if isinstance(v, float):
                return f"{v:.3f}".rstrip("0").rstrip(".")
            return str(v)
        body = [" | ".join(cols)]
        body += [" | ".join(_cell(v) for v in r) for r in rows]
        return head + "\n" + "\n".join(body)
