# Phase 2 — the roadmap after the demo

**Written 2026-08-12, at the end of the session that made the project
demonstrable.** Phase 1 is complete in the sense that mattered: a colleague can
open a link, find the interesting parts without narration, and leave with the
right impression of what was built.

This document exists because the backlog that carried Phase 1 is **gone** —
D-75 declined Phase 5 and parked the ML track, and the remaining epics are
blocked or cut for stated reasons. Anything after this is a new commitment, and
should be made deliberately rather than by picking up whatever was left in a
list built for a different goal.

> **The honest starting position: you do not have to build anything.** The
> project demonstrates what it was meant to demonstrate. Every track below is
> optional and each one names the door it opens, so the choice is about which
> door you want.

---

## Where Phase 1 ended

| | |
|---|---|
| Corpus | ~1,900 analysed tracks · ~900 artists · 83 features each |
| Surfaces | library · song · **83-feature drill-down** · artists · artist deep-dive · explore · analytics · **eras** · chat · **how-it-works** · MCP server |
| Warehouse | staging → cleansed → modeled → 15 marts, **two fact grains** |
| Gates | ~1,000 tests · 26 data-quality flags · route × persona matrix · docs whose numbers are generated |
| Models | clustering (null-tested, real but weak) · similarity (evaluated, whitening shipped) |
| Deploy | one click, with a `Code STALE` line that cannot lie |

**What is deliberately absent**, each for a recorded reason: Phase 5
AcousticBrainz (D-75), the ML track (label-limited, D-75), MPD (licence,
verified twice), FAISS vector search (deleted, `DELETIONS.md`), threaded
acquisition (D-74, measured), Spark at scale (no real data to justify it).

---

## The five doors

Each track states the **condition that makes it worth starting**. If the
condition is not true, the track is not ready — that is the point of writing
them this way rather than as a priority list.

### Track A — Reliability & auditability *(the interview door)*

**Start if:** you want the platform-engineering story to be the strongest thing
in the repo.

The one unsurfaced asset left. `track_provenance` covers ~97% of the corpus and
`extraction_jobs` records a **~11% failure rate** that has never appeared
anywhere.

| Slice | What it builds | Proves |
|---|---|---|
| A1 | `/reliability` — coverage, failure rate by cause, matcher-confidence distribution | you measure your own pipeline's failures |
| A2 | Dead-letter view: the 248 failed jobs, *why*, and what a retry would cost | you treat failure as data, not noise |
| A3 | Freshness SLA per mart — built_at, staleness, what depends on what | lineage as a product surface, not a diagram |

**Effort:** ~2 sessions. **Risk:** low, all read-only.
**Why it's first among equals:** *"here is my 11% failure rate"* is the single
most credible thing a platform candidate can put on screen, and almost nobody
does it.

### Track B — Label supply, then the ML revival

**Start if:** you have imported 50+ curated playlists, or a second person's
library is in the corpus.

The ML track was parked because the constraint was **measured** as label
supply, not modelling: 29 curated playlists give 93 seeds in the stratum that
matters, which cannot adjudicate a feature change. Nothing about the model has
changed; the evidence base is simply too thin.

| Slice | What it builds |
|---|---|
| B1 | Bulk curated-playlist import (public playlists by URL), with the library-dump filter |
| B2 | Re-run the harness; the delta on the obscure stratum is the whole result |
| B3 | Only if B2 shows the stratum has real power: revisit feature selection through `nested_feature_selection()` |

**Effort:** 1 session for B1–B2. **Do not skip B2.** The reason to import
playlists is to find out whether more labels change the answer, and if they
do not, B3 must not happen.

### Track C — Scale, legitimately *(the Spark door)*

**Start if:** you want a distributed-compute artifact and are willing to build
the fence first.

ListenBrainz publishes a **CC0 Spark-shaped dump**, joinable through the ISRC
bridge that D-70 already put at 100%.

