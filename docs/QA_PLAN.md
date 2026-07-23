# QA & bug-fix plan — Epic QA (owner ask, 2026-07-23)

Written at the end of a very long build session so the next one starts from
this file, not from a lost conversation. Everything below is either **verified
live** or an **open item with its evidence**.

## Where we are

**Phase 4.5 (Epic Q — provenance & QA), mid-epic.** Q1 (capture) ✅, Q2
(exposure) ✅, Q3 (the D-52 full re-extraction) ✅ **closed**, D-56 (owner
repair) ✅, D-57 (withhold unverified features) ✅. **Q4 (the QA loop) is the
next spec'd slice — this document is its input.**

Corpus truth (probed 2026-07-23, use these as the baseline):

| metric | value |
|---|---|
| canonical analyzed | **770** |
| source-validated (has provenance) | **724** |
| **unvalidated** (features withheld, D-57) | **46** |
| needs-source repair queue | **72** |
| flagged duplicate twins | 35 |
| track_meta rows | 847 |
| tests | **555 green** · app-verify ALL-FALSE · audits clean |

---

## A. Bugs found and FIXED this session (each needs a regression check)

These are done, but Q4 should verify them against **live data**, not just unit
tests — most were invisible to the suite and only appeared in production.

| # | Bug | Root cause | Fix | QA check |
|---|---|---|---|---|
| A1 | DJ-set audio stored as songs (19 tracks, up to 37× too long) | heuristic-v1 **ranks, never rejects** — with no true candidate the least-bad wins | duration guard vs Spotify's own length, pre-download + post-load backstop | no track's audio length >2× its Spotify duration |
| A2 | **Wrong songs entirely** (7 of the first 71 swaps) | duration match scores +25 with **no title requirement** | `title_affinity` gate; auto-accept needs a real title-token overlap | re-run the affinity sweep over all provenance → expect 0 |
| A3 | 27 wrong-song swaps **grandfathered** past the resume marker | a resume key records *that* work happened, not that it was correct (journal #46) | `quarantine_wrong_songs.py` (reuses the gate's own function) | the recheck is repeatable and finds 0 |
| A4 | Every repair silently failed at conversion | **Anaconda's ffmpeg** (no libmp3lame) shadowed the good build on the webapp's PATH; the first fix only *detected* it and handed yt-dlp back the same binary | resolver tries every candidate, picks the first that can encode MP3 | a link repair succeeds from the **webapp**, not just a shell |
| A5 | Repairs left **stale derived planes** | swap updated `TrackFeatures`; `/explore`, `/recommend`, chat read `track_perceptual` + marts | `refresh_derived()` after every successful repair | after a repair, all three planes agree |
| A6 | 20 MB cap made lossless masters impossible | D-45's cap was specced for **public** uploads; D-56 is owner-only | 120 MB, `WEBAPP_MAX_UPLOAD_MB` | a ~30 MB WAV master uploads |
| A7 | Owner repair tools hidden by the D-57 gate | the gate wrapped the whole analyzed block | tools moved outside the gate | unverified track still shows repair card |
| A8 | "117 bpm" vs "112 bpm" on the same audio | headline = `beat_track` periodicity; section = `60·beats/duration` **density**; both labelled "bpm" | hover reads "beats/min avg" + caption | no two figures share a label with different meanings |

---

## B. OPEN items for the QA session (ranked)

### B1 — the live worker still lacks the acquisition guards ⚠️ **highest**
`extractor.default_acquire` has **neither** the duration guard nor the affinity
gate — only the Q3 runner (`re_extract.guarded_acquire`) does. **This is how
the 19 DJ sets and the wrong songs entered originally**, so every new login or
playlist import can re-introduce exactly the bugs we just spent a session
removing. Fix: make `guarded_acquire` the shared acquisition path.
*Owner call pending only because it changes live ingestion behaviour.*

### B2 — should unvalidated features leave the AGGREGATES too?
D-57 withholds the 46 unvalidated tracks from **display** and from `similar()`,
but their features still feed clusters, `/explore` percentiles, `corpus_facts`
and the chat's SQL. Fullest reading of the owner's principle says exclude them;
cost is corpus 770 → 724 and **another archetype shift**. *Owner decides.*
Alternative: let the repair queue shrink it naturally, then re-ask.

### B3 — drain the 72-track needs-source queue (owner, at leisure)
`/library?filter=needs-source` → paste a link or upload audio. Each repair now
also refreshes the derived planes (A5). Two repairs proven live: "1, 2 Step"
(link) and "Roots" by WILDS (29.6 MB WAV master).

### B4 — the 6 long-duration tracks
`FEATURE_DISTRIBUTION` is true solely because 6 tracks exceed 1 h (longest
130 min). They pass title affinity, so they're plausibly real DJ-mix releases —
but they should be eyeballed and either confirmed or queued for repair.

### B5 — DUPLICATE_TRACKS advisory on the frozen star schema
10 near-dupe clusters in `dim_tracks` (the Jul-4 frozen warehouse plane, not
the serving corpus — O3 handles serving-side dedup). Decide: rebuild that
plane, or document it as intentionally frozen.

### B6 — error messages that lied
"download failed" when conversion failed cost the owner two blind retries. One
was fixed; **sweep the other user-facing failure strings** for the same
pattern (say what actually happened, not the nearest generic).

### B7 — deferred, unchanged
S4 DMARC `quarantine`→`reject` (owner's DNS, ~Jul-25 after clean reports) ·
O3d acoustic recall miner (post-Q3 vectors) · cluster_profile online-assign ·
`/chat` async-streaming.

---

## C. Proposed Q4 shape (the actual next build)

1. **QA1 — `scripts/qa_audit.py`**: one command that runs every A1–A8
   regression against LIVE data and prints a pass/fail table (affinity sweep,
   duration sanity, plane coherence for a sample, provenance coverage,
   label-collision check). This is the artifact that makes "is the corpus
   honest?" a 30-second question.
2. **QA2 — B1**, the shared guarded acquisition path (+ tests proving a DJ set
   and a wrong-title candidate are refused on the *live worker* path).
3. **QA3 — `review_provenance.py`** (the original Q4): stratified sample of the
   provenance mart + duration audit → aggregates-only dated health artifact in
   `evals/runs/`, mirroring the D-47 chat-review flywheel.
4. **QA4 — B2 decision + execution** (if the owner says exclude).

**Definition of done for Epic Q:** `qa_audit.py` green on live data · the
worker and the runner share one guarded acquisition path · a provenance health
report committed · the needs-source queue understood (drained or documented).
