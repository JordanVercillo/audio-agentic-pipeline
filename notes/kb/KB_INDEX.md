# Knowledge Base — Index

**Version:** 2026.07.07 · **Canonical home:** `language-models/kb/` ·
**Contract:** [KB_SPEC.md](KB_SPEC.md) (read it before editing anything here)

Portable, versioned knowledge distilled from the *Foundations of Language
Models* course and the projects built with it. Authored HERE; synced
read-only into consumer repos at `notes/kb/` via:

```bash
uv run kb/_tools/sync_kb.py --to <consumer-repo-path>   # push a copy
uv run kb/_tools/sync_kb.py --check                     # validate cards + index
```

If you are reading a synced copy: **don't edit it** — see `KB_PROVENANCE.md`
beside this file for the source; propose changes there.

## Contents

| Path | What it holds |
|---|---|
| `weeks/COURSE_SUMMARY.md` | The 8 course modules: key points, tools used, techniques exercised, hard-won lessons |
| `techniques/` | Atomic cards — one reusable technique/lesson each (below) |
| `skills/SKILL_PATTERNS.md` | How `.claude` skills are formatted, composed, and used to work a repo interactively |
| `tools/TOOLING.md` | Environment & package matrix: uv, Ollama model roles, stacks per capability |
| `templates/` | Copy-to-create: week/module summary, technique card, orchestrator + worker skills |
| `_tools/sync_kb.py` | Sync + validation machinery |

## Technique cards

| Card | `use_when` |
|---|---|
| [structured-output-json](techniques/structured-output-json.md) | LLM output is inconsistent/unparseable, or pipeline stages need a contract |
| [gold-eval-sets](techniques/gold-eval-sets.md) | You can't tell if a change helped; claims lack numbers |
| [embeddings-and-similarity-metrics](techniques/embeddings-and-similarity-metrics.md) | Similarity/drift scores look wrong, flatlined, or too clean |
| [teacher-student-distillation](techniques/teacher-student-distillation.md) | You need labels/enrichment at scale with one big + one small model |
| [rag-and-retrieval](techniques/rag-and-retrieval.md) | Context is hardcoded/missing/too big to inline per query |
| [finetuning-data-design](techniques/finetuning-data-design.md) | Prompting plateaued; an adapter helps or HURTS depending on data |
| [deterministic-audit-scripts](techniques/deterministic-audit-scripts.md) | An agent (or human) keeps re-checking repo/data state by eyeball |

## Consumers

| Repo | Synced to | Since |
|---|---|---|
| `audio-agentic-pipeline` | `notes/kb/` | 2026.07.07 |
| `wasteland101_4x` | *(not yet — sync when a design session needs it)* | — |
