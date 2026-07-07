# Vercillo Analytics — Full Application Spec & Long-Term Roadmap

**Status:** vision spec — 2026-07-07. Written now that the **P8 pilot is a working
demo** (PKCE auth → dashboard → acoustic overlap, drift, top artists, grounded
RAG `/ask`). This document defines the *long-term product* the pilot grows into.

**Relationship to existing docs.** `SPEC.md` (phases P0–P8, decision log D-1…D-10)
and `CLAUDE.md` (ground rules) remain in force — they are the foundation. This
doc **extends** them with the full-app product architecture and adds new
decisions (**D-11+**). Where this doc and SPEC.md's P8 non-goals differ (notably
"visitors never trigger acquisition"), **this doc supersedes for the long-term
app** — see §4 and D-11.

---

## 0. TL;DR

A public, PKCE-authenticated web app (no owner secret — D-8) where any listener:

1. **Sees their Spotify top songs & artists** across Spotify's three time windows
   (short / medium / long term — the only windows the 2026 API exposes).
2. **Sees the local-DSP audio features** of those songs — tempo, energy, timbre,
   77-dim acoustic vectors — **extracted from YouTube-sourced audio via librosa**,
   and **cached forever in a shared database** so no song is ever analyzed twice.
3. **Explores a data-science layer**: ML clustering of their songs *and* artists by
   acoustic features, taste-drift analytics across the time windows, a **mel-
   spectrogram per song**, and **hover-to-inspect + deep-dive** on any track.
4. **Gets a grounded RAG taste classification** (Phase 2): an archetype + narrative
   grounded strictly on their own clustered features and drift.

It is deliberately an **analytics-engineering showcase**: public APIs, audio
feature engineering (librosa), a medallion warehouse + Spark, ML clustering, a
serving database, and an agent-ready RAG layer — the exact surface a Data
Platform / Data Engineer loop wants to see.

---

## 1. Product vision (owner, 2026-07-07)

> "A user logs in, sees their top Spotify songs and artists by the periods
> Spotify allows, then views the **top audio features** extracted from those songs
> (YouTube WAV or any extraction method). A second dashboard shows **drift over
> time** and tried-and-tested attributes — really interesting bucketing of
> **similar artists via ML clustering**, and **bucketing songs in your top-3
> windows via clustering** on their audio features. A fun data-science project
> highlighting strong analytics-engineering, Spark, and feature engineering
> leveraging APIs and librosa. Include a **spectrogram of each song**. On polish:
> **hover a song → see its audio features**, click into a **deep dive**. **Cache
> all extracted features to a database** so we don't re-extract. **RAG
> classification** of the user's top songs as a Phase 2."

---

## 2. Users & core flows

| Flow | What the user does | What the app shows |
|---|---|---|
| **Login** | Authorizes their own Spotify (PKCE, `user-top-read`) | — |
| **Top items** | Lands on the dashboard | Top tracks + artists, per time window, with album art |
| **Audio features** | Views the features tab / hovers a track | Per-song acoustic features from the cache; "analyzing…" for misses |
| **Deep dive** | Clicks a song | Full 77-dim breakdown, **mel-spectrogram**, radar, nearest-neighbor "songs like this", its cluster |
| **Analytics** | Opens the analytics dashboard | Song clusters across the 3 windows, **artist clusters**, taste-drift trajectory |
| **Ask / classify** | Asks a question or requests a profile | Grounded RAG answer + (Phase 2) a taste archetype |

**Privacy invariant (D-7 preserved):** the user's *listening data* stays
session-ephemeral. The *feature cache* is **track-keyed and user-agnostic** — it
stores acoustics of songs, not who listened to them (see §6).

---

## 3. What exists today (honest baseline)

