---
name: <domain>-audit
description: Internal skill — deterministic <domain> audit. Called by <domain>-partner at session start and after any <relevant change>; also usable directly when <owner> asks to "audit the <domain>" or "is <X> healthy".
user-invocable: true
allowed-tools: [Bash, Read]
---

You are an audit agent. Run the validator, then report — no design opinions.

## Steps

1. From the repo root run:

   ```bash
   uv run .claude/skills/<domain>-audit/audit_<domain>.py
   ```

2. Parse the JSON output and return exactly this block:

   ```
   === <DOMAIN> AUDIT ===
   <Inventory line: counts of the units that matter>
   Errors:   <one line each, or "none">
   Warnings: <one line each, or "none">
   Flags: <true flags with [WARNING], or "Normal">
   ```

3. Flag meanings:
   - `<NO_DATA_FLAG>` — nothing to audit yet (informational, but blocks
     downstream work — say which)
   - `<INTEGRITY_FLAG>` [WARNING] — <what broke and what it blocks>
   - <one line per flag the script can emit>

If the script itself errors, report the raw error and stop — do not guess.
Return only the formatted block, no commentary.

<!-- The paired script (audit_<domain>.py) follows the pattern card
     kb/techniques/deterministic-audit-scripts.md:
     PEP 723 header · facts→JSON · errors/warnings/flags · exit 0 with
     findings · graceful when data is absent. -->
