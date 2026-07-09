# SPEC — Vercillo Analytics: the audio-agentic-pipeline portfolio project

**Status:** Approved design (v1.0, 2026-07-03) · **Owner:** Jordan Vercillo · **Lead design:** pipeline-partner session
**Supersedes:** the roadmap/current-state sections of `CLAUDE_INSTRUCTIONS.md` (frozen 2026-05-06 snapshot) and the gameplan detail in `notes/project_roadmap.md`.

**Document map** (one source of truth per concern — journal #4/#8 lesson):

| Concern | Lives in |
|---|---|
| What we're building & why (vision, phases, acceptance) | **THIS FILE** |
| Ground rules (non-negotiables) | `CLAUDE.md` |
| Architecture reference & ADRs | `CLAUDE_INSTRUCTIONS.md` (manual; its status tables are historical) |
| Verified live state + next action | `notes/PROJECT_CONTEXT.md` |
| Weakness ledger (W-numbers) | `notes/project_roadmap.md` |
| Lessons | `notes/engineering_journal.md` |

---

## 1. Vision

**One sentence:** A personal music-analytics data platform that rebuilds the acoustic intelligence Spotify's API deleted — Spotify listening history → YouTube audio acquisition → local 77-dim DSP → medallion warehouse → taste analytics — engineered so that **AI agents are first-class users of both the codebase and the data**.

**The thesis that makes it a story, not a toy:** In February 2026 Spotify removed `/audio-features`, `/audio-analysis`, and `popularity` for third-party apps. Every hobby project that consumed those columns died. This project answers by *becoming the producer*: it acquires real audio (rate-limited, idempotent YouTube acquisition), extracts its own 77-dimension feature space (librosa DSP), and warehouses it in a medallion star schema designed for agent consumption. The deprecation is the origin story (journal #1).

**Why Jordan is credible here:** the domain is authentic (musician, Ableton producer — resume Interests) and the platform patterns mirror his production work (medallion warehouse on BigQuery, Dataform, Dagster at Aritzia) — but implemented here in **production Python with tests, CI, and agent tooling**, which is exactly the evidence the resume doesn't yet show.

## 2. Audience & what the project must prove

Reference role: **Spotify Data Engineer – Platform, Toronto** (`Spotify_Data_Engineer_Platform.md`). Mapping of JD signals → where this project provides evidence:

| JD signal | Evidence in this project |
|---|---|
| "Build large-scale batch … data processing tools" | 7-step orchestrator; PySpark jobs running against the real warehouse; scaling narrative (P7) |
| "Improve developer experience and standardizing workflows" | The agent harness (skills + deterministic audit + env-verify), contracts, one-command runs, CI (P6) |
| "Systems that enable AI agents to effectively interact with data infrastructure" | **The differentiator.** Agent-optimized gold layer (ADR-002) + `column_descriptions` + MCP server over the warehouse (P5) + the harness itself as a working exhibit |
| "Testing, maintainable, high-quality code" | 55+ synthetic-data tests colocated with modules; CI gate; typed, documented modules |
| "Python or JVM-based … Spark, Flink, Dataflow" | Python package architecture + PySpark transforms verified on real data (P7) |
| Data quality culture | `warehouse-audit`: deterministic bridge-key/join/contract validation run after every pipeline change |

**Resume-gap lens** (what the day job already proves vs. what this repo must add): BigQuery/Dataform/SQL depth → already proven at Aritzia; **production Python, working Spark, CI/CD, and *building* (not just using) agent-data systems → must be proven HERE.** Every phase below earns its place against this table.

## 3. Architecture (verified 2026-07-03)

```
Spotify API (PKCE only)      YouTube (yt-dlp + ffmpeg/libmp3lame)
      │ top tracks/artists         │ {spotify_track_id}.mp3
      ▼                            ▼
step 1-2: fetch + stage      step 3: acquire (idempotent, rate-limited)
      │                            │
      │                      step 4-5: 77-dim DSP (librosa) + stage
      ▼                            ▼
   STAGING (Bronze, append-only snapshots + lineage)
      ▼
   CLEANSED (Silver: typed, deduped — (track_id, time_range) grain)
      ▼
   MODELED (Gold: fact_listening_features + dim_tracks/artists/time_range
            + column_descriptions — denormalized, agent-optimized)
      ▼                    ▼                     ▼
  analysis/ (drift)   search/ (FAISS+UMAP)   agent access (P5: MCP)
```

**Invariants (from `CLAUDE.md`, enforced by `warehouse-audit`):**
1. `spotify_track_id` is the only join key; filenames ARE the key (ADR-005).
2. Parquet only, pyarrow engine (ADR-006).
3. 2026 API guardrails: PKCE auth; no deprecated endpoints/fields (`.agent_prompts/01`).
4. No secrets in the repo — env/`.env` only; PKCE needs no client secret.
5. Tests are synthetic-only (`generate_test_signal()`); no network in CI.
6. Idempotency everywhere: file cache + Parquet cache; reruns are safe and cheap.
7. `data/` is rebuildable and never committed.

**Feature contract (clarified after journal #8):** the canonical similarity contract is `TrackFeatures.to_summary_vector()` — exactly **77 dims**, frozen (FAISS/embedding consumers). The warehouse carries the **full serialized feature set (82 numeric feature columns + key/mode)**. The contract is a *column list owned by the extractor*, not a magic number; P6 makes the audit verify the exact list via a completed `column_descriptions`.

## 4. The AI story (three honest roles)

Cheap-deterministic-first is a design rule; AI is applied where it's genuinely the right tool:

1. **AI as engineering copilot (already real, demo-able):** the Claude Code harness — `pipeline-partner` (design sessions with persistent memory), `warehouse-audit` (agent-invoked deterministic QA), `env-verify` (capability-checking triage). The `notes/` memory system + journal is *process evidence* a hiring loop can read.
2. **AI as data consumer (P5 → P8, the JD differentiator):** an MCP server exposes the gold layer to any agent — schema self-description via `column_descriptions`, safe read-only SQL, precomputed insights. "An AI agent answers questions about my music taste from a warehouse built for it" is the demo. P8 productizes the same retrieval core as **RAG**: visitor listening history + feature-store joins ground an LLM's taste answers on the public pilot.
3. **AI as narrator (P2, optional path):** the insight engine is deterministic (metrics → JSON → templated markdown) so it's testable; `--llm-polish` optionally rewrites the prose. The pipeline never *depends* on an LLM.

## 5. Build plan

Sequenced by portfolio value; each phase has acceptance criteria (measured, not asserted) and a demo artifact. Current baseline: Phase V verified — pipeline runs end-to-end, audit ALL-GREEN, 9-track corpus.

### P0 — Full-corpus run (prerequisite, ~1 background session)
Populate the warehouse with the full profile: `python scripts/run_pipeline.py` (50/range → ~117 unique tracks; ~108 downloads at 5–30 s spacing ≈ 1.5–3 h).
**Accept:** audit ALL-GREEN at full scale; run timing + failure/no-match counts recorded in PROJECT_CONTEXT. **Artifact:** populated warehouse + run log.

### P1 — Taste Map: genre clustering (roadmap 5.2 — the money visual)
UMAP projection of the feature space, clustered (KMeans/HDBSCAN), colored by `dim_artists.genres` (coarse-mapped), sized/marked by time range. Deterministic seed.
Files: `src/analysis/clustering.py` (new), enhance `src/search/visualizer.py`; reuse FAISS store.
**Accept:** cluster assignments land as a Parquet keyed by bridge key (audit-clean); same-seed reruns identical; visual renders with ≥ 2 interpretable genre neighborhoods. **Artifact:** `taste_map.png` — the README hero image.

### P2 — Insight engine (roadmap 5.1)
`src/analysis/insights.py`: pure functions over fact + drift + clusters → `insights.json` (drift score & label, top-5 drivers, cluster/genre summaries, cross-range persistence, superlatives) → templated `INSIGHTS.md`. Optional `--llm-polish` flag (Claude API) rewrites narrative prose only.
**Accept:** unit-tested on a synthetic fact table; JSON schema stable; runs as pipeline step 8. **Artifact:** `INSIGHTS.md` — readable taste narrative.

### P3 — Temporal trend visuals (roadmap 5.3)
Wire existing `plot_drift_radar` / `plot_temporal_heatmap` / delta charts to the real warehouse; export PNGs deterministically.
**Accept:** each chart generated by one function from the gold layer alone. **Artifact:** 3–5 PNGs consumed by P4.

### P4 — Portfolio export (roadmap 5.4)
`src/export/portfolio.py` + Jinja2 template → **single-file** static HTML (inline CSS/images): top tracks, taste map, drift narrative, methodology footnote. (The Copilot-era `temporal_analysis.html` in Downloads is the fidelity reference.)
**Accept:** one command from a fresh gold layer → self-contained HTML < 10 MB, opens offline. **Artifact:** `taste_report.html` — shareable, linked from README.

### P5 — Agent Access Layer: MCP server ✅ DONE 2026-07-03 (the JD bullet made concrete)
`src/agent/mcp_server.py` (FastMCP, stdio): tools `get_schema()` (from `column_descriptions`), `query_warehouse(sql)` (DuckDB **read-only** over gold Parquet, SELECT-only guard), `get_insights()` (serves `insights.json`). Register in Claude Code/Desktop.
**Accept:** tool functions unit-tested against a synthetic warehouse; injection-guard test (rejects non-SELECT); a recorded agent session answers ≥ 3 taste questions correctly. **Artifact:** demo GIF/transcript in README + `docs/AGENT_ACCESS.md`.
**Delivered:** pure `src/agent/warehouse_agent.py` core (DuckDB + two-layer guard, D-10) reused by P8's RAG; thin `mcp_server.py` wrapper; 30 tests (guard matrix + sandbox + 3 tools); verified via a real MCP stdio handshake (list_tools + query + injection-reject) and 5 live taste questions; `docs/AGENT_ACCESS.md` with registration config + transcript.

### P6 — Platform hardening (the standardization/DX pass)
uv migration (`pyproject.toml` + lockfile; keep `requirements.txt` export) · ruff · GitHub Actions CI (lint + pytest, synthetic-only, no secrets) · complete `column_descriptions` to the full schema and switch the audit from ±7 tolerance to **exact column-list verification** · archive legacy (`spotify/` → `legacy/`, `00_tools/media_converter.py` → `legacy/`) · README rewrite (below).
**Accept:** CI green on a clean clone; audit contract check exact; README passes the 90-second test (§8). **Artifact:** green CI badge; reviewer-grade README.

### P7 — Scale slice (choose-one, decision gated)
**Default (chosen):** prove the existing PySpark jobs (`spark/feature_transform.py`, `temporal_aggregate.py`) against the real warehouse; write `docs/SCALING.md` — the honest design narrative for 10K/1M tracks (GCS layout, BigQuery external tables, Dataflow vs Spark tradeoffs, partitioning strategy). Zero cloud spend, maximum systems-design signal.
**Stretch (optional, only after P6):** publish the gold layer to BigQuery and point the MCP `query_warehouse` at it — a one-evening bridge from local to cloud.
**Accept:** spark-submit runs green on the real warehouse with results matching pandas outputs (row-count + centroid parity). **Artifact:** `docs/SCALING.md` + parity check output.

### P8 — Production pilot: public taste-insights webapp (owner decision D-7)

**Vision (Jordan, 2026-07-03):** a public website where *anyone* authenticates
their own Spotify account — **without our client secret existing anywhere** —
and the app pulls their listening history to power RAG-grounded taste insights.

**Why PKCE makes this possible:** Authorization Code + PKCE needs only the
public client ID; each visitor authorizes *their own* account. The 2026-07-03
PKCE-only refactor made the codebase pilot-ready by construction.

**Scope:**
- **Auth:** server-session PKCE flow (client ID + registered redirect URI
  only). Session rotation on callback; secure cookies (patterns preserved
  from the old Phase-4 webapp's security hardening).
- **Data:** on login, fetch the visitor's top tracks/artists (3 time ranges,
  `user-top-read`). **Privacy-first:** session-scoped, ephemeral by default
  (TTL expiry); persistence only by explicit opt-in. Published privacy note.
- **Acoustic enrichment — the feature-store pattern:** join visitor
  `spotify_track_id`s against OUR local DSP corpus (the bridge key becomes a
  shared feature store). Overlapping tracks get real 77-dim acoustic
  insights instantly; non-overlapping tracks get metadata/genre treatment.
  **Visitors never trigger YouTube acquisition** (non-goal preserved).
- **RAG:** retrieval over the visitor's tracks + joined features + insight
  templates + `column_descriptions` → grounded LLM answers to taste
  questions ("what's my vibe lately?"). Shares its retrieval core with P5's
  MCP layer — P5 builds the core locally, P8 productizes it behind the web.
  Deterministic insight fallback when no LLM key (D-5 holds).
- **Deploy:** containerized → GCP Cloud Run, custom domain
  (vercilloanalytics.com). No secret in the deployment env — infra creds only.

**The honest gate:** Spotify **Development Mode caps apps at allowlisted
users** — *[corrected 2026-07-09: the Feb-2026 platform policy sets the cap
at **5 users** (was ~25) and restricts extended-quota mode to registered
businesses with ≥250K MAU, so quota extension is off the table for a
personal pilot; the manual 5-seat allowlist is the permanent gate, and the
landing page tells visitors how to request a seat]*. Pilot = public URL +
allowlisted testers (friends/recruiters on request). The spec calls this a
*pilot* deliberately.

**Accept:** an allowlisted tester on the public URL logs in with their own
Spotify account, sees their top items, at least one acoustic-informed
insight from corpus overlap, and gets a grounded RAG answer citing their
data; deployment env contains no Spotify secret; sessions expire; privacy
note published. **Artifact:** live pilot URL + demo recording in README.

**Sequencing:** after P5 (shares the retrieval core) and P6 (CI before
deploy); can begin design in parallel with P7.

## 6. Non-goals

- **No hosted/multi-user service *before P8*.** P0–P7 are single-user,
  local-first; shareable artifacts are static. The production pilot (P8) is
  the deliberate, scoped exception — session-ephemeral, PKCE-only,
  feature-store reads only.
- **No real-time/streaming pretensions.** This is a batch pipeline; the scaling story addresses streaming honestly as "not this system."
- **No orchestrator theater.** No Airflow/Dagster here — the day job already proves Dagster; this repo demonstrates orchestration as clean Python + CI, which is the right size for the problem.
- **No audio redistribution.** Personal research use; MP3s are never committed, never served, acquisition stays rate-limited. **Web visitors never trigger acquisition** — they read the derived feature store only.
- **No second ID system, no CSV, no secrets in code.** Ever (ground rules).

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| YouTube acquisition fragility (yt-dlp churn, encoder deps) | CVE-pinned yt-dlp; env-verify checks *capability* (libmp3lame) not presence (journal #7); idempotent retries |
| Spotify dev-mode sandboxing tightens further | PKCE + guardrails module isolates the API surface; synthetic path keeps everything else testable |
| **Leaked client secret (git history)** | Working tree is now **PKCE-only — no secret used or referenced anywhere** (D-8); Jordan rotating the old secret in the dashboard closes the historical exposure (rotation doesn't affect PKCE/client ID) |
| Pilot gate: Spotify dev-mode allowlist (**5 users** since the Feb-2026 policy; was ~25) | P8 ships as an allowlisted pilot; extended quota is business-only (≥250K MAU) since Feb 2026, so the 5-seat manual list is the permanent gate — the landing page carries an invite-request notice; spec never claims "public at scale" |
| Pilot privacy (visitor listening data) | Session-ephemeral by default with TTL; opt-in persistence only; published privacy note; no third-party sharing (P8 acceptance criteria) |
| 117-track corpus thin for clustering | Honest visuals at n=117; optional corpus expansion via playlist endpoints (allowed surface) if P1 needs density |
| Single-machine env drift (conda base, PATH ffmpeg) | P6 uv migration + lockfile; env facts pinned in PROJECT_CONTEXT until then |
| LLM dependency creep | Deterministic-first rule: every AI-polished artifact has a testable template fallback |

## 8. Definition of done — the 90-second reviewer path

A hiring-loop reviewer, cold, in 90 seconds: **README hero** (taste map + drift score + one-line thesis) → **architecture diagram** → three commands (`run_pipeline.py`, `pytest`, `audit`) with real output pasted → **agent demo GIF** (MCP answering a taste question) → link to `taste_report.html` and `INSIGHTS.md`. Everything they might try actually works on a clean clone (CI proves the test path).

## 9. Decision log

| # | Decision | Rationale |
|---|---|---|
| D-1 | ~~Descope the webapp~~ **SUPERSEDED by D-7** | (Original rationale: lost in upload; hosting+OAuth surface adds risk.) |
| D-2 | **Add MCP Agent Access Layer (P5)** | Converts the JD's agent-infrastructure bullet from claim to demo; gold layer was already designed for it (ADR-002). |
| D-3 | **Spark-first scale slice; BigQuery as stretch** (P7) | Resume already proves BigQuery in production; working Spark + a scaling design doc is the missing evidence. Zero cloud spend. |
| D-4 | **Feature contract = column list, not a count** (P6) | Journal #8: two docs agreed on "77" while disagreeing on membership. Exact-list audit kills the class of bug. |
| D-5 | **Deterministic-first AI** (P2/P5) | Testability and honesty; LLM adds polish, never load-bearing correctness. |
| D-6 | Phase order P0→P7 by demo value | Money visual first; hardening before scale claims; every phase ends demo-able. |
| D-7 | **Owner override (Jordan, 2026-07-03): webapp reinstated as P8 production pilot** — public site, per-visitor PKCE auth, RAG-grounded insights | The pilot converts the portfolio from "artifacts" to "a running product"; PKCE-only architecture (D-8) makes per-visitor auth possible with zero secret. Gated honestly on Spotify extended-quota approval. |
| D-8 | **PKCE-only auth everywhere; client-credentials flow deleted** (2026-07-03) | One flow for pipeline AND pilot; a user PKCE token covers public endpoints too; no secret exists in code/env/deployment — nothing to leak, rotate, or manage. Old secret rotation still closes the historical exposure. |
| D-9 | **ADR-003 amended: drift metric = RMS σ-shift between standardized centroids** (was: cosine distance) | Measured on real data, cosine failed both ways — raw: scale-dominated, reads ≈0 always; centered: geometry-forced ≈1.5 always (direction-only metrics can't express effect size). RMS σ-shift keeps ADR-003's scale-invariance via z-scoring and measures magnitude honestly. Journal #10; sanity-anchored at both ends (0 for constant corpus, ~2σ for strong synthetic drift). |
| D-10 | **Agent SQL security = capability removal, not a denylist** (P5) | The real boundary is DuckDB `enable_external_access=false` + `lock_configuration=true` over native in-memory tables (no filesystem/network reach, nothing persistent to corrupt); the SELECT-only statement guard is defense-in-depth + a clear read-only contract, never the primary defense. A denylist can't enumerate every dangerous DuckDB function. Journal #11. Reused verbatim by P8's web-facing RAG. |
