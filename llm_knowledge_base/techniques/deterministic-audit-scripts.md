---
id: deterministic-audit-scripts
title: Deterministic audit scripts (facts by code, judgment by LLM)
type: pattern
origin: "harness pattern — lm build-student-context; wasteland kb-audit; audio warehouse-audit"
tags: [harness, skills, data-quality, automation]
use_when: "an agent (or human) keeps re-checking repo/data state by eyeball, or 'is X healthy?' recurs"
maturity: proven
version_added: 2026.07.07
---

# Deterministic audit scripts

**What it is.** The load-bearing harness pattern: a single-file script
gathers FACTS (state, counts, violations) and emits JSON; a thin skill has
the LLM format it and branch on flags. Anything checkable is checked by
code, not vibes — the LLM never "looks around and estimates."

**How to apply.**
1. Write one script per domain: `audit_<domain>.py`, uv single-file with a
   PEP 723 header (`# /// script … dependencies=[…]`) so it runs via
   `uv run` with NO project env, venv, or pyproject.
2. Output one JSON object: inventory, `errors` (block work), `warnings`
   (note and continue), boolean `flags` (branch points). Exit 0 even with
   findings — the report IS the result; exit 1 only if the audit itself
   can't run.
3. Degrade gracefully: absent data is a FLAG (`NO_WAREHOUSE`,
   `NO_CONTENT_YET`), not a crash.
4. Pair it with a worker skill whose SKILL.md fixes the report format
   exactly, and whose orchestrator calls it at session start and after
   every relevant change.
5. Same pattern brackets LLM *generation*: script-collect before, script-
   validate after, loop until valid (lm `generate-spec` + `validate_spec.py`).

**When NOT to use.** One-off questions — just look. The script earns its
keep on the third repetition.

**Gotchas (earned the hard way).**
- Check the CAPABILITY, not the binary: `ffmpeg -version` passed while the
  build lacked libmp3lame and 9/9 downloads failed (audio journal #7).
- A contract is a column LIST, not a count — two docs agreed on "77
  features" while disagreeing on members; only the audit's exact-list check
  caught it (audio journal #8).
- Verify entry points first — docs' run commands can be fiction while the
  modules underneath are real (audio journal #6).
- Existence checks test the proof-file, not the folder (lm #24).

**Related:** [structured-output-json], [gold-eval-sets]
