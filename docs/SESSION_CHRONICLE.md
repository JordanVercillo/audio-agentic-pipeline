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
| **New-user pipeline hardening** (2026-07-09) | Proved the visitor flow live (uncached track queued→done in 52 s), then closed its silent-failure gaps: worker heartbeat + WORKER_DOWN/QUEUE_STUCK flags, crash-orphan re-queue, post-drain mart refresh (new tracks reach /explore unattended), seed ghost guard (+ deleted the seeded ghost row — journal #17), `register_autostart.ps1` | 264 tests; the new flag caught its own blind spot on first run (journal #16) |
| **Click-to-run + on-demand** (2026-07-09, Opus) | `start_app`/`stop_app`/`status_app.bat` → `app_control.ps1` (idempotent start, script-name-matched stop, **backup-on-stop**). Owner runs on-demand, not 24/7 | app restored + verified ALL-GREEN via the scripts |
| **Email → $0** (2026-07-09) | Dropped paid Google Workspace for free **Cloudflare Email Routing**; `jordan@vercilloanalytics.com` catch-all → personal inbox; MX+SPF+DKIM+DMARC live; invite CTA switched. Domain wears 3 free hats (site / Microsoft-Entra identity / CF email) | forwarding proven end-to-end (journal #14 ethos: authoritative DNS) |
| **Epic F-v2** (2026-07-09) | **F-v2a** within-track loudness curve on the song page (rebuilds get-audio-analysis); **F-v2b** estimated `time_signature` as a measured /explore feature (catalog 13→14). Both = promoted cache columns (vector/82-col contract untouched), backfilled 117/117 from LOCAL MP3s (no re-download) | 277 tests; forward-only migration (journal #18); backbeat-as-2/4 honesty fix (journal #19) |

## Hard-won lessons (full text: `notes/engineering_journal.md`)
#12 test the frozen env, not your PATH · #13 select columns by coverage, one ghost
row poisons intersections · #14 a DNS page is a claim; the authoritative NS answer
is the fact · #15 "merged" is a commit range, not a PR — verify content landed ·
#16 a queue without a monitored consumer fails silently — audit every process the
promise depends on · #17 at a system boundary, copy meanings, not rows · #18 a
green suite proves your CREATE path, not your ALTER path · #19 when an estimate
surprises on real data, ask if the signal supports the distinction before
"fixing" the model — sometimes honesty is a narrower claim.

## The system today
- **Serving:** `vercilloanalytics.com` → Cloudflare tunnel (Windows service
  `cloudflared`) → uvicorn :8000 + worker `--loop` (heartbeats to the DB;
  app-verify flags WORKER_DOWN/QUEUE_STUCK); SQLite+WAL
  `data/feature_cache.db` (118 tracks full features + perceptual + clusters +
  spectrograms + loudness curves + meter; 119 metas); marts (14 features) in
  `data/marts/`, auto-refreshed by the worker after each successful drain.
- **Run mode:** ON-DEMAND (owner's choice) via `start_app`/`stop_app`/
  `status_app.bat` (→ `app_control.ps1`; stop backs up the cache). Not 24/7;
  autostart tasks deferred to the future dedicated server.
- **Email ($0):** `jordan@vercilloanalytics.com` = free Cloudflare Email Routing
  catch-all → personal inbox (MX/SPF/DKIM/DMARC live). The domain also carries a
  free Microsoft Entra identity (Power BI) — independent of MX. Workspace being
  cancelled.
- **New-visitor flow (proven live):** login → dashboard queues cache misses →
  worker yt-dlp → 77-dim DSP + spectrogram → cache → marts refresh; observed
  52 s queued→done. Front gate: Spotify dev-mode allowlist — **5 seats**
  (Feb-2026 policy), manual dashboard adds ONLY (no API); the landing page
  carries an invite-request notice (jordan@vercilloanalytics.com).
- **Quality:** **277 pytest** (synthetic; golden evals = the CI guard for LLM
  surfaces), warehouse-audit (+ marts drift flags), app-verify (worker
  liveness), ruff, 2-job CI on main — all green.
- **Run:** `run_webapp.py` · `run_extraction_worker.py --loop` ·
  `start_app.bat`/`stop_app.bat` · `register_autostart.ps1` (optional) ·
  `seed_cache.py [--spectrograms]` · `train_clusters.py` ·
  `build_feature_marts.py` · `backfill_loudness.py` · `backfill_time_signature.py` ·
  `backup_cache.py` · `evals/run_golden.py`.
- **Docs:** APP_SPEC (vision) · VISION_SPECS (Epic F + A3 plan) · SELF_HOSTING
  (the $0 hosting/email template) · SCALING · AGENT_ACCESS · SPEC/P8_PLAN (historical).

## What remains (owner's fork)
1. **F-v2c — instrumentalness** (the only unbuilt F-v2 slice). Deliberately last:
   summary stats can't see vocals (F1 deferral), and journal #19 reinforced it.
   An honest version needs source separation (HPSS-based vocal-presence proxy,
   labeled *experimental*), or keep it parked.
2. **Owner cost-cleanup (manual, non-blocking):** cancel the Google Workspace
   subscription (email already on Cloudflare); delete the orphaned GCP Cloud DNS
   zone (~$0.20/mo). *(Extended Spotify quota is DEAD — business-only ≥250K MAU;
   the 5-seat allowlist is permanent. Autostart/backup are scripted but
   deferred by choice — on-demand + backup-on-stop covers it.)*
3. **A3 — Ollama local-LLM** (plan validated in VISION_SPECS §A3): $0 real LLM
   answers for `/ask` + `/classify`, guarded by the F0 golden evals. Own epic.
4. **Later polish:** DMARC `p=none` → `quarantine` → `reject` once reports are
   clean; F-v2a loudness curve could also land on the /explore or analytics view.
