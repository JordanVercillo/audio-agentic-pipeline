---
id: embeddings-and-similarity-metrics
title: Embeddings & similarity metrics — what they actually measure
type: concept
origin: "language-models week 2; audio-agentic-pipeline drift analysis"
tags: [embeddings, metrics, vectors, drift]
use_when: "similarity/drift scores look wrong, flatlined, pegged, or suspiciously clean"
maturity: proven
version_added: 2026.07.07
---

# Embeddings & similarity metrics — what they actually measure

**What it is.** Embeddings place text in a space where distance ≈
meaning-as-written-in-training-text. A similarity/drift metric on top of
any vectors is a CLAIM about which differences matter. Most failures are a
mismatch between that claim and the question asked.

**How to apply.**
- Use a dedicated embedder (MiniLM/mpnet class), not a generative model as
  embedder — measured worse gaps (lm week 2).
- Evaluate embedders by the **gap between close-pair and far-pair means**,
  never absolute values (lm #13) — and per category, because the overall
  mean hides a passing category and a failing one (lm #14).
- Isolate variables: hold the item constant, flip one word (lm #15).
- Heterogeneous-scale features (tempo 60–200 vs RMS 0–1): standardize
  FIRST, then measure. Scale-invariance belongs in preprocessing, not the
  metric (audio journal #10, amending naive "just use cosine").

**When NOT to use.** Embeddings don't know your labels (lm #10), can't
count or compare numbers (lm #11), and can't do exact filters ("Mod ≥ +2")
— structured data wants structured storage (wasteland journal #3).

**Gotchas (earned the hard way).**
- Similarity is of the WORDS IN THE STRING: two Italian pastas sharing only
  "with" scored as unrelated; the fix was richer input (prepend category,
  append ingredients), not a bigger model (lm #16, #17).
- Domain words may fragment at the tokenizer — check survival first (lm #12).
- Cosine on raw centroids = pinned by the largest-magnitude features
  (drift flatlined at 0.0000); cosine on z-scored group centroids =
  geometry forces ~120° angles (pegged at 1.4998). If the question is
  magnitude, measure magnitude: RMS σ-shift between standardized centroids
  (audio journal #10 — both failures were direction-vs-magnitude confusion).

**Related:** [rag-and-retrieval], [gold-eval-sets]
