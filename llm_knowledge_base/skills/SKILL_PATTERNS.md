# Skill Patterns — how `.claude` skills are formatted, composed, and used

*The interactive layer of every harnessed repo. A skill is a markdown file
that packages a repeatable workflow so Claude runs it consistently on
demand. This doc: the file format, the seven design patterns, the live
inventory across Jordan's repos, and how sessions actually use them.*

## 1. Anatomy of a SKILL.md

Location: `<repo>/.claude/skills/<skill-name>/SKILL.md` (+ optional helper
scripts and a `references/` folder beside it). **Skills only load when the
repo folder itself is the project root** — the #1 "unknown command" cause.

```markdown
---
name: <kebab-name>                     # what you type: /<name>
description: <one sentence>. TRIGGER when: <concrete user phrasings>.
  SKIP if: <the adjacent-but-wrong case, and which skill handles it>.
user-invocable: true                   # or "Internal skill — use ONLY when called by X"
allowed-tools: [Glob, Grep, Read, Skill, Edit, Write, Bash]   # least privilege
---

<The workflow, written as instructions to Claude — numbered phases,
exact commands in fenced blocks, report formats spelled out verbatim.>
```

The `description` is the routing layer: TRIGGER phrases make it fire at the
right moment; the SKIP clause routes adjacent traffic to the right sibling
(design questions ≠ env triage ≠ data audit). Adjacent skills that don't
disambiguate each other misfire on each other's traffic.

## 2. The seven patterns

1. **Orchestrator + internal workers.** One user-facing skill runs phases
   and delegates mechanical steps to internal skills that return
   structured blocks (not prose) with state FLAGS the orchestrator
   branches on.
2. **The Phase 0/5 memory sandwich.** Every orchestrator BEGINS by reading
   the project's PROJECT_CONTEXT and ENDS by updating it (status, next
   action, session log, journal). This wires the living-memory system into
   the workflow so it maintains itself.
3. **Determinism in scripts, judgment in prompts.** Facts come from a
   script (JSON out); the LLM formats, flags, decides. Generation gets
   bracketed: script-collect before, script-validate after, loop until
   valid. (Card: [deterministic-audit-scripts].)
4. **Progressive disclosure.** SKILL.md stays lean; bulky detail lives in
   `references/` files read only when needed.
5. **Draft/lock separation.** Content-authoring skills write `status:
   draft` and present for review; only the human flips to locked/approved.
   Spec-scale changes get a written SPEC with exit criteria before
   implementation.
6. **Runbooks with error playbooks.** Ops skills: silent pass-through on
   the happy path, lettered recovery options per failure, a symptom→fix
   table, secrets referenced by NAME only.
7. **Same-turn continuation.** Skills state explicitly: never end the turn
   on a bare audit/orientation report, and don't re-confirm a goal the
   invocation already stated. (Learned live: the first design-partner run
   "stalled" after its audit until this line was added.)

## 3. Live inventory (what exists, what each does)

| Repo | Skill | Role |
|---|---|---|
| language-models | `assignment-partner` | Course-week orchestrator: recall → scan → interview → spec → update context |
| | `build-student-context` / `generate-spec` | Internal workers: scripted repo scan; YAML spec with validation loop |
| | `setup-debugger` / `sync-course-material` / `host-streamlit` | Env triage runbook; upstream-sync runbook; deploy recipe |
| | `kb-sync` | Validate + push THIS knowledge base to consumer repos |
| wasteland101_4x | `design-partner` | Senior design-partner orchestrator (pillars, anti-fabrication, SPEC gate) |
| | `kb-audit` (+`audit_kb.py`) | Deterministic game-KB validator: schemas, ids, censuses |
| | `card-author` / `balance-sim` / `unity-verify` | Draft-only content batches; sim method (baselines, one-knob); headless Unity checks |
| audio-agentic-pipeline | `pipeline-partner` | Senior DE-partner orchestrator (portfolio lens, measure-before-claiming) |
| | `warehouse-audit` (+`audit_warehouse.py`) | Medallion data-quality validator: bridge key, joins, feature contract |
| | `env-verify` | Env/capability triage (deps, ffmpeg *capability*, creds by name, pytest) |

## 4. How sessions use them (the interaction model)

```
1. Open the repo folder as project root  → CLAUDE.md bootloader auto-loads
2. /<orchestrator>  +  one-line session goal (+ any scope limit)
3. Phase 0 reads PROJECT_CONTEXT → Phase 1 runs the audit worker
4. Work happens in reviewable slices; audits/tests after each
5. Phase 5 writes the memory back — next session starts warm
```

The prompt stays tiny BY DESIGN: the repo carries the context. If a session
needs a long opening prompt, the context file is missing something — add it
there once. Utility invocations (`/kb-audit`, `/warehouse-audit`,
`/env-verify`) work standalone anytime; "continue with the session goal"
un-sticks a turn that stopped early.

## 5. Instantiating skills for a new repo

Copy `../templates/TEMPLATE_SKILL_orchestrator.md` and
`TEMPLATE_SKILL_worker.md`; rename for the domain (`<x>-partner`,
`<x>-audit`); point Phase 0 at the project's context file; write the
domain's audit script from the pattern card. Full worked examples: the
three repos above. Plus `.claude/settings.json`:
`{"permissions": {"allow": ["Skill", "Bash(uv run:*)"]}}`.
