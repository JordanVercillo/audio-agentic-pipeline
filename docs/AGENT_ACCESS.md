# Agent Access Layer — an MCP server over the music-taste warehouse

**SPEC P5.** This is the Spotify Data Engineer – Platform posting's differentiating
bullet made concrete — *"systems that enable AI agents to effectively interact
with and leverage data infrastructure."* The gold warehouse was designed for
agent consumption (denormalized fact table, `column_descriptions`); this layer
exposes it to any [MCP](https://modelcontextprotocol.io) client — Claude
Desktop, Claude Code — as three read-only tools.

The same retrieval core (`src/agent/warehouse_agent.py`) is reused by the P8
production-pilot RAG layer — P5 builds it locally, P8 productizes it behind the
web.

## The three tools

| Tool | What it does | When the agent uses it |
|---|---|---|
| `get_schema()` | Every gold table, its columns + types + plain-English descriptions, row counts, and the join key. | First — so its SQL uses real table/column names. |
| `query_warehouse(sql, max_rows=200)` | Runs a **read-only** SELECT and returns `{ok, columns, rows, row_count, truncated}`. | Specific questions: superlatives, distributions, persistence, acoustic averages. |
| `get_insights()` | The precomputed insight document (drift score, clusters, favorites, superlatives, genres — SPEC P2, schema v1). | High-level "what's my taste like / how has it drifted". |

## Security — two independent layers

Querying a warehouse from an agent means executing model-generated SQL, so the
design assumes the SQL is untrusted (this matters doubly for P8, where a *web
visitor's* session drives it).

1. **Statement guard** (`is_safe_sql`) — the query must be a *single* statement
   beginning with `SELECT`/`WITH`, with no mutating verbs, no multiple
   statements, and no file-reading table functions. Gives clear errors and
   states the read-only contract.
2. **DuckDB sandbox** (the hard boundary) — the gold Parquet is copied into
   **native in-memory tables**, then `enable_external_access=false` +
   `lock_configuration=true` are set. After that the connection *cannot* read
   or write any file, reach the network, install extensions, attach databases,
   or re-enable any of the above — and the DB is ephemeral, so there is nothing
   to corrupt. A denylist can never enumerate every dangerous DuckDB function;
   the security comes from **removing the capability**, not pattern-matching.
   The guard is defense-in-depth on top.

Both layers are unit-tested (`src/agent/test_agent.py`), including a test that
bypasses the guard and confirms the sandbox still refuses file access.

## Register it

**Claude Desktop** — add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "vercillo-warehouse": {
      "command": "C:/Users/jverc/anaconda3/python.exe",
      "args": ["-m", "src.agent.mcp_server"],
      "cwd": "C:/Users/jverc/audio-agentic-pipeline"
    }
  }
}
```

**Claude Code** — `claude mcp add vercillo-warehouse -- C:/Users/jverc/anaconda3/python.exe -m src.agent.mcp_server`
(run from the repo root), or add the same block to `.mcp.json`.

Run standalone (stdio) for debugging: `python -m src.agent.mcp_server`.

## Demo transcript

Verified against the live 117-track warehouse (`src/agent/warehouse_agent.py`
called directly; the MCP path returns identical results):

```
Q: What tables can I query?
→ get_schema() → fact_listening_features, dim_tracks, dim_artists,
  dim_time_range, cluster_assignments  (+ per-column descriptions)

Q: What's my highest-energy track in each time range?
→ query_warehouse("SELECT time_range, track_name, primary_artist_name,
     round(rms_mean,3) energy FROM fact_listening_features f WHERE rms_mean =
     (SELECT max(rms_mean) FROM fact_listening_features g
      WHERE g.time_range=f.time_range) ORDER BY time_range")
   long_term    Be With You            — Muse          0.291
   medium_term  Diamond on a Landmine  — Billy Talent  0.289
   short_term   Cut Back               — Marmozets     0.305

Q: Which genres dominate my taste map?
→ query_warehouse("SELECT genre_bucket, count(*) n FROM cluster_assignments
     GROUP BY 1 ORDER BY n DESC")
   Indie & Alt 35 · Punk & Emo 25 · Metal 6 · Blues 4 · Rock 2  (Unknown 36)

Q: Which tracks have I loved across all three time windows?
→ query_warehouse("SELECT track_name, primary_artist_name,
     count(DISTINCT time_range) r FROM fact_listening_features
     GROUP BY 1,2 HAVING r=3")
   Be With You · Cryogen · Hush · Nightshift Superstar (Muse) ·
   One By One (The Blue Stones) · …

Q: How much has my taste drifted?
→ get_insights() → drift 0.1405σ — "Minimal Drift — remarkably stable"

Q: [adversarial] SELECT * FROM read_csv('C:/Windows/win.ini')
→ Query rejected: Forbidden keyword or function: 'read_csv'.
```

## Files

- `src/agent/warehouse_agent.py` — the tested retrieval core (DuckDB + guard).
- `src/agent/mcp_server.py` — thin FastMCP (stdio) wrapper.
- `src/agent/test_agent.py` — 30 tests (guard matrix, sandbox, three tools).
