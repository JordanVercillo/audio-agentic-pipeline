# Course Summary — Foundations of Language Models (8 modules)

*Per module: the key points, the tools it put on the bench, the techniques
exercised, and the lessons that only surfaced in real project work
(citations = `eureka_moments.md` entry numbers in this repo). Cards in
`../techniques/` carry the reusable versions.*

The arc — each module adds ONE capability:

```
W1 prompting → W2 embeddings → W3 context/RAG plumbing → W4 evaluation
→ W5 fine-tuning → W6 RAG done right → W7 multimodal → W8 agents + production
```

---

## Week 1 — Introduction to LLMs

**Key points.** An LLM is one mechanism: probabilistic next-token
prediction; everything else is steering the distribution. Logprobs expose
the ranked candidates behind each token. System prompts/roles reshape the
whole distribution; special tokens end generation.

**Tools.** `ollama` (local inference, `gemma2:2b`), `ollama.generate()`
with `logprobs`/`top_logprobs`.

**Techniques.** Role/persona prompting; problem framing (classify / decide
/ enrich); scoping to one-prompt-one-call-one-output.

**Lessons.** Pick a problem that flows WITH the surrounding infrastructure
(#1). Scope to the smallest LLM-shaped slice (#2). Name the call's exact
I/O — user-flow talk means you're designing a different module (#5). One
enum per question (#3). The LLM only does what a DB column can't (#4). A
persona needs a field in the OUTPUT or it's invisible (#6).

## Week 2 — Tokenization & Embeddings

**Key points.** Tokens are BPE sub-word units — rare domain words fragment
(`lasagna` → `las|agna`). Embeddings put text in a vector space where
distance ≈ meaning-as-written; cosine similarity is standard.

**Tools.** `sentence-transformers` (`all-MiniLM-L6-v2`), HF tokenizers,
numpy (`np.dot`/`norm` by hand).

**Techniques.** Similarity evals with close/far/domain pairs; judging
embedders by the **gap** between group means, disaggregated per category;
controlled comparisons (hold the item, flip one word).

**Lessons.** Embeddings encode meaning, not your labels (#10) or numeric
properties (#11); check tokenization survival of domain words (#12); gap
not magnitude (#13); overall means hide per-category failures (#14);
similarity is of the words in the string (#16); richer input beats a
bigger model (#17). Dedicated embedders beat generative-as-embedder
(measured). → card: `embeddings-and-similarity-metrics`

## Week 3 — Transformer Architecture & Context

**Key points.** Causal masking; attention cost is quadratic in sequence
length; KV cache + GQA are why 2B models run on laptops. Context windows
are finite and priced → embed the knowledge base, retrieve top-k (RAG).

**Tools.** `chromadb` (persistent vector store), embedder choice via
mini-eval (mpnet won a 4-model bake-off), token counting.

**Techniques.** Vector-store CRUD (`add`/`query`); structured intent
extraction as a retrieval pre-filter; labels in metadata, not embedded text.

**Lessons.** Retrieval quality is measurable BEFORE you trust it (souvlaki
→ Italian pasta); count the token cost of injected context (~705/call
here). → card: `rag-and-retrieval`

## Week 4 — Prompt Engineering & Evaluation

**Key points.** Message roles (system anchors, user carries data,
assistant can be pre-filled). Zero-shot is the baseline to beat; few-shot
calibrates boundaries; structured output + `temperature=0` trades
reasoning for parseability — a CoT `thoughts` field buys it back. Eyeball
testing doesn't scale: build a golden set. Recognize the prompt ceiling.

**Tools.** Pydantic/JSON schemas, `format="json"`, teacher model
(`gemma4:12b`) for label proposal, csv gold sets.

**Techniques.** Golden-set construction (teacher-propose → human-verify);
per-dimension accuracy vs the majority-class baseline; failure-mode
notes per row. → cards: `gold-eval-sets`, `structured-output-json`,
`teacher-student-distillation`

**Lessons.** Bad retrieval is NEGATIVE information — RAG scored below
zero-shot on every dimension (#18b). Accuracy means nothing without the
majority baseline (#19b). Gold labels must be inside the model's output
space (#22). Ground subjective labels in observable features (#23). The
"Other" bucket is your taxonomy's to-do list (#21).

## Week 5 — Fine-Tuning with Adapters (LoRA/QLoRA)

**Key points.** Adapters train ~1% of params beside a frozen (4-bit) base;
consumer GPUs suffice. Two motives: efficiency (internalize a verbose
prompt) vs accuracy (teach hard cases, with reasoning). The 5-question
dataset framework: scope / format / source of truth / coverage /
validation.

**Tools.** `torch`+CUDA, `transformers`, `peft`, `trl` (SFTTrainer),
`bitsandbytes` (NF4), `datasets`; Unsloth = same method, faster wrapper
(#21). `ollama stop` to free VRAM before training.

**Techniques.** JSONL dataset builds with leakage guards (id AND name,
#27); reasoning-first examples; distribution matching + coverage
balancing; decode ONLY generated tokens (#23); artifact existence = the
proof-file, not the folder (#24). → card: `finetuning-data-design`

**Lessons.** Same recipe swung −19 to +24 points on data design alone
(#22). The training label distribution is a hyperparameter (#28→#30);
coverage is a separate lever (#31). A teacher sharing the student's bias
can't author the correction — hand-write the hard cells (#25, #26).

## Week 6 — Semantic Search & RAG (done right)

**Key points.** Static rules → system prompt; per-user/per-query context →
retrieval. Multi-layer RAG (user history + domain chunks) composed into
one prompt. Chunking matches document structure. Offline teacher
enrichment; hybrid dense+BM25 with RRF; bi-encoder retrieve → cross-encoder
re-rank.

**Tools.** chromadb ≥1.x (full `EmbeddingFunction` protocol — the contract
moved, #32), MiniLM local embedder, teacher enrichment with
`format="json"`.

**Techniques.** Reframing failed retrieval at a different target
(recipe-similarity failed; user-context worked); delete-then-recreate
indexing; `count()` guards on queries.

**Lessons.** A crashed cell leaves half-built state that poisons
downstream queries (#33); an `except` that substitutes a default BURIES
errors — a whole enrichment column silently became empty strings (#33).

## Week 7 — Multimodal Models

**Key points.** Transformers don't care what tokens represent — image
patches project into the same token space (ViT → projection → fusion);
base LLM stays frozen. Audio parallels via mel spectrograms; Whisper
converts speech→text that slots into any text pipeline.

**Tools.** Vision-capable Ollama models (`gemma4:12b` — verify the `clip`
block with `ollama show`; a `vision` FLAG can ship without the projector
weights, #32), `pillow`.

**Techniques.** Image → structured JSON extraction; the recovery ladder
(strip fences → small text model reformats to schema); photo-vs-typed
parity as the acceptance test.

**Lessons.** A capability flag is a claim, not a proof — check the
component exists before building on it (#32).

## Week 8 — Evaluation, Agents & Production

**Key points.** Deterministic pipelines (hard-coded transitions) vs
agentic ReAct loops (model picks tools at runtime) — default deterministic;
it's easier to eval and trust. Structured output is the interface contract
between stages. Chat = an outer state machine with memory. Agent eval has
four dimensions: task completion, trajectory quality, output quality,
robustness. LLM-as-judge scaled by human-calibrated spot checks.

**Tools.** OpenTelemetry/OpenLLMetry tracing; LLM-as-judge with a larger
model; `streamlit` for the demo surface.

**Techniques.** System-level eval design; trajectory logging; judge
calibration. → cards: `gold-eval-sets` (§judge), `deterministic-audit-scripts`

**Lessons.** Deliverables that "arrive at the end" (the demo app) must be
built incrementally from the middle — or the finale is construction panic,
not polish.

---

## Meta-lessons (bigger than any module)

- **Evaluation is a design tool, not a final exam** — if it never
  surprises you, it isn't measuring anything (#7, #18).
- **Trust the sequence** — compressing modules made every design worse (#19).
- **Capture the surprise, not the fix** (#20) — the practice this whole KB
  is built on.
