---
id: finetuning-data-design
title: Fine-tuning is data design (LoRA/QLoRA)
type: technique
origin: "language-models week 5 + week 5 v2"
tags: [finetuning, lora, training-data, distributions]
use_when: "prompting plateaued below the bar on specific dimensions; or an adapter made things WORSE"
maturity: proven
version_added: 2026.07.07
---

# Fine-tuning is data design

**What it is.** LoRA/QLoRA trains ~1% of parameters beside a frozen
(4-bit) base — feasible on a 12 GB consumer GPU for 2B models. The
technique is commodity; **the dataset is the product**: the same recipe
swung from −19 to +24 points on data design alone (lm eureka #22).

**How to apply.**
1. Escalate only per-dimension, only after the eval proves a plateau
   (below majority baseline after real prompt iteration — lm week 4).
2. Pick the motive: efficiency (internalize a verbose prompt) or accuracy
   (teach hard cases). Different datasets.
3. The 5-question framework: one behavior in scope · training format ==
   inference format EXACTLY · named source of truth · coverage of every
   class · trust 8/10 random samples or don't train.
4. **Reasoning-first examples** (rationale before label) beat bare labels.
5. **Match the label marginals to the deployment/eval distribution** — the
   distribution you train on is a hyperparameter; a "regression" dissolved
   when marginals were matched, nothing else changed (lm #28, #30).
6. **Fill coverage separately** — zero-example classes get quietly
   forgotten; coverage and marginals are different knobs (lm #31).
7. Hand-author rare/corrective cells; the teacher can't (see
   [teacher-student-distillation]).
8. Version adapters (`_v1_backup`, `_v2_backup`) — rollback is a rename.

**When NOT to use.** Before measuring the prompt ceiling; to fix a problem
that's actually retrieval/input-representation; for knowledge that changes
often (that's RAG's job).

**Gotchas (earned the hard way).**
- Leakage guards must cover EVERY path in — by id AND by name; hand-written
  anchors bypassed the id filter (lm #27).
- Decode only generated tokens (`outputs[0][input_len:]`) — full-sequence
  decoding let the prompt's own text match the answer regex, faking a
  clean-looking table (lm #23).
- `os.path.exists(dir)` is not "the artifact exists" — check for
  `adapter_config.json`, not the folder a crashed run left (lm #24).
- Wrappers (Unsloth) are the same method, faster engine — swap freely when
  the OS demands it (lm #21, `notes/methodology_peft_vs_unsloth.md`).

**Related:** [gold-eval-sets], [teacher-student-distillation]
