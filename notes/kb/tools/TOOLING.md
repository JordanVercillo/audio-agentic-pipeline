# Tooling Matrix — environments, packages, models

*What's on the bench across Jordan's projects, and the conventions that
make it agent-friendly.*

## Python execution (two proven modes)

| Mode | When | How |
|---|---|---|
| **Project env via uv** | A real package project (language-models) | `pyproject.toml` + `uv.lock` + `.python-version`; ALWAYS `uv run python …`, never activate a venv (stateless per command = agent-safe) |
| **Single-file uv scripts** | Harness/audit/sim scripts in ANY repo | PEP 723 header (`# /// script` + `dependencies=[…]`) → `uv run script.py` needs no project env at all — this is how audit scripts run identically in Unity repos and conda repos |

Watch for interpreter shadowing: a bare `python` on PATH may be a dep-less
system install while the real env is elsewhere (audio repo: conda base
3.13). Wrong-interpreter mimics missing-environment (audio journal #7 kin).

## Package stacks by capability (proven versions in each repo's manifest)

| Capability | Packages |
|---|---|
| Local LLM | `ollama` |
| Embeddings / similarity | `sentence-transformers`, `numpy` |
| Vector store / RAG | `chromadb` (≥1.x protocol!), `faiss-cpu` (audio) |
| Fine-tuning (QLoRA) | `torch` (+CUDA index pin in pyproject), `transformers`, `peft`, `trl`, `bitsandbytes`, `accelerate`, `datasets` |
| Audio DSP | `librosa`, `soundfile`; acquisition: `yt-dlp` (CVE floor ≥2026.2.21) + ffmpeg **with libmp3lame** (Gyan build — Anaconda's lacks it) |
| Distributed | `pyspark` (needs JVM) |
| Data layer | `pandas`, `pyarrow` (Parquet-only for feature matrices), `scikit-learn`, `umap-learn` |
| App/demo | `streamlit`, `fastapi`+`uvicorn` |
| Tests | `pytest` (synthetic data — no network in unit tests) |

## Local models via Ollama — the three-role pattern

| Role | Model class | Job | Verify |
|---|---|---|---|
| Student/worker | small (`gemma2:2b`) | the production call; fine-tune target | — |
| Teacher/judge | large (`gemma4:12b`) | label proposal, enrichment, judging | shares student's biases — human-verify |
| Embedder | dedicated (mpnet/MiniLM) | similarity | beat generative-as-embedder, measured |

**A capability flag is a claim, not a proof**: check `ollama show <model>`
for the actual component (`clip` block for vision) before building on it
(lm eureka #32). GPU discipline: `ollama stop` before training (12 GB
budget, one CUDA owner at a time).

## Git conventions (agent-relevant)

- Two-remote consumption: `origin` = yours (push), `upstream` = source
  (pull, push DISABLED); `merge=ours` driver in `.gitattributes` protects
  customized files across upstream merges.
- Commit-sized reviewable chunks; Jordan pushes. Rebuildable artifacts
  (data, adapters, stores) are gitignored — the script is the artifact.
- Secrets: `.env` (gitignored) + names-only in any output. A hardcoded
  "fallback" credential IS a leak — and git history keeps it after the
  scrub; only rotation closes it (audio journal #5).

## The harness kit (per repo)

`CLAUDE.md` bootloader → `notes/PROJECT_CONTEXT.md` state file → journal →
roadmap → `.claude/skills/` (orchestrator + audit worker + env triage) →
this KB synced at `notes/kb/`. Templates: `../templates/`; full rationale:
`claude-repo-playbook` (playbook 01–08).
