---
id: rag-and-retrieval
title: RAG & retrieval — target choice decides everything
type: technique
origin: "language-models weeks 3, 4, 6"
tags: [rag, vector-store, context, chromadb]
use_when: "context is hardcoded, missing, per-user/per-query, or too big to inline"
maturity: proven
version_added: 2026.07.07
---

# RAG & retrieval

**What it is.** Embed a knowledge base; at query time retrieve top-k
relevant items and inject them into the prompt. Static rules stay in the
system prompt; retrieval carries what changes per user/query or exceeds the
context budget.

**How to apply.**
- **Eval the retriever BEFORE trusting what it feeds the model** — bad
  retrieval is *negative* information; retrieval-augmented prompting scored
  below zero-shot on every dimension when the embedder couldn't tell
  souvlaki from pasta (lm #18b).
- Pick the embedder with a mini-eval (a 4-model bake-off chose mpnet).
- Embed only what should drive similarity; labels go in METADATA.
- Enrich the representation before upgrading the model: prepend category,
  append ingredients/attributes (lm #17).
- Chunking matches document structure (semantic / fixed+overlap / sentence
  / recursive); enrich chunks offline with a teacher; hybrid dense+BM25 via
  RRF; bi-encoder retrieves top-20, cross-encoder re-ranks to top-3.
- Budget the token cost — injected context ran ~705 tokens/call (lm week 3).

**When NOT to use.** Exact-schema queries ("all X where Mod ≥ 2") — that's
a database, not similarity search (wasteland journal #3). Small corpora of
structured rows don't need vectors.

**Gotchas (earned the hard way).**
- When RAG fails, the TARGET may be wrong, not the tool: recipe-similarity
  few-shot hurt; per-user history retrieval worked with the same machinery
  (lm roadmap W-4 reframe).
- Make indexing delete-then-recreate; a crashed cell left an empty
  collection that "existed" and silently emptied every later query. Guard
  queries with `count()` checks (lm #33).
- Library contracts move: chromadb ≥1.x requires the full
  `EmbeddingFunction` protocol (lm #32).

**Related:** [embeddings-and-similarity-metrics], [structured-output-json]
