# KB_SPEC — How This Knowledge Base Works

*The design contract for `kb/`: what goes in, how it's formatted, how it
flows to other repos, and how to grow it. Read this before adding or
restructuring anything here.*

**Version:** 2026.07.07 · **Canonical home:** `C:\Users\jverc\language-models\kb\`

---

## 1. The model: hub and spokes

```
                    AUTHOR HERE (canonical)
              language-models/kb/   ← one home per fact
                        │
            uv run kb/_tools/sync_kb.py --to <repo>
                        │
        ┌───────────────┼────────────────────┐
        ▼               ▼                    ▼
 audio-agentic-     wasteland101_4x      <any future repo>
 pipeline/notes/kb/   notes/kb/           notes/kb/
     (READ-ONLY COPIES, stamped with KB_PROVENANCE.md)
```

Three rules make this work:

1. **Author upstream, read downstream.** Cards are edited ONLY here. A
   synced copy is never hand-edited — the next sync overwrites it silently.
   Project-specific knowledge belongs in that project's own `notes/`
   (journal, PROJECT_CONTEXT), not inside its `kb/` copy.
2. **Consumers contribute by proposal.** When a consumer project learns
   something general (e.g. the audio repo's drift-metric lesson), the move
   is: journal it there → distill the *general* part into a card HERE →
   re-sync everywhere. The project journal keeps the story; the KB gets the
   reusable rule.
3. **Every sync is stamped.** `KB_PROVENANCE.md` (written by the sync
   script) records source commit, date, and file list — so a consumer can
   always tell how stale its copy is and where truth lives.

## 2. Directory contract

```
kb/
├── KB_INDEX.md            # map + version + consumption rules (this folder's README)
├── KB_SPEC.md             # ← this file: the design contract
├── weeks/
│   └── COURSE_SUMMARY.md  # per-module key points, tools, techniques (one file per course)
├── techniques/            # the atomic unit: one CARD per reusable technique/lesson
│   └── <kebab-id>.md
├── skills/
│   └── SKILL_PATTERNS.md  # how .claude skills are formatted, composed, and used
├── tools/
│   └── TOOLING.md         # environment/package/tooling matrix
├── templates/             # copy-to-create: week summary, cards, skills
└── _tools/
    └── sync_kb.py         # sync + validate (uv single-file script)
```

Naming: folders are plural nouns; cards are kebab-case matching their `id`;
`_tools/` underscore marks non-content machinery.

## 3. The card format (the atomic unit)

One card = one reusable idea. Frontmatter is the queryable data; the body is
the teaching. Cards must stand alone — a reader in another repo has no
course context.

```markdown
---
id: <kebab-case, unique across kb/, matches filename>
title: <human title>
type: technique | concept | lesson | pattern
origin: "<where it was learned — course week, project, incident>"
tags: [<2-5 lowercase tags for grep/agents>]
use_when: "<one line: the situation that should trigger recalling this card>"
maturity: proven | promising | caution
version_added: <YYYY.MM.DD>
---

# <Title>

**What it is.** <2-4 lines.>

**How to apply.** <Steps or a minimal snippet — enough to act, not a manual.>

**When NOT to use.** <The boundary — every technique has one.>

**Gotchas (earned the hard way).**
- <each one cites its evidence: "(lm eureka #28)", "(audio journal #10)">

**Related:** [<other-card-id>], [<other-card-id>]
```

Rules:
- **`use_when` is the retrieval key.** Write it as the *symptom*, not the
  topic ("output format inconsistent / unparseable", not "JSON").
- **Gotchas require citations** to a journal entry, eureka number, or
  measured result. An uncited gotcha is an opinion — label it `maturity:
  promising` at best.
- **One idea per card.** If a card needs two `use_when` lines, split it.
- Cards are course-agnostic on arrival: strip assignment context, keep the
  transferable rule.

## 4. The ingestion workflow (course → KB)

When a course module (or project milestone) finishes:

1. **Harvest** — sweep the module's notebook, study guide, and the project
   journal for candidates: anything that (a) changed a decision, (b) broke
   an assumption, or (c) you'd want in a NEW project's context. Progress
   notes don't qualify; surprises and reusable rules do.
2. **Summarize** — add/extend the module's section in
   `weeks/COURSE_SUMMARY.md` (template: `templates/TEMPLATE_week_summary.md`):
   key points, tools used, techniques exercised, links to cards.
3. **Card** — for each reusable idea, copy
   `templates/TEMPLATE_technique_card.md`, fill it, save under
   `techniques/`. Update cross-refs both ways.
4. **Validate** — `uv run kb/_tools/sync_kb.py --check` (frontmatter parses,
   ids unique + match filenames, required fields present, index lists every
   card).
5. **Index + version** — add the card lines to `KB_INDEX.md`, bump its
   version (calver `YYYY.MM.DD`).
6. **Sync** — `--to` each consumer repo; commit there ("KB sync <version>").

Same workflow ingests NON-course knowledge (a project incident, a book, a
deep-research dump): only step 2's target changes (a new file under
`weeks/`, e.g. `SOURCE_<name>.md`).

## 5. Skills: how the KB is used interactively

The KB is passive files; skills are what make it interactive
(full patterns: `skills/SKILL_PATTERNS.md`):

- **Orchestrator skills** (`assignment-partner`, `design-partner`,
  `pipeline-partner`) read the project's PROJECT_CONTEXT in Phase 0 — and in
  repos with a synced `notes/kb/`, ALSO check `techniques/` for cards whose
  `use_when` matches today's problem before proposing a design.
- **`kb-sync`** (in this repo) runs the sync/validate script and reports
  what changed per consumer.
- **Audit-style skills** (`kb-audit`, `warehouse-audit`) are the pattern the
  KB itself follows: deterministic script → JSON → LLM formats and flags.

## 6. Versioning & staleness

- `KB_INDEX.md` carries the current calver version; provenance files carry
  what each consumer has. Drift is visible with `--check --from` in a
  consumer (compares provenance to source HEAD).
- Never delete a card silently: mark `maturity: caution` with a note, or
  fold it into its replacement and leave the old id as a one-line tombstone
  pointing forward. Consumers may hold references to old ids.

## 7. Creating a template from all this (new-project bootstrap)

The reusable skeleton for ANY new project =

1. **This KB, synced** (`notes/kb/`) — the knowledge.
2. **The harness pattern** — CLAUDE.md bootloader + `notes/PROJECT_CONTEXT.md`
   + journal + roadmap (templates in `claude-repo-playbook/02`, checklist in
   `08-new-project-checklist.md`).
3. **Skills instantiated from `templates/TEMPLATE_SKILL_*.md`** — rename the
   orchestrator for the domain (design-/pipeline-/x-partner), point its
   Phase 0 at the project's context file, give the audit worker a
   domain-specific script.

That triple (knowledge + memory + skills) is what was hand-built for
wasteland101 and audio-agentic-pipeline; with this KB it becomes: sync,
copy templates, fill in the domain.