| Layer | Status |
|---|---|
| Pipeline P0–P7 (Spotify → YouTube → 77-dim librosa DSP → Parquet medallion → MCP), Spark parity, CI | ✅ on `main` |
| Song clustering (`analysis/clustering.py`: KMeans + silhouette, 77-dim, UMAP, coarse-genre buckets) | ✅ exists (owner corpus) |
| Taste drift (`analysis/drift.py`: RMS σ-shift, D-9) | ✅ exists |
| P8 pilot webapp (`src/webapp/`): PKCE auth, dashboard, **bridge-key overlap** insight, per-visitor drift, top artists, RAG `/ask` | ✅ built, verified live (PR #6) |
| **Per-user audio extraction** for arbitrary visitors | ❌ pilot reads the owner's 117-track corpus only |
| **Shared feature-cache database** | ❌ warehouse is Parquet files, not a serving DB |
| Artist clustering · spectrograms · hover/deep-dive · analytics dashboard · RAG classification | ❌ this spec |

The pilot proves auth, the feature-store join, drift, and grounded RAG. The full
app's central new work is **turning the owner-only corpus into a self-growing,
shared, per-user feature cache** — everything else builds on that.

---

## 4. The core architectural shift

The pilot's non-goal was *"visitors never trigger acquisition — they read the
owner's derived feature store."* The full-app vision requires the opposite:
**every visitor's songs get their real features**. The way to make that scale
(and stay cheap, polite, and legal) is a **shared, track-keyed feature cache**:

- On login, fetch the visitor's ~50 top tracks × 3 windows (≤150, fewer unique).
- **Cache lookup** each `spotify_track_id` in the database.
  - **Hit** → show real features instantly (the common case, grows over time).
  - **Miss** → enqueue for **async extraction**; show "analyzing…" and refresh.
- A miss extracted for *one* visitor is cached for *all* — popular tracks are
  analyzed once, ever. **Cache hit-rate rises with every user**: the classic
  "shared derived store" pattern, and a strong data-eng story.
- **Extraction never blocks a request.** A worker pool (Cloud Run Jobs pulling a
  queue) does yt-dlp → librosa DSP → 77-dim vector + mel-spectrogram → write DB.

This is idempotency (a ground rule) elevated to a multi-tenant serving cache.
**D-11** records the shift.

---

## 5. System architecture

```
 Visitor ──PKCE (no secret, D-8)──> FastAPI  (Cloud Run)
                                      │
      ┌───────────────────────────────┼───────────────────────────────┐
      │ ONLINE (per request)          │ user data ephemeral (D-7)      │
      │                               │                                │
      │  Spotify Web API ── top tracks/artists (short/med/long) ──┐    │
      │                                                           ▼    │
      │  cache lookup ─────────────────>  ┌──────────────────────────┐ │
      │                                   │  Postgres + pgvector     │ │  ← shared,
      │  hit → features + spectrogram ◄───│  track_features(77-dim   │ │    track-keyed,
      │                                   │   vector), spectrogram_  │ │    user-agnostic
      │  miss → enqueue ──────────┐       │   uri, cluster_id,       │ │
      │                           │       │  artist_profiles, models │ │
      │  analytics/RAG ◄──────────┼───────└──────────────────────────┘ │
      └───────────────────────────┼────────────────────────────────────┘
                                  ▼
                         ┌───────────────────┐
                         │ Extraction queue  │  (Cloud Tasks / Pub-Sub)
                         └─────────┬─────────┘
                                   ▼
                    Workers (Cloud Run Jobs): yt-dlp → librosa DSP
                    → 77-dim vector + mel-spectrogram → Postgres + GCS

 OFFLINE (batch):  Postgres ──snapshot──> GCS Parquet medallion ──> Spark
   (feature_transform · KMeans/HDBSCAN clustering · drift · artist centroids)
   ──> cluster models + assignments written back to Postgres.  MCP agent reads gold.
```

**Two data planes, one bridge key.** Postgres = **online serving + cache**
(low-latency point lookups, pgvector similarity). Parquet/GCS + Spark = **offline
analytics + ML training** (clustering, drift, heavy compute). They stay in sync
by snapshot; both are keyed on `spotify_track_id` (never a second ID — ground
rule). See **D-12**.

---

## 6. Data model (Postgres serving DB)

Track-keyed and user-agnostic (privacy invariant). Feature columns follow the
**exact 77-dim / 82-column DSP contract** already frozen (`clustering.py`
`VECTOR_77_COLUMNS`, `serializer.to_summary_dict`) — the cache does not invent a
new schema.

| Table | Key | Holds |
|---|---|---|
| `track_features` | `spotify_track_id` | 77-dim `vector(77)` (pgvector) + the 82 named feature cols, `dsp_version`, `extraction_source`, `extracted_at`, `spectrogram_uri` (GCS) |
| `track_meta` | `spotify_track_id` | name, primary artist id, album, isrc, duration_ms |
| `artist_meta` | `artist_id` | name, genres, followers, image_uri |
| `artist_profiles` | `artist_id` | **acoustic centroid** `vector(77)` (mean of the artist's cached tracks), `cluster_id` |
| `song_cluster_model` / `artist_cluster_model` | version | k, centroids, silhouette, `trained_at` (models are versioned artifacts) |
| `extraction_jobs` | `spotify_track_id` | `status` (queued/running/done/failed), attempts, requested_at, last_error |

- **`pgvector`** gives free nearest-neighbor: "songs like this," "artists like
  this," and cluster assignment — the engine behind the clustering vision.
- **User listening data is never stored** — top-track lists are fetched fresh per
  login and held only in the session (D-7). The cache stores *songs*, not *people*.
- **Longitudinal drift caveat (important):** Spotify exposes only 3 fixed windows,
  not raw history. *True* drift-over-time (a monthly trajectory) requires
  **snapshotting a consenting user's top tracks over time** — which needs opt-in
  accounts + a scheduled job (**D-13**). Until then, "drift" = the σ-shift across
  the 3 windows (already built), framed honestly as a 3-point trajectory.

---

## 7. Feature epics

### Epic A — Feature cache DB + per-user async extraction *(foundational)*
The unlock for everything else. Postgres+pgvector schema; cache read/write;
extraction worker (yt-dlp → librosa → 77-dim + spectrogram → DB/GCS); queue;
"analyzing… N of M done" dashboard state with refresh; shared track-keyed cache.
**Accept:** a returning visitor's already-cached songs render instantly; a new
song is enqueued, extracted once, and served to every later visitor; audio bytes
are never stored or served — only derived features + the spectrogram PNG.

### Epic B — Audio-features dashboard (the "features & drift" polish)
Per-song features from the cache; **hover a track → tooltip** (tempo, energy,
key, brightness); **deep-dive page** per song: full 77-dim breakdown, **mel-
spectrogram**, radar chart, pgvector **nearest-neighbor "songs like this,"** and
its cluster. **Accept:** hovering any cached track shows its features; the
deep-dive renders the spectrogram + neighbors for any cached song.

### Epic C — Analytics & drift dashboard (the data-science showcase)
- **Song clustering** across the 3 windows: KMeans/HDBSCAN on 77-dim features →
  each top song placed in an acoustic cluster; a UMAP map colored by cluster;
  drift shown as songs *moving between clusters* short→long term.
- **Artist clustering**: derive an **acoustic centroid per artist** (mean of the
  artist's cached track features), cluster artists in that space (genre as a
  secondary signal) → "artists who *sound* alike, not just tagged alike."
- **Drift dashboard**: the σ-shift (D-9) as a headline + per-feature deltas ("your
  recent listening is 12% faster, brighter") + the cluster-movement view.
- Runs on Spark at corpus scale; scikit-learn for per-user online clustering.
**Accept:** a user sees their songs and artists bucketed with a readable label
per cluster, and a drift readout that is non-tautological and grounded.

### Epic D — RAG taste classification *(Phase 2)*
Beyond `/ask`: classify the user's taste into an **archetype** and a short
narrative, grounded strictly on their clustered features + drift + top items
(reuses the P8 RAG core; deterministic fallback holds — D-5). **Accept:** the
profile cites the user's real clusters/features/artists and invents nothing.

### Epic E — Deploy & harden
Containerize (Dockerfile); Cloud Run + `vercilloanalytics.com`; `/privacy` page;
allowlist + extended-quota request; opt-in accounts + scheduled snapshots for
real longitudinal drift (D-13). **Accept:** SPEC P8 acceptance met on the public
URL, no Spotify secret in the deploy env, sessions expire, privacy note published.

---

## 8. The analytics / ML dimension (portfolio core)

| Piece | Technique | Portfolio signal |
|---|---|---|
| Audio feature extraction | librosa DSP → 77-dim vector (frozen contract) | feature engineering on raw audio |
| Song buckets | KMeans + silhouette-chosen k; UMAP 2-D; HDBSCAN option | unsupervised ML, deterministic + reproducible |
| Artist buckets | acoustic centroid per artist → cluster | derived features + aggregation, not just tags |
| Nearest neighbors | pgvector cosine/L2 on 77-dim | vector search / similarity |
| Drift | RMS σ-shift on standardized centroids (D-9) | multivariate effect size, honest metric |
| Spectrograms | librosa mel-spectrogram → PNG | signal processing, visual craft |
| Scale | Spark feature_transform + parity-tested jobs | distributed data engineering |
| Agent access | MCP + grounded RAG over the gold layer | "AI agents on data infrastructure" |

Every dashboard element traces to a real acoustic feature — the whole product is
"your taste, in the language of the audio itself."

---

## 9. Tech stack

| Concern | Choice | Note |
|---|---|---|
| Auth | Spotify **PKCE** (public client id only) | no secret anywhere (D-8) |
| Backend | **FastAPI** + Jinja + **HTMX** for hover/refresh | React only if interactivity demands it (D-14) |
| Serving DB / cache | **Cloud SQL Postgres + pgvector** | point lookups + similarity; first stateful infra (D-12) |
| Object store | **GCS** | spectrogram PNGs + Parquet warehouse |
| Batch / ML | **Parquet medallion + Spark**, scikit-learn, UMAP | clustering/drift training at scale |
| Extraction | **yt-dlp + librosa**, Cloud Run Jobs + a queue | async, shared cache, rate-limited |
| LLM / RAG | **Anthropic** (`claude-opus-4-8`, `WEBAPP_LLM_MODEL` override) | grounded; deterministic fallback (D-5) |
| Deploy | **Cloud Run** + custom domain | no Spotify secret in env |

---

## 10. Roadmap (build order)

1. **Epic A** — cache DB + async extraction *(foundational; do first)*
2. **Epic B** — audio-features dashboard + hover + deep-dive + spectrogram
3. **Epic C** — clustering (songs + artists) + drift dashboard
4. **Epic E (partial)** — Dockerfile + Cloud Run early, so real users seed the cache
5. **Epic D** — RAG classification (Phase 2)
6. **Epic E (full)** — domain, allowlist, opt-in longitudinal snapshots, privacy

Ship A→B behind the allowlist first so the cache warms on real traffic; layer C/D
on the growing cache; harden in E. Each epic lands in reviewable slices with
synthetic tests (ground rule) and CI.

---

## 11. Key decisions (new — extends SPEC.md D-1…D-10)

| # | Decision | Rationale |
|---|---|---|
| **D-11** | **Per-user extraction via a shared, track-keyed feature cache** (supersedes P8's "visitors never trigger acquisition") | The vision needs every visitor's real features; the shared cache makes it scale (analyze each song once, ever) and stays polite/cheap |
| **D-12** | **Two data planes: Postgres+pgvector (online cache/serving) + Parquet/Spark (offline analytics/ML), synced by snapshot, one bridge key** | Parquet can't do concurrent row upserts or low-latency lookups; a DB can. pgvector adds similarity search. Analytics/Spark stay on Parquet |
| **D-13** | **True longitudinal drift requires opt-in accounts + scheduled snapshots**; until then drift = σ-shift across Spotify's 3 windows | Spotify exposes 3 fixed windows, not history — be honest; real trajectories need consented persistence |
| **D-14** | **Stay FastAPI + Jinja + HTMX**; adopt React only if a view demands rich client state | Server-rendered is enough for hover/deep-dive; keeps the stack lean and the DE story front-and-center |
| **D-15** | **Never store or serve audio — only derived features + spectrogram images**; extraction rate-limited and research-framed | Legal/ToS posture (see §12); consistent with the existing "MP3s never committed" rule |

---

## 12. Risks & mitigations

| Risk | Mitigation |
|---|---|
| **YouTube ToS / copyright** on extracting audio for many users' songs | Store **only derived features + spectrograms**, never audio (D-15); rate-limit + idempotent cache (analyze once); keep the pilot **allowlisted + research-framed**; document the posture; design so an official audio-analysis source can replace YouTube if one appears |
| Extraction cost/latency (cold cache, 5–30 s/track) | Async workers + shared cache (hit-rate climbs); "analyzing…" UX; pre-warm popular tracks; the **derived store is the artifact**, audio is transient |
| Spotify Dev-Mode ~25-user cap | Ship allowlisted; submit + document the extended-quota request (honest gate, SPEC P8) |
| Longitudinal drift over-claim | D-13 — 3-window σ-shift now, opt-in monthly snapshots later; never claim a trajectory we don't have |
| First stateful infra (Postgres) raises ops burden | Managed Cloud SQL; keep schema tight; synthetic tests + migrations; Parquet/Spark path unchanged |
| Cold-start empty cache for a new user | Show cached subset instantly + progress; seed the cache with popular tracks; overlap insight still works from the owner corpus |

---

## 13. Non-goals & ground rules preserved

- **Bridge key `spotify_track_id` only** — the DB, cache, spectrogram names, and
  vectors all key on it. No second ID system, ever.
- **No secrets — PKCE only** (D-8). Infra creds (session key, DB password,
  optional LLM key) are not the Spotify secret.
- **2026 API reality** — acoustic characteristics come from **local DSP only**;
  `/audio-features` and `popularity` stay gone.
- **Synthetic-data tests** — extraction/cluster/drift logic tested without real
  API calls or downloaded audio.
- **Parquet for the warehouse; audio never committed/served** (D-15).
- **Not streaming, not multi-tenant-at-rest by default** (user data ephemeral,
  D-7; the cache is song-keyed, not person-keyed).

---

## 14. "Officially ready" — the definition of done for this phase of work

The app is ready to set aside when: a logged-in allowlisted user sees their top
songs & artists, the **real audio features** of their cached songs (with hover +
deep-dive + spectrogram), an **analytics dashboard** clustering their songs and
artists and showing drift, and a **grounded RAG answer/classification** — all
served from a **shared feature cache** that grew from real use, deployed on Cloud
Run with no Spotify secret. Everything past that (richer longitudinal drift,
scale, extra polish) is enhancement, not blocker.
