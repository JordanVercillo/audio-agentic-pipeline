---
id: teacher-student-distillation
title: Teacher–student distillation (with the load-bearing verify pass)
type: technique
origin: "language-models weeks 4–6"
tags: [llm, labeling, data-generation, bias]
use_when: "you need labels/enrichment at scale and have a big model + a small model"
maturity: proven
version_added: 2026.07.07
---

# Teacher–student distillation

**What it is.** A larger model (teacher) proposes labels, enrichment, or
training examples at scale; outputs are cached; a human verifies; the small
model (student) trains or evaluates against the result.

**How to apply.**
1. Stratify what the teacher labels (cover the classes you care about).
2. Cache every teacher output — never re-pay for the same call.
3. **Human-verify before anything downstream consumes it.** Spot-verify at
   minimum (trust 8/10 random samples or don't use the batch).
4. Use `format="json"` + fence-stripping on teacher calls (see
   [structured-output-json]).
5. Record one-line rationales for human corrections — they become the
   rubric for the next batch.

**When NOT to use.** When the teacher shares the student's failure mode —
a same-family teacher labeled **0 of 51** examples with the class being
fixed (lm eureka #25, #29). You cannot distill a correction out of a model
with the same blind spot: hand-author the hard/rare cells, use the teacher
only where it's already right.

**Gotchas (earned the hard way).**
- Rare classes that won't fill are a data truth, not a script bug — author
  them, don't fake or over-sample them (lm #26).
- The verify pass is where the eval EARNS trust; skipping it would have
  shipped a broken measurement axis (lm #29).
- Vendor metadata can be too sparse to be a teacher at all — the audio
  project's genre tags couldn't even name clusters; its own measured
  features could (audio journal #9).

**Related:** [gold-eval-sets], [finetuning-data-design], [structured-output-json]
