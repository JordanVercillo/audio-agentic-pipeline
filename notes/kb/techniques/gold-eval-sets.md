---
id: gold-eval-sets
title: Gold eval sets & honest baselines
type: technique
origin: "language-models course, weeks 4–5 v2; reused in wasteland sim + audio audits"
tags: [evaluation, data-quality, methodology]
use_when: "you can't tell if a change helped; claims lack numbers; 'it improved' with no table"
maturity: proven
version_added: 2026.07.07
---

# Gold eval sets & honest baselines

**What it is.** A fixed, versioned, human-verified set of labeled examples
that every change is measured against, before/after. The measurement
instrument for the whole project — and the FIRST thing to fix when results
can't be trusted.

**How to apply.**
1. Start small (n≈15–20) but label it provisional; expanding it is a
   roadmap item, not an afterthought (each row of n=15 is 6.7% of your score).
2. Scale via teacher-propose → **human-verify** (see
   [teacher-student-distillation]); one-line rationale per corrected row.
3. Report accuracy NEXT TO the majority-class baseline — 67% on a
   67%-skewed set is zero skill (lm #19b). Below-majority = actively worse
   than a constant.
4. Disaggregate per dimension/category; a composite hides one dimension
   regressing inside a "net win" (lm #14, #28).
5. Version the file (`_v2`); never overwrite — old results cite it.
6. Leakage-guard every path into training data, by id AND by name (lm #27).
7. Gold labels must be values the system can actually output (lm #22);
   ground subjective labels in observable features, not reputations (lm #23).

**When NOT to use.** Don't block week-one exploration on a perfect set —
but don't call anything a result until the set exists.

**Gotchas (earned the hard way).**
- If every row gives the same answer, suspect the harness before the
  model — a decode bug once matched the prompt's own text (lm #23-wk5).
- Sanity-anchor metrics at BOTH ends: a known-zero corpus and a known-large
  one; an instrument that has only seen one dataset is fitted, not
  calibrated (audio journal #10).
- First full run's real job is finding the rule that contradicts the
  design's own story — usually exactly one (wasteland journal #9).

**Related:** [teacher-student-distillation], [deterministic-audit-scripts],
[embeddings-and-similarity-metrics]