⚠️ **The fence is not optional and comes first.** `canonical_ids()` is a single
population definition feeding percentiles, the KMeans fit, `corpus_facts` and
the chat; and `ExtractionJob` has **no source column**. Enqueue external ids and
the worker writes them into `track_features`, silently re-fitting the clustering
so every visitor's archetype changes with no error.

| Slice | What it builds |
|---|---|
| C0 | **The fence** — separate lake + DB, `corpus_source` at enqueue *and* persist, an `EXTERNAL_LEAKAGE` audit flag, and a tripwire asserting mart row counts and all 13 similarity-column medians stay bit-identical when an external row is inserted |
| C1 | ListenBrainz intake, MBID → ISRC → bridge key, with a coverage report |
| C2 | The genuine Spark job — full within-playlist self-join, ~10⁹ interaction rows |

**Effort:** ~3 sessions. **Honest caveat:** even at that scale one machine
finishes in hours. The artifact is the *pipeline*, not the necessity.

### Track D — Product depth *(the "you built that?" door)*

**Start if:** the demo goes well and people ask for their own.

| Slice | What it builds |
|---|---|
| D1 | Analyse-on-stage: a demo-safe path to queue an unanalysed track and watch it appear in ~15 s |
| D2 | More PKCE seats, or a queue-and-notify flow for people without one |
| D3 | Chat warm-start + seeded example questions as buttons — the cold-model latency is the demo's biggest live risk |

**Effort:** 1–2 sessions. **Highest wow-per-hour of anything here**, and the
least architecturally interesting. That trade is the point.

### Track E — The harness itself *(the meta door)*

**Start if:** you want the transferable artifact rather than the music one.

The most reusable thing built here is not the pipeline — it is the **way it was
built**: session memory, a numbered decision log, an engineering journal of
surprises, generated documentation, a director review that red-teams the
author, and a quality ledger tracking how defects were found.

| Slice | What it builds |
|---|---|
| E1 | Extract the harness as a standalone template repo (`repo-bootstrap` already gestures at this) |
| E2 | A written case study on AI-assisted engineering discipline, using this repo's own reversals as evidence |
| E3 | The `grill-me` loop run properly, with the gaps fed back here |

**Effort:** 1–2 sessions. **This is the one most likely to matter at work**,
because colleagues can use it and a music corpus is not transferable.

---

## What is NOT in Phase 2, and why

| Not doing | Reason |
|---|---|
| Phase 5 AcousticBrainz | D-75 — 7 sessions and 3 owner gates for a number no colleague asks about |
| MPD | Licence, verified twice; also 39% of the corpus post-dates its 2017 freeze |
| Re-adding FAISS | Exact k-NN is 7.7 ms; revisit at ~25k tracks, and prefer `pgvector` over a sidecar index |
| Threaded acquisition | D-74 — measured: ~75–80% of the per-track budget is local CPU, and the queue is empty |
| More tests for their own sake | ~1,000 with CI green is past the point of return |
| Instrumentalness, K4, K5/K6, Epic M | Blocked or appetite-gated, unchanged |

---

## How to choose

Run **`/grill-me`** first. It is designed to end with a list of *questions you
could not answer because the work does not exist yet* — and those are better
roadmap input than anything written in advance, including this document.

If you want a recommendation without that: **A → E → D**. Reliability is the
most credible thing you can show a platform interviewer, the harness is the
most transferable thing you can show a colleague, and product depth is the most
fun. B and C are both real, and both should wait for their condition to be true
rather than being started because they are the biggest.

---

## The rule this project earned

Every track above states what would make it worth starting, and several state
what would make it *not* worth finishing. That is the discipline Phase 1
actually taught — measured in a session where a 14% improvement was rejected
because an untouched holdout said −11%, and a spec's ten invariants were
declined because nobody had measured its one premise.

> Do not start a track because it is next. Start it because its condition is
> true, and stop it when the evidence says stop.
