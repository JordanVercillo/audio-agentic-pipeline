# Vercillo Analytics — Full Application Spec & Long-Term Roadmap (v2, local-first)

**Status:** vision spec v2 — 2026-07-07. v1 was written the day the P8 pilot
became a working demo; **v2 revises it under the owner's cost constraint: zero
external spend — no GCP/BigQuery/Cloud Run. All development AND hosting stay
local (the owner's PC) until the app outgrows it.** Epics A and B have shipped
since v1; statuses below are current.

**Relationship to existing docs.** `SPEC.md` (P0–P8, decisions D-1…D-10) and
`CLAUDE.md` ground rules remain in force. This doc extends them with the
full-app architecture and decisions **D-11+**. Where it conflicts with SPEC.md's
P8 non-goals (notably "visitors never trigger acquisition"), this doc supersedes
(D-11). Cloud designs in `docs/SCALING.md` remain the *documented migration
path*, not a build target (D-16).

---

## 0. TL;DR

A PKCE-authenticated web app (no owner secret — D-8), **running entirely on the
owner's PC at $0/month**, where any allowlisted listener:

1. **Sees their Spotify top songs & artists** across Spotify's three time windows
   (short / medium / long term — the only windows the 2026 API exposes).
2. **Sees the local-DSP audio features** of those songs — tempo, energy, timbre,
   77-dim vectors — extracted from YouTube-sourced audio via librosa and **cached
   forever in a local database** so no song is ever analyzed twice.
3. **Explores a data-science layer**: ML clustering of their songs *and* artists,
   taste-drift analytics, a **mel-spectrogram per song**, **hover-to-inspect +
   deep-dive** on any track, and their **acoustic signature** (the features where
   their taste deviates most from the population).
4. **Gets a grounded RAG taste classification** (Phase 2): an archetype +
   narrative grounded strictly on their own clustered features and drift.

Deliberately an **analytics-engineering showcase**: public APIs, audio feature
engineering (librosa), a medallion warehouse + Spark, ML clustering, a serving
database, and an agent-ready RAG layer — with the *right-sizing judgment* to run
it all on one machine and the documented path to scale off it.

---

## 1. Product vision (owner, 2026-07-07)

> "A user logs in, sees their top Spotify songs and artists by the periods
> Spotify allows, then views the **top audio features** extracted from those songs
> (YouTube WAV or any extraction method). A second dashboard shows **drift over
> time** — really interesting bucketing of **similar artists via ML clustering**,
> and **bucketing songs in your top-3 windows via clustering** on their audio
> features. A fun data-science project highlighting strong analytics-engineering,
> Spark, and feature engineering leveraging APIs and librosa. Include a
> **spectrogram of each song**. On polish: **hover a song → see its audio
> features**, click into a **deep dive**. **Cache all extracted features to a
> database** so we don't re-extract. **RAG classification** as Phase 2."
>
> **v2 constraint:** "no external cost like BQ/GCP — keep all development local
> and host via my PC before moving to external vendors."

---

## 2. Users & core flows

| Flow | What the user does | What the app shows |
|---|---|---|
| **Login** | Authorizes their own Spotify (PKCE, `user-top-read`) | — |
| **Top items** | Lands on the dashboard | Top tracks + artists, per time window, album art |
| **Audio features** | Hovers a track | Its tempo/energy/brightness from the cache; "analyzing…" for misses |
| **Deep dive** | Clicks a song | Feature breakdown, **mel-spectrogram**, radar, "songs like this", its cluster (Epic C) |
| **Analytics** | Opens the analytics dashboard | Song clusters across the 3 windows, **artist clusters**, drift trajectory, **acoustic signature** |
| **Ask / classify** | Asks a question / requests a profile | Grounded RAG answer + (Phase 2) a taste archetype |

**Privacy invariant (D-7 preserved):** the user's *listening data* stays
session-ephemeral. The *feature cache* is **track-keyed and user-agnostic** — it
stores acoustics of songs, not who listened to them.

---

## 3. What exists today (honest baseline, post-Epics A+B)

| Layer | Status |
|---|---|
| Pipeline P0–P7 (Spotify → YouTube → 77-dim DSP → Parquet medallion → MCP), Spark parity in CI | ✅ on `main` |
| Clustering + drift analytics (`analysis/`: KMeans+silhouette, UMAP, σ-shift D-9) | ✅ (owner corpus; per-user in Epic C) |
| P8 pilot webapp: PKCE auth, dashboard, drift, top artists, RAG `/ask` | ✅ merged (PR #6) |
| **Epic A — shared feature cache + async extraction** (`src/store/`: SQLAlchemy cache, DB-backed queue, yt-dlp→librosa→spectrogram worker, seed script; dashboard reads cache, queues misses, shows coverage) | ✅ built (PR #7) |
| **Epic B — features experience** (hover tooltip, `/song/{id}` deep-dive: spectrogram + radar + "songs like this") | ✅ built (PR #7) |
| Epic C — clustering dashboards (songs + artists) + drift viz + acoustic signature | ❌ next |
| Epic D — RAG taste classification | ❌ Phase 2 |
| Epic E — self-host & share (tunnel, worker loop, backups, privacy page) | ❌ after C |

---

## 4. The core architectural shift (unchanged from v1)

Every visitor's songs get their real features via a **shared, track-keyed
feature cache**: cache hit → instant features; miss → queued for async
extraction; a miss extracted for one visitor is cached for all. **Analyze each
song once, ever** (D-11). Extraction never blocks a request.

**v2 addition — why local-first strengthens this:** YouTube aggressively
throttles and blocks datacenter/cloud IP ranges. yt-dlp from a residential
connection is *more reliable* than from any cloud worker. The extraction layer —
the app's riskiest dependency — actively prefers the PC. Local-first is not a
compromise here; it's the better engineering call (D-16).

---

## 5. System architecture (local-first)

```
 Visitor ── HTTPS ── free tunnel (Cloudflare Tunnel / Tailscale Funnel) ──┐
                    (Spotify requires HTTPS for non-loopback redirects)   │
 ┌────────────────────────────── OWNER'S PC ────────────────────────────▼─────┐
 │                                                                            │
 │  FastAPI (uvicorn :8000) ── PKCE, no secret (D-8); sessions ephemeral (D-7)│
 │       │                                                                    │
 │       ├─ Spotify Web API → top tracks/artists (short/med/long)             │
 │       ├─ cache lookup ──► SQLite + WAL  (data/feature_cache.db)            │
 │       │   hit → features + spectrogram    [DATABASE_URL swaps in Postgres] │
 │       │   miss → INSERT extraction_jobs   ◄── THE DB IS THE QUEUE          │
 │       └─ analytics / RAG read the same cache                               │
 │                                                                            │
 │  Worker process (run_extraction_worker.py --loop)                          │
 │      polls extraction_jobs → yt-dlp (residential IP) → librosa 77-dim      │
 │      + mel-spectrogram → cache; audio deleted after (D-15)                 │
 │      spectrograms → data/spectrograms/*.png                                │
 │                                                                            │
 │  OFFLINE (same PC): Parquet medallion + Spark local[*] + scikit-learn      │
 │      cache snapshot → clustering / drift / artist centroids → results      │
 │      written back to the cache DB.  MCP agent reads the gold layer.        │
 └────────────────────────────────────────────────────────────────────────────┘
```

**Two data planes, one bridge key, one machine.** The serving plane is the
SQLAlchemy cache (SQLite+WAL now; Postgres via `DATABASE_URL` when needed). The
analytics plane stays Parquet + local Spark. Both key on `spotify_track_id`.

**Cost ledger (the v2 constraint, auditable):**

| Item | Cost |
|---|---|
| Hosting (owner PC) + HTTPS tunnel (Cloudflare/Tailscale free tier) | $0 |
| Serving DB (SQLite; optional local Docker Postgres) | $0 |
| Storage (local disk: cache DB, spectrograms, Parquet) | $0 |
| Spark (`local[*]`), scikit-learn, librosa, yt-dlp | $0 |
| CI (GitHub Actions free tier) | $0 |
| LLM answers | **$0 default** (deterministic fallback, D-5); `ANTHROPIC_API_KEY` is the *only* optional spend; Ollama is a $0 LLM alternative |
| Domain `vercilloanalytics.com` | already owned (its DNS on Cloudflare free tier gives the tunnel a stable URL) |

---

## 6. Data model (the cache DB)

Track-keyed and user-agnostic. Feature columns follow the frozen 77-dim /
82-column DSP contract — the cache invents no new schema. Portable SQLAlchemy:
**SQLite + WAL by default** (webapp + worker are two processes; WAL makes
concurrent reader/writer safe), Postgres+pgvector via `DATABASE_URL` with zero
code change (D-12 amended).

| Table | Key | Holds | Status |
|---|---|---|---|
| `track_features` | `spotify_track_id` | 82-col feature JSON + promoted columns, `spectrogram_uri`, provenance | ✅ |
| `track_meta` | `spotify_track_id` | name, artists, album (the worker's YouTube query) | ✅ |
| `extraction_jobs` | `spotify_track_id` | queued/running/done/failed, attempts, last_error | ✅ |
| `artist_profiles` | `artist_id` | acoustic centroid (mean of the artist's cached tracks), `cluster_id` | Epic C |
| `song_cluster_model` / `artist_cluster_model` | version | k, centroids, silhouette, trained_at | Epic C |

- **Similarity** ("songs like this"): z-scored acoustic distance in Python —
  correct and fast at pilot scale (≤ a few thousand cached tracks). On Postgres
  the same call swaps to a pgvector `ORDER BY embedding <-> :target`. Documented
  upgrade, not a dependency.
- **User listening data is never stored** — fetched fresh per login, held only in
  the session (D-7).
- **Longitudinal drift caveat (D-13):** Spotify exposes 3 fixed windows, not
  history. True drift-over-time needs opt-in accounts + scheduled snapshots (a
  Task-Scheduler job on the PC — still $0). Until then, drift = the σ-shift
  across the 3 windows, framed honestly as a 3-point trajectory.

---

## 7. Feature epics

### Epic A — Feature cache + per-user async extraction ✅ *(shipped)*
`FeatureCache` (get/missing/upsert/enqueue/claim_next/fail/job_status),
DB-backed queue, extraction worker (yt-dlp → librosa → 77-dim + spectrogram →
cache; audio deleted, D-15), seed script, dashboard wiring ("N of M analyzed ·
K analyzing…"). **Accepted:** cached songs render instantly; a new song is
extracted once and served to every later visitor; audio never stored.

### Epic B — Audio-features experience ✅ *(shipped)*
Hover a track → tempo/energy/brightness tooltip. Deep-dive `/song/{id}`: acoustic
summary, **mel-spectrogram**, inline-SVG radar, **"songs like this."**
**Accepted:** hover works on any cached track; deep-dive renders spectrogram +
neighbors end-to-end (proven on real owner audio).

### Epic C — Analytics & drift dashboard *(next — the data-science showcase)*
- **Song clustering** across the 3 windows: KMeans (silhouette-chosen k) on the
  77-dim features → each top song in an acoustic bucket; UMAP map colored by
  cluster; **drift as songs moving between clusters** short→long term.
- **Artist clustering**: acoustic centroid per artist (mean of their cached
  tracks) → cluster artists in sound-space; genres as secondary labels —
  "artists who *sound* alike, not just tagged alike."
- **Acoustic signature**: the features where the user deviates most from the
  cached population (|z| ranked) — the "your top audio features" of the vision.
- **Drift dashboard**: σ-shift headline + per-feature deltas + cluster-movement.
- Population-scale training runs on **local Spark** (the parity-tested jobs);
  per-user assignment is scikit-learn online. Cluster models are versioned rows
  in the cache DB.
**Accept:** a user sees their songs and artists bucketed with readable labels,
their acoustic signature, and a grounded, non-tautological drift readout.

### Epic D — RAG taste classification *(Phase 2)*
Beyond `/ask`: classify the user's taste into an **archetype** + short narrative,
grounded strictly on their clusters, signature, drift, and top items (reuses the
P8 RAG core; deterministic fallback holds — D-5, so Phase 2 still runs at $0).
**Accept:** the profile cites the user's real clusters/features/artists and
invents nothing.

### Epic E — Self-host & share *(replaces v1 "Deploy & harden" — D-16)*
Run the pilot from the PC for allowlisted testers, at $0:
- **Free HTTPS tunnel** (Cloudflare Tunnel or Tailscale Funnel) → stable URL
  (optionally `vercilloanalytics.com` via free Cloudflare DNS); register that
  redirect URI in the Spotify dashboard (HTTPS required for non-loopback).
- **Worker loop** (`--loop`) + a documented two-process run procedure (webapp +
  worker); optional Task Scheduler autostart. Docker/compose optional, not required.
- **Backups (D-17):** the cache is an asset (hours of extraction) — a script zips
  `feature_cache.db` + `spectrograms/` on a schedule. Still gitignored, never
  committed.
- `/privacy` page; session TTLs verified; allowlist management *(corrected
  2026-07-09: dev-mode caps at **5 users** since Spotify's Feb-2026 policy, and
  extended quota is business-only — the manual allowlist is permanent; the
  landing page carries the invite-request notice)*.
- **Explicit non-goal:** no cloud migration until the PC is outgrown; when that
  day comes, `docs/SCALING.md` + `DATABASE_URL` are the prepared path.
**Accept:** an allowlisted tester on a phone, outside the home network, logs in
over HTTPS and gets the full experience served by the PC; deploy env holds no
Spotify secret; the cache survives a reboot and a restore-from-backup drill.

---

## 8. The analytics / ML dimension (portfolio core)

| Piece | Technique | Portfolio signal |
|---|---|---|
| Audio feature extraction | librosa DSP → 77-dim vector (frozen contract) | feature engineering on raw audio |
| Song buckets | KMeans + silhouette k; UMAP 2-D | unsupervised ML, deterministic + reproducible |
| Artist buckets | acoustic centroid per artist → cluster | derived features, not just tags |
| Acoustic signature | \|z\| vs cached population | interpretable per-user statistics |
| Nearest neighbors | z-scored distance now; pgvector when on Postgres | vector similarity, right-sized |
| Drift | RMS σ-shift on standardized centroids (D-9) | honest multivariate effect size |
| Spectrograms | librosa mel-spectrogram → PNG | signal processing, visual craft |
| Scale | Spark `local[*]`, parity-tested in CI | distributed engineering without cloud spend |
| Agent access | MCP + grounded RAG over the gold layer | AI agents on data infrastructure |

Plus the v2 meta-signal: **right-sizing** — SQLite/WAL at 25 users with a clean
abstraction to Postgres, one machine doing serving + extraction + training, and
a written migration path. Knowing what *not* to build is the senior skill.

---

## 9. Tech stack (v2)

| Concern | Choice | Note |
|---|---|---|
| Auth | Spotify **PKCE** (public client id only) | no secret anywhere (D-8) |
| Backend | **FastAPI** + Jinja (+ HTMX when refresh UX needs it) | React only if a view demands it (D-14) |
| Serving DB / cache | **SQLite + WAL** via SQLAlchemy; `DATABASE_URL` → local Docker Postgres+pgvector when needed | right-sized; zero-ops (D-12 amended) |
| Queue | **the `extraction_jobs` table** + polling worker | no queue service; the DB is the queue |
| Files | local `data/` (cache DB, spectrograms, Parquet) | backed up per D-17 |
| Batch / ML | Parquet medallion + **Spark `local[*]`**, scikit-learn, UMAP | zero cloud |
| Extraction | **yt-dlp + librosa** worker `--loop` on the PC | residential IP beats cloud IPs |
| LLM / RAG | deterministic fallback ($0) · optional Anthropic key · optional Ollama | D-5 holds |
| Hosting | **owner PC + free HTTPS tunnel** (+ owned domain via free DNS) | D-16; Cloud Run only post-outgrowth |

---

## 10. Roadmap (current)

1. ~~Epic A — cache + async extraction~~ ✅
2. ~~Epic B — hover + deep-dive + spectrogram~~ ✅
3. **Epic C — clustering (songs + artists) + acoustic signature + drift viz** ← next
4. **Epic E — self-host & share** (tunnel, worker loop, backups, privacy) — so real
   allowlisted users warm the cache from real traffic
5. **Epic D — RAG classification** (Phase 2, richest once C's clusters exist)
6. Polish pass (owner-flagged) — ongoing

Each epic lands in reviewable slices with synthetic tests (ground rule) and CI,
**pushed after every section** (owner cadence).

---

## 11. Key decisions (extends SPEC.md D-1…D-10)

| # | Decision | Rationale |
|---|---|---|
| **D-11** | Per-user extraction via a shared, track-keyed feature cache (supersedes P8's "visitors never trigger acquisition") | Every visitor gets real features; each song analyzed once, ever |
| **D-12** *(amended v2)* | **Serving DB = SQLAlchemy over SQLite+WAL (default) with `DATABASE_URL` → local Docker Postgres+pgvector as the upgrade; cloud DB only after outgrowing the PC.** Parquet+Spark stay the analytics plane | At ≤25 users / thousands of tracks, SQLite is the *correct* size: zero-ops, zero-cost, WAL handles the two-process (web + worker) pattern. The abstraction is already built — Postgres is a config change, not a rewrite |
| **D-13** | True longitudinal drift needs opt-in accounts + scheduled snapshots (PC Task Scheduler); until then drift = σ-shift across the 3 windows | Spotify exposes windows, not history — stay honest |
| **D-14** | FastAPI + Jinja (+ HTMX); React only if demanded | Lean stack, DE story front-and-center |
| **D-15** | Never store or serve audio — derived features + spectrograms only; extraction rate-limited, research-framed | Legal/ToS posture; audio transient by construction |
| **D-16** *(new v2)* | **Local-first: all development and hosting on the owner's PC at $0 external spend; public access via a free HTTPS tunnel; cloud (Cloud Run/GCS/BQ) is a documented migration path, not a build target** | Owner constraint; and yt-dlp genuinely works better from a residential IP than from cloud ranges — the riskiest layer *prefers* the PC |
| **D-17** *(new v2)* | **The cache is an asset**: `data/` stays gitignored, but the cache DB + spectrograms get a scheduled local backup | Features now embody hours of extraction work; "rebuildable" is true but expensive — a backup script is cheap insurance |

---

## 12. Risks & mitigations (v2)

| Risk | Mitigation |
|---|---|
| **YouTube ToS / copyright** on extraction | Derived features + spectrograms only, never audio (D-15); rate-limited, idempotent (once ever); allowlisted + research-framed; swappable if an official audio source appears |
| Extraction latency on a cold cache (5–30 s/track) | Async worker + shared cache; "analyzing…" UX; seed script pre-warms; residential IP maximizes acquisition success |
| **PC uptime** — the app is up only when the PC is | Acceptable and *stated* for an allowlisted pilot ("demo hours"); Task Scheduler autostart on reboot; the honest gate before any cloud move |
| **Home-network exposure** | Tunnel means **no inbound port-forward and the home IP is never published**; HTTPS end-to-end; sessions signed + TTL'd; no Spotify secret exists to leak (D-8) |
| SQLite single-writer limits | WAL + short transactions + a single worker process — correct at pilot scale; `DATABASE_URL` → Postgres is the pressure valve (D-12) |
| Data loss (disk failure eats the cache) | D-17 scheduled backups + restore drill in Epic E acceptance |
| Spotify Dev-Mode user cap — **5 since Feb 2026** (was ~25); extended quota now business-only (≥250K MAU) | Manual allowlist + the landing-page invite-request flow (email → owner adds in the dashboard → the pipeline handles the rest automatically). Existing users are grandfathered; the 5-seat list is the pilot's honest, permanent gate |
| LLM cost creep (if a key is set) | $0 deterministic default; key optional; cap `max_tokens`; Ollama documented as the free LLM path |
| Longitudinal drift over-claim | D-13 — 3-window σ-shift now; opt-in snapshots later; never claim a trajectory we don't have |

---

## 13. Non-goals & ground rules preserved

- **Bridge key `spotify_track_id` only** — cache, spectrogram filenames, vectors,
  cluster tables. No second ID system, ever.
- **No secrets — PKCE only** (D-8). Infra creds (session key, optional LLM key)
  are not the Spotify secret.
- **2026 API reality** — acoustic characteristics from local DSP only.
- **Synthetic-data tests** — extraction/cluster/drift logic tested without real
  API calls or downloaded audio (the worker tests run real DSP on generated signals).
- **Parquet for the warehouse; audio never committed/served** (D-15).
- **No cloud until outgrowth** (D-16) — and no orchestrator theater, no streaming
  pretensions (unchanged from SPEC.md).

---

## 14. "Officially ready" — definition of done for this phase

The app is ready to set aside when: an allowlisted tester, **outside the home
network, over HTTPS served from the owner's PC**, logs in and sees their top
songs & artists; the real audio features of their cached songs (hover +
deep-dive + spectrogram); an analytics dashboard clustering their songs and
artists with their acoustic signature and honest drift; and a grounded RAG
answer/classification — all from a shared feature cache that grew from real use,
**at $0 external spend**, with backups proven by a restore drill. Everything
past that (extended quota, cloud migration, richer longitudinal drift) is
enhancement, not blocker.
