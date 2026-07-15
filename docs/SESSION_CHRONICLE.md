# Session Chronicle — the build arc (2026-07-04 → 2026-07-11)

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
| **F-v2c** (2026-07-09) | Fade-in/out (pure over the stored loudness curve, zero backfill) + bar grid (every meter-th real beat) on the song page | 281 tests; depth-gate tuning → fade-out>fade-in asymmetry = honesty signal (journal #21) |
| **Security + robustness review** (2026-07-09/10) | Whole-app audit (2 review subagents + strategic pass) then the backlog cleared: XSS-escape in |safe SVGs, worker dead-letter + poll-loop guard, /spectrogram gate, www→apex ALLOWLIST (open-redirect), POST logout, track-id guard, single-instance worker lock, FEATURE_DISTRIBUTION audit + population_n, ops sweep (anchored process-kill, CI perms) | 299 tests; journals #22 (review method), #23 (the lock's first victim = its own restart) |
| **Ingestion live-progress** (2026-07-09) | Validated the flow already met 3 asks; built cache-only `GET /status` + dashboard poller (bar, ETA, current song by name) — no Spotify re-hit, textContent no-XSS | 290 tests |
| **Slice P — popularity** (2026-07-10) | `popularity` verified deprecated-NOT-removed (journal #20) → captured as fetched CONTEXT (never ML); "taste vs popularity" line on /analytics + RAG grounding; 3 over-cautious docs (incl. CLAUDE.md rule 3) corrected; backfilled 119/119 in 3 /tracks calls | 304 tests; meter-hunt cross-check = F-v2b's 17 3/4-tracks |
| **F-v3 — structure timeline** (2026-07-10) | Rebuilt get-audio-analysis' sections[] via simplified Laplacian segmentation (recurrence on chroma+MFCC + path graph, eigengap k); section ribbon on the song page (same letter/color = repeat; NO chorus/verse claims); 117/117 backfilled locally | 311 tests; validate-on-3-levels (journal #24: KoC read as 1 section under chroma-only → +MFCC) |
| **Epic G — recommendation explorer** (2026-07-10/11) | Rebuilt the retired /recommendations transparently: min/max/target tunables over our 14 features + popularity, seed-track "more like this" (visible targets), z-distance ranking, cluster chips; `/recommend` + nav + song-page seed link | 325 tests; browser-validated live |
| **A3 — Ollama local LLM** (2026-07-11) | `/ask`+`/classify` answer via a LOCAL model ($0, no key): `WEBAPP_LLM_MODEL=ollama:gemma4:12b`, format=json, num_ctx 8192, startup warm-up. The F0 evals graded gemma4 5→9/15 (paraphrases, not hallucinations) → owner shipped it as default with the deterministic path as safety net | 330 tests; journal #25 (evals over vibes) |
| **⑥ loudness arc on /analytics** (2026-07-11) | Corpus roll-up of the F-v2 within-track loudness: "Your typical track's loudness arc" — the MEDIAN normalized loudness *shape* + middle-50% IQR band across the visitor's tracks (distinct from the absolute "Loudness" signature dim). `cache.loudness_curves` bulk getter + pure `average_loudness_arc`/`loudness_arc_svg`, wired before the model block (no clusters needed) | 333 tests; journal #26 (the band brackets the median, not the mean) |
| **The public era + harness v2** (2026-07-11/12) | DMARC→`quarantine`; **first real pilot user** (the first pilot user: cache 118→159, 0 fail); **guest demo persona** — "View as guest" loads the owner's snapshot → the full analytics with NO login (the interview showpiece); Vision C/D specced (public corpus D-18, MPD metadata-only D-26, dedup D-28). **Harness v2:** `/wrap-session` + `/orchestrator` + 4 domain-expert agents (data-platform/webapp/dsp/llm-rag). **Vision D Phase 1 (orchestrated, 8/8 COMPLETE):** B1 seed-fix · popularity-on-hover · mobile cut-off sweep · N1 σ/stats explainers · N2 12-archetype taxonomy · **O1 dedup-as-flag** (stdlib `dedup.py` + DUPLICATE_TRACKS audit + cache guards; 10 real dupes flagged live, D-28 flag-not-delete) | 353 tests; journals #26 (median+IQR) / #27 (derive, don't re-type) / #28 (z-scored cosine degenerate at n=2) |
| **Vision E specced — the product era** (2026-07-14) | Owner re-scope → Phases 3–6 (D-32…D-39): P3 = Artists+genres · Library tabs · playlists · guest dashboard · public-flip EXIT GATE; P4 = Epic K (chat+multimodal builds, adapters/RL gated); P5 = MPD; P6 = ML. New agents `research-expert`+`agile-coach`; first research outing → `docs/SPOTIFY_API_RESEARCH.md` — **artist top-tracks REMOVED "no replacement"** → derive "YOUR top by artist" as core, live call = absent-safe garnish (the borrowed-time doctrine); 5-seat cap = platform ceiling; playlists own+collaborative only | spec-only (a5298d0); journal #29 (research the surface before you spec) |
| **P3.0–P3.2 — groundwork + the Artists surface** (2026-07-15) | Fetchers hardened (absent-safe artist records, singles fallback, playlist 50/page+`items` fallbacks, search 10) · `_TOP_LIMIT=50` (the "why 39 songs" fix) · guardrails wave 2 · `artist_meta` serving path (60 seeded, 29 w/ genres) · **the Artists surface live**: `/artists` (cards+genre chips+coverage honesty+comparison chart) + `/artist/{id}` (D-33 derived core · borrowed-time live top-10 · acoustic "similar in your library" — Muse→Metric Δ1.46σ · analyze-on-demand) + D-35 two-group nav | 375 tests; browser-validated on real data; the first Vision-E product surface |

## Hard-won lessons (full text: `notes/engineering_journal.md`)
#12 test the frozen env, not your PATH · #13 select columns by coverage, one ghost
row poisons intersections · #14 a DNS page is a claim; the authoritative NS answer
is the fact · #15 "merged" is a commit range, not a PR — verify content landed ·
#16 a queue without a monitored consumer fails silently · #17 at a system
boundary, copy meanings, not rows · #18 a green suite proves your CREATE path,
not your ALTER path · #19 when an estimate surprises, ask if the signal supports
the distinction before "fixing" the model · #20 audit your OWN guardrails against
reality (popularity wasn't removed) · #21 validate an estimator by its corpus
distribution, not just unit tests · #22 the strategic review predicts where the
code bugs are · #23 test a safety interlock against the system's own lifecycle
(the lock's first victim is its own restart) · #24 validate on three levels —
synthetic fixtures (logic), corpus distributions (stats), named examples you know
(meaning) · #25 build the eval before the thing it judges, and believe it when it
fights your gut · #26 a central line and its spread band must be drawn from the
same order statistics — median+IQR, not mean+IQR (a "surely-true" invariant that
failed taught which summary I meant).

## The system today (2026-07-11)
- **Serving:** `vercilloanalytics.com` → Cloudflare tunnel (Windows service
  `cloudflared`) → uvicorn :8000 + worker `--loop` (heartbeats to the DB;
  single-instance lock; app-verify flags WORKER_DOWN/QUEUE_STUCK); SQLite+WAL
  `data/feature_cache.db` (118 tracks: features + perceptual + clusters +
  spectrograms + loudness curves + meter + beat grid + **sections** +
  **popularity**; 119 metas); marts (14 features) in `data/marts/`,
  worker-refreshed after each drain.
- **The app rebuilds BOTH retired Spotify endpoints + more:** audio-features
  (14-feature `/explore` catalog) · audio-analysis (spectrogram + loudness curve
  + fades + bar grid + **section ribbon** on the song deep-dive; a **loudness
  arc** — median shape + IQR band — rolled up on `/analytics`) · a transparent
  **recommendation explorer** (`/recommend`: tunables + seed) · **taste-vs-
  popularity** on `/analytics` · **local $0 LLM** `/ask`+`/classify` (Ollama
  gemma4:12b, deterministic fallback as safety net) — all evals/audit-guarded.
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
- **Quality:** **333 pytest** (synthetic; golden evals guard the LLM surfaces),
  warehouse-audit (marts drift + FEATURE_DISTRIBUTION), app-verify (worker
  liveness), ruff, 2-job CI on main — all green. Run mode: ON-DEMAND via the
  click scripts (owner's choice, not 24/7). Email: $0 Cloudflare Email Routing.
- **Run:** `start_app.bat`/`stop_app.bat`/`status_app.bat` (→ `app_control.ps1`)
  · `run_webapp.py` · `run_extraction_worker.py --loop` · `seed_cache.py` ·
  `train_clusters.py` · `build_feature_marts.py` · `backfill_{loudness,
  time_signature,beat_times,sections,popularity}.py` · `backup_cache.py` ·
  `evals/run_golden.py [--llm]`.
- **Docs:** APP_SPEC (vision) · VISION_SPECS (Epic F + the sequenced roadmap +
  A3 done) · SELF_HOSTING (the $0 hosting/email template) · SCALING ·
  AGENT_ACCESS · SPEC/P8_PLAN (historical).

## What remains (2026-07-11)

**The whole audio-features roadmap ①–⑤ is COMPLETE and live**, the loudness arc
closed the bigger half of ⑥, and **DMARC was tightened to `p=quarantine`
(2026-07-11)** — so **⑥ polish is effectively done.** Only optional infra tails
remain: the `quarantine`→`reject` bump (~2 weeks after reports show clean) and a
**send-as-the-domain** path if wanted (free Gmail+relay+DKIM, or a cheap mailbox
in Outlook — see the `vercilloanalytics-domain-setup` memory). Parked by
deliberate decision: **instrumentalness** (needs source separation — a fake
proxy would cost the tier system its credibility). Otherwise: a fresh direction
of the owner's choosing.
