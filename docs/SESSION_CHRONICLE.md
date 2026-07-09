# Session Chronicle — the build arc (2026-07-04 → 2026-07-09)

The narrative record of the marathon session that took this repo from "verified
pipeline" to "live product." **State lives in `notes/PROJECT_CONTEXT.md`** (always
current); this file is the story + index. New session? Run **`/resume`**.

## The arc, in order

| Phase | What happened | Proof |
|---|---|---|
| **P7 scale slice** | `spark/parity_check.py` + `spark-parity` CI job; caught Java 11-vs-17 (lock resolves pyspark 4.1.2). `docs/SCALING.md` | CI: dedup 30=30, 90=90, centroids <1e-3 |
| **P8 pilot** (SPEC.md, PRs #5–#6) | FastAPI webapp: session-scoped PKCE (no secret, D-8), dashboard, album art, top artists, taste drift, RAG `/ask` (D-5 fallback) | Live login: 41/41 overlap, drift 0.211σ |
| **APP_SPEC v1→v2** | Full product vision (Epics A–E, D-11…D-15); v2 = **local-first at $0** (D-16 PC+tunnel, D-12 SQLite+WAL, D-17 cache=asset) after owner constraint | `docs/APP_SPEC.md` |
| **Epic A** | Shared track-keyed feature cache (`src/store/`): SQLAlchemy cache, DB-as-queue, yt-dlp→librosa→spectrogram worker, dashboard wiring | seed 118 tracks; "N of M analyzed" |
| **Epic B** | Hover features, `/song/{id}` deep-dive: spectrogram + radar + "songs like this" | real 128KB spectrogram |
| **Epic C** | Population clustering (songs + artists via acoustic centroids), signature, cluster movement, the acoustic map, validated 6-color palette | 117→k=2 "Dark·Smooth"/"Bright·Noisy"; 59 artists |
| **Epic D** | Taste archetype: deterministic (home/breadth/motion) + grounded LLM narrative that can't rebrand | "The Drifting Dualist …Muse anchors it all" |
| **Epic E + GO-LIVE** | `/privacy`, WAL-safe backup+restore drill, `docs/SELF_HOSTING.md` (the $0 template). **DNS drama:** domain was DARK (deleted Google Cloud DNS zone behind Squarespace) → Cloudflare cutover RESTORED domain+email → cloudflared tunnel as a Windows service (registry ImagePath fix) | **`https://vercilloanalytics.com` live from the PC**; Epic E accepted via real login |
| **PR #7/#8 rescue** | PR #7 merged early; `git branch -d` upstream-rule footgun deleted 8 unmerged commits → restored by hash, PR #8, verified main **by content** | journal #15 |
| **VISION_SPECS + Epic F** | Two visions audited (KB review = 3 keeps + 2 rejections; A3 Ollama parked w/ validated 4070 Ti plan: gemma4:12b + num_ctx 8192). **F0** gold evals (15/15 vs baseline 0/15) + JSON contracts; **F1** `perceptual-v1` (5 measured/7 derived/1 experimental; "The Groove" tops danceability); **F2** `feature_stats` mart + audit drift flags; **F3** `/explore` dashboard (percentile chips, X×Y scatter) | 255 tests; chips "loudness above 72% of corpus" |
| **Polish** | 117/117 spectrograms, ♪ art tiles + letter avatars, 🎧 favicon + titles, www→apex 301, ask→explore link | live edge checks green |

## Hard-won lessons (full text: `notes/engineering_journal.md`)
#12 test the frozen env, not your PATH · #13 select columns by coverage, one ghost
row poisons intersections · #14 a DNS page is a claim; the authoritative NS answer
is the fact · #15 "merged" is a commit range, not a PR — verify content landed.

## The system today
- **Serving:** `vercilloanalytics.com` → Cloudflare tunnel (Windows service
  `cloudflared`) → uvicorn :8000 + worker `--loop`; SQLite+WAL
  `data/feature_cache.db` (117 tracks full features + perceptual + clusters +
  spectrograms); marts in `data/marts/`.
- **Quality:** 255 pytest (synthetic; golden evals = the CI guard for LLM
  surfaces), warehouse-audit (+ marts drift flags), ruff, 2-job CI on main.
- **Run:** `scripts/run_webapp.py` · `run_extraction_worker.py --loop` ·
  `seed_cache.py [--spectrograms]` · `train_clusters.py` ·
  `build_feature_marts.py` · `backup_cache.py` · `evals/run_golden.py`.
- **Docs:** APP_SPEC (vision) · VISION_SPECS (Epic F + A3 plan) · SELF_HOSTING
  (the $0 hosting template) · SCALING · AGENT_ACCESS · SPEC/P8_PLAN (historical).

## What remains (owner's fork)
1. **F-v2** — frame-level audio pass: time_signature, loudness-curve time series,
   instrumentalness (extractor addition + corpus re-run).
2. **Closeout** — DKIM/DMARC records, Task Scheduler autostart + nightly backup,
   delete orphaned GCP Cloud DNS zone, Spotify extended-quota + tester allowlist.
3. **A3** — Ollama local-LLM (plan validated in VISION_SPECS §A3).
