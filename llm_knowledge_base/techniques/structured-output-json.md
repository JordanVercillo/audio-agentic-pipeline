---
id: structured-output-json
title: Structured output (JSON mode / schemas)
type: technique
origin: "language-models course, week 4 + week 8"
tags: [llm, reliability, pipelines, contracts]
use_when: "LLM output is inconsistent/unparseable, or pipeline stages need a guaranteed shape"
maturity: proven
version_added: 2026.07.07
---

# Structured output (JSON mode / schemas)

**What it is.** Constrain the model to a schema instead of parsing prose:
`ollama.generate(format="json")`, Pydantic/JSON-Schema definitions, or
constrained decoding. `temperature=0` for classification consistency.
Downstream code gets a contract, not a conversation.

**How to apply.**
- Define the schema first (fields, enums, types); put it in the prompt AND
  enforce it at the API level where the runtime supports it.
- Closed enum fields get an `Other` bucket — without one the model is
  forced to lie about outliers, and what piles up in `Other` is your next
  vocabulary revision.
- Want reasoning too? Add a `thoughts` field ORDERED BEFORE the answer
  fields — CoT and strict schemas aren't mutually exclusive.
- In multi-stage pipelines, the schema is the interface contract between
  stages — version it like one.

**When NOT to use.** Open-ended generation where the value IS the prose
(narratives, chef's notes) — schema the envelope, free-text the field.

**Gotchas (earned the hard way).**
- Ollama *enforces* valid JSON; raw HF `model.generate()` does NOT — extract
  with `re.search(r'\{.*\}', out, re.DOTALL)` or constrained decoding
  (lm spec pitfall, week 5).
- Teachers often fence JSON in ```` ```json ```` — strip fences before
  parsing (lm eureka #33).
- An `except` that substitutes a default on parse failure BURIES the error:
  a whole column shipped as empty strings while looking populated (lm #33).
  Log every swallow; spot-check the field.

**Related:** [deterministic-audit-scripts], [teacher-student-distillation]
