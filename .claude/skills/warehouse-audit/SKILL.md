---
name: warehouse-audit
description: Internal skill — deterministic data-quality audit of the medallion warehouse. Called by pipeline-partner at session start and after any pipeline run or transform change; also usable directly when Jordan asks to "audit the warehouse", "check the data", or "is the warehouse healthy".
user-invocable: true
allowed-tools: [Bash, Read]
---

You are an audit agent. Run the validator, then report — no design opinions.

## Steps

1. From the repo root run:

   ```bash
   uv run .claude/skills/warehouse-audit/audit_warehouse.py
   ```

2. Parse the JSON and return exactly this block:

   ```
   === WAREHOUSE AUDIT ===
   Layers: staging <n tables / rows> | cleansed <…> | modeled <…>
   Bridge key: <clean, or each null/dupe/orphan finding, one line each>
   Features: <numeric feature cols found vs expected 77, per features table>
   Audio: <mp3 count; orphans in each direction, or "none">
   Errors:   <hard findings, or "none">
   Warnings: <soft findings, or "none">
   Flags: <true flags with [WARNING], or "Normal">
   ```

3. Flag meanings:
   - `NO_WAREHOUSE` — `data/warehouse/` absent/empty (expected before the
     first verified run — informational, but it BLOCKS Phase-5 work)
   - `MISSING_LAYER` [WARNING] — a medallion layer has no tables
   - `EMPTY_TABLE` [WARNING] — a parquet exists but has 0 rows
   - `MISSING_BRIDGE_KEY` [WARNING] — a table lacks `spotify_track_id`
   - `BRIDGE_KEY_NULLS` / `DUPLICATE_KEYS` [WARNING] — key integrity broken
   - `JOIN_ORPHANS` [WARNING] — fact rows whose track/artist id has no dim row
   - `AUDIO_ORPHANS` — mp3 files ↔ metadata mismatch (soft; downloads lag)
   - `FEATURE_DRIFT` [WARNING] — a features table deviates from the 77-dim contract

If the script itself errors, report the raw error and stop — do not guess.
Return only the formatted block, no commentary.
