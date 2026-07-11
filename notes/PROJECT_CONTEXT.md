# PROJECT CONTEXT — read this first

## ⏭️ RESUME HERE (30-second orientation)

- **Project:** Vercillo Analytics — a data-engineering portfolio pipeline:
  Spotify top tracks (3 time ranges) → YouTube audio acquisition → local DSP
  (77-dim features) → medallion warehouse (Parquet, star schema) → FAISS/UMAP
  + temporal drift analytics. Exists BECAUSE the Feb-2026 Spotify API removed
  `/audio-features` — the local-DSP layer is the interesting part.
- **Portfolio target:** Data Engineer – Platform (Spotify Toronto posting is
  the reference role): pipelines at scale, Spark, developer experience, data
  quality, "systems that enable AI agents to interact with data
  infrastructure" — this repo's agent harness IS evidence for that last one.
- **Status:** ✅ **Phase V VERIFIED 2026-07-03 — the pipeline runs end-to-end
  on this machine and the warehouse passes its audit ALL-GREEN** (see §2:
  smoke + 9-track real run w/ audio download + DSP). Fixed during
  verification: committed Spotify secret scrubbed AND **rotated in the
  dashboard 2026-07-03 (old `9b75…` secret is dead; PKCE never used it
  anyway)** — security item CLOSED, 7-step
  orchestrator rebuilt to match docs, ffmpeg/libmp3lame installed, DSP
  feature-serialization gap closed (warehouse: 82 numeric feature cols;
  FAISS vector unchanged at 77). Phase-4 webapp still NOT in this repo copy.
- **🚀 LIVE (2026-07-08): `https://vercilloanalytics.com` serves the app from the
  owner's PC — Epic E slice 2 (tunnel go-live) DONE.** Chain verified end-to-end:
  public URL → Cloudflare edge (yyz) → `cloudflared` **Windows service**
  (tunnel `vercillo`, `c02e4398…`; ImagePath fixed via registry — `service
  install` registers NO args and crash-loops, and `sc.exe config` from PS
  silently mangles quotes; see SELF_HOSTING §2 gotcha) → localhost:8000
  (`/healthz` {ok:true}, landing 200 in 0.26s). Webapp + worker `--loop` running
  (background tasks); prod `.env` set (fresh SESSION_SECRET_KEY, https redirect
  → Secure cookies). **DNS drama (journal #14): the domain was DARK — the four
  delegated ns-cloud-d* pointed at a DELETED Google Cloud DNS zone (Squarespace's
  records page was an inactive copy). Cutover to Cloudflare (`jason`/`surina`)
  RESTORED the domain + Workspace email (MX+SPF staged pre-swap, verified
  publicly).**
- **✅ EPIC E ACCEPTED (2026-07-08): owner logged in ON THE LIVE DOMAIN and the
  full experience rendered** — landing → PKCE login (after adding the prod
  redirect in the Spotify dashboard; the "redirect_uri: Not matching
  configuration" error confirmed-then-fixed it) → dashboard (41/41 analyzed,
  absolute profile, ask box) → /analytics (archetype "The Drifting Dualist"
  0.208σ, signature, cluster movement toward "Dark · Smooth", composition bars,
  the acoustic map, artist buckets: Muse 31-track "Noisy · Bright" vs "Smooth ·
  Dark"). External reachability separately proven via curl through the
  Cloudflare edge. **ALL EPICS A–E OF APP_SPEC v2 ARE BUILT AND LIVE, at $0.**
- **➡️ NEXT ACTION — app is UP; owner's control is now a double-click.**
  ✅ The hardened pipeline is LIVE (verified 2026-07-09, app-verify ALL-GREEN,
  heartbeat fresh, public edge 200). **Runtime control is now click-to-run:**
  `start_app.bat` / `stop_app.bat` / `status_app.bat` at the repo root (wrap
  `scripts/app_control.ps1`; start is idempotent, stop matches by script name,
  logs → `logs\*.log`). Optional reboot persistence (owner's hand — the
  classifier reserves scheduled-task registration): `powershell
  -ExecutionPolicy Bypass -File scripts\register_autostart.ps1` (at-logon tasks
  + 03:00 backup). **DECIDED 2026-07-09 (owner): run ON-DEMAND via the click
  scripts — NOT 24/7, autostart tasks deferred until the dedicated server he'll
  build later. Do NOT re-suggest register_autostart for this PC.** One
  consequence to watch: the nightly backup task isn't registered, so the cache
  (hours of extraction, the one non-instant asset) is unprotected between
  manual `backup_cache.py` runs — ✅ **backup-on-`stop_app` now WIRED** (every
  stop snapshots the cache; proven live). NEW SESSION? Run **`/resume`** as
  usual. **Standing next build — F-v2 (IN PROGRESS):** frame-level audio pass.
  ✅ **F-v2a DONE (2026-07-09, commit 951cb5a, 272 tests):** the within-track
  **loudness curve** on the song page — per-frame RMS→dBFS (120-pt downsample),
  honest measurement rebuilding Spotify's retired get-audio-analysis series;
  kept OUT of the frozen 77-dim vector / 82-col dict; `loudness_curve` cache
  column + forward-only `_migrate_added_columns` (journal #18); `loudness_svg`
  area chart; **`scripts/backfill_loudness.py` filled 117/117 from LOCAL owner
  MP3s — no re-download** (data/raw_audio survives even though worker audio is
  transient). Deployed live via `app_control restart`. ✅ **F-v2b DONE
  (2026-07-09, commit 199f8e3, 277 tests):** **time_signature** as a *measured*
  `/explore` feature (catalog 13→14) — same promoted-column discipline (cache
  column, NOT in the vector/82-col dict), joined into the perceptual transform
  by bridge key; `_estimate_time_signature` = autocorrelation of beat accents;
  `scripts/backfill_time_signature.py` filled 117/117 from LOCAL MP3s.
  **Honesty fix on real data (journal #19):** candidates start at 3 not 2 — a
  4/4 backbeat has period-2 accents that mislabeled 42/117 as 2/4; duple
  collapses to the 4 default (distribution → credible 4/4×83, 3/4×17, odd×17).
  Marts catalog↔stats parity held. The decoupling keeps paying off:
  online-first extractor + local backfill = ZERO re-download. ✅ **ROADMAP SET
  (2026-07-09, `docs/VISION_SPECS.md` → "Roadmap — remaining build sequence"):**
  reviewed all 13 Spotify audio-features — **10 rebuilt reliably** + 3 bonus
  (brightness/punch/dynamics) + valence proxy; **instrumentalness REMOVED**
  (source-separation cost not worth the tier-credibility hit), valence/liveness
  stay unfaked. **Verified `popularity` is Deprecated-not-removed** (our own
  guardrail was over-cautious — journal #20). Sequence: **~~① F-v2c~~ → ② P
  popularity-context → ③ F-v3 structure timeline (marquee) → ④ Epic G
  recommendation explorer (capstone) → ⑤ A3 Ollama → ⑥ polish**. ✅ **F-v2c
  DONE (2026-07-09, commits d1a…694ed2e, 281 tests):** ①.1 **fade-in/out**
  detection — a PURE function over the stored loudness curve (zero backfill,
  all 117 immediately); depth-gated to real fades-from-silence → credible
  fade-in 19% / fade-out 34% (the fade-out>fade-in asymmetry = the honesty
  signal, journal #21). ①.2 **beat grid** — `beat_times` cache column (migration
  #3), extractor + worker + `backfill_beat_times.py` (117/117, ~481 beats/track);
  rendered as a **bar grid** (every meter-th real beat) since a full beat grid
  is a 1px/beat smear — ~5–6px legible, honest spacing, phase approximate.
  Deployed live. ✅ **② P — POPULARITY CONTEXT DONE (2026-07-10, commits
  →4957f73, 304 tests, audits clean, deployed):** popularity captured as
  optional fetched CONTEXT (never acoustic, never ML — policy encoded at every
  layer); the 3 over-cautious docs CORRECTED (CLAUDE.md rule 3, agent-prompt
  01 w/ dated note, guardrails/fetchers); `track_meta.popularity` (migration
  #4) + preserve-if-absent `remember_meta` (also fixed a latent field-clobber);
  `popularity_context()` line on `/analytics` w/ honest fetched-not-acoustic
  caption + RAG grounding; `backfill_popularity.py` valued **119/119 in 3
  batched /tracks calls** (silent PKCE refresh — deprecated-not-removed
  re-confirmed live). Real lines: owner "63/100 — more obscure than 55% of the
  corpus" (median 67); crafted obscure taste → "more obscure than 97%".
  ✅ **③ F-v3 — STRUCTURE TIMELINE DONE (2026-07-10, commits →27fd23d, 311
  tests, deployed, all audits green):** the marquee — rebuilt the sections[]
  of Spotify's retired get-audio-analysis via simplified Laplacian
  segmentation (path-enhanced recurrence + MFCC path graph, eigengap k,
  seeded KMeans); `sections` cache column (migration #5, preserve-if-absent);
  worker persists; `backfill_sections.py` 117/117 from LOCAL MP3s (no
  re-download); **section ribbon** on the song page (same letter/color =
  same-sounding part, hover = span/tempo/loudness/key, the no-chorus/verse
  honesty line stated IN the UI). **Three real-data tuning rounds** (journal
  #24 — validate on 3 levels): fragmentation (25–63 fake sections → 7s min +
  9-beat smoothing), A|A coalesce artifact (majority-vote span labels), and
  chroma-blindness — Knights of Cydonia read as ONE 366s section because its
  structure is TIMBRAL (harmonica→gallop→vocals) while recurrence saw only
  harmony → z-balanced chroma+MFCC stack. Final corpus: mode 3–4
  sections/track, max 14, min dur 7.1s, 549 sections; spot-checks: Prayer
  A-B-A-B-A, Hexagons 9 secs/4 letters, KoC 3 coarse-but-honest.
  ✅ **④ EPIC G — RECOMMENDATION EXPLORER DONE (2026-07-10/11, commits
  →bcd0fb3+, 325 tests, deployed, browser-validated):** the capstone —
  Spotify's retired `/recommendations` rebuilt TRANSPARENTLY over our
  features: `src/webapp/recommend.py` (pure engine: whitelisted min_/max_/
  target_ tunables; hard filters prune; targets rank by z-distance against
  feature_stats — a tempo miss and an energy miss compare in σ; tracks
  missing a constrained value sit out; deterministic (score,id));
  **seed mode fills VISIBLE targets** from the seed's own values ("more like
  this" with no hidden model — every knob shows in the form); popularity
  rides as a constraint axis (fetched context; analysis use only). `/recommend`
  route + tunables-table UI + ranked results (value chips, cluster colors,
  Δσ, /song links), nav entry, song-page "More like this — tune it" seeding.
  **Real-data proof:** obscure-mover hunt works (all results < pop 50);
  "more like The Groove" neighbors at 0.81–0.95σ; meter hunt min=max=3
  returns EXACTLY the 17 tracks F-v2b recorded as 3/4 (cross-feature
  consistency). **NEW STANDING PRACTICE (owner ask): every build ends with a
  LIVE BROWSER validation** — Browser pane on vercilloanalytics.com verified
  the landing (incl. CF email-obfuscation decoding), /recommend auth-gating,
  and www→apex through the real edge (authed pages = route tests + owner
  click-path, credentials never handled).
  ✅ **⑤ A3 — OLLAMA LOCAL-LLM DONE (2026-07-11, commits →<A3.2/3>, 330 tests,
  deployed):** `/ask` + `/classify` now answer via a LOCAL model at $0, no key.
  `rag.py` unified both providers behind one `_chat()` dispatching on
  `WEBAPP_LLM_MODEL=ollama:<m>` (REST /api/chat, format=json, num_ctx 8192 —
  gemma4's 262K default KV spilled 29% to CPU on the 12GB card; temp 0,
  keep_alive 10m); deterministic fallback unchanged as the automatic safety
  net; `run_webapp` warms the model on startup (no ~90s cold first-ask; live
  Ollama confirmed gemma4 resident after deploy). **The F0 evals paid off
  (journal #25):** gemma4 first scored **5/15** vs the template's 15/15 →
  tightened the grounding contract (name real artists; reuse labels verbatim)
  → **9/15** (no_invention 15/15, archetype 5/5 — zero hallucination; misses
  are paraphrases). **Owner chose gemma4 as the live default** (set via
  gitignored .env; code default stays hosted so CI never hits a server); /ask
  credits "local gemma4:12b ($0)". **THE ENTIRE ROADMAP ①–⑤ IS COMPLETE — both
  retired Spotify endpoints rebuilt + a reco engine + real $0 local LLM, all
  evals-guarded. ✅ **⑥ POLISH — LOUDNESS-ON-/ANALYTICS DONE (2026-07-11, commit
  c7ffe95, 333 tests, deployed, all audits green):** "Your typical track's
  loudness arc" on `/analytics` — the MEDIAN within-track loudness *shape* across
  the visitor's analyzed tracks (each stored dBFS curve normalized to its own
  dynamic range + resampled onto a common 0→1 timeline) with a middle-50%
  (p25–p75) IQR band. Pure `average_loudness_arc` + `loudness_arc_svg` in
  analytics.py; `cache.loudness_curves(ids)` bulk getter (all_popularity
  pattern); wired in `_analytics_context` BEFORE the model block (needs no
  trained clusters); template section + honest caption; `.loud-band` CSS.
  **Deliberately distinct from the absolute "Loudness" signature dim** (shape,
  not level — no duplication). Central line is the median + IQR band = quantiles,
  so the band brackets the line by construction (a mean can fall outside a skewed
  IQR — caught by a test, journal #26). Real corpus: varied intro (median .61,
  band .31–.77) → sustained loud body (~.95, tight) → collapse to silence at the
  very end (median .00) — that aggregate fade-out corroborates F-v2c (fade-outs
  34% > fade-ins 19%). Deployed via `app_control restart` (cache backed up on
  stop); app-verify ALL-GREEN, live edge 200/303, arc DOM-verified in the Browser
  pane (117 tracks, band + axis labels + caption). ✅ **DMARC TIGHTENED to
  `p=quarantine` (2026-07-11, verified live on 8.8.8.8 + 1.1.1.1)** — **⑥ POLISH
  IS NOW EFFECTIVELY COMPLETE.** Only two *optional* tails remain, both infra not
  code: the `quarantine`→`reject` bump (~2 weeks after DMARC reports show clean)
  and the never-set-up **send-as-the-domain** path (free = Gmail "send mail as"
  via a Brevo free SMTP relay + that provider's DKIM in Cloudflare; paid-tidy = a
  cheap Purelymail/Migadu mailbox in the Outlook app) — email details live in the
  `vercilloanalytics-domain-setup` memory. ✅ **VISION C SPECCED (2026-07-11,
  owner's 12-idea list → `docs/VISION_SPECS.md` §"Vision C — the public era"):**
  decisions D-18 (corpus goes PUBLIC — full 118-track corpus, owner's explicit
  privacy choice; deliberately reverses the /spectrogram gate), D-19 (MPD
  PARKED w/ saved dbt/Recce references — see `mpd-future-references` memory),
  D-20 (filter-repo history scrub before public flip), D-21 (llm_knowledge_base
  EXCLUDED from public repo — course material), D-22 (yt-dlp stays, harden
  matching — duration check, official-audio preference; iTunes 30s previews
  REJECTED on feature-comparability honesty). **➡️ NEXT ACTION — Vision D Phase 1 — bugs + quick wins: D-31 rename (drop "Taste Pilot" →
  "Vercillo Analytics"), B1 recommend-seed refresh, H3 popularity-on-hover, H4
  UI cut-off sweep, N1 stats/σ explainer, N2 the 12-archetype taxonomy, O1
  dedup-as-flag, and **H0+H7 guest demo persona (D-30 — the INTERVIEW
  showpiece: "View as guest" → read-only session preloaded with the owner's
  taste snapshot via `snapshot_demo_profile.py`; full personalized experience,
  no login, pulled forward from Epic H).** Then Phase 2 = MPD/Spark
  METADATA-ONLY (D-26…D-29: J0 local intake script → J1 Spark co-occurrence +
  track2vec on real 66M rows → J2 hybrid acoustic×co-occurrence reco → J3
  real-66M-row Spark benchmark; Spark NEVER on the download path). Phase 3 =
  public showcase (H full) + I (playlists) + K (agentic chat) + L publish.
  Vision D also added Epic N (explainability), Epic O (dedup + yt-dlp
  match-hardening), Bug B1 — full spec in VISION_SPECS §"Vision D". Start Phase
  1 with the app running (`start_app`); J-audio + M-notifications stay parked.
- ✅ **SECURITY + ROBUSTNESS REVIEW (2026-07-09, commits 26891b1←): whole-app
  audit via 2 review subagents + a strategic pass; 7 real fixes, all tested,
  deployed, 286 green.** **Security surface came back STRONG** — auth, session
  signing/rotation, PKCE `state`/CSRF, the DuckDB read-only sandbox, yt-dlp
  (ytsearch prefix = no SSRF/shell), path handling, and secret hygiene all
  verified clean. Fixed: **① XSS** — track/artist names were interpolated into
  `|safe` SVG `<title>`s unescaped (`scatter_svg`/`scatter_xy_svg`) → now
  `markupsafe.escape`d (self-XSS now, cross-user the moment F-v3/G render others'
  names). **② + ③ two HIGH availability bugs** in the extraction path: no
  dead-letter + `enqueue` reset `attempts` → a permanently-unfetchable track
  hot-looped re-download+DSP forever (now `MAX_ATTEMPTS=3` dead-letter, attempts
  preserved); the worker `--loop` body was unguarded → one transient WAL
  snapshot-stale DB error killed the only consumer (now try/except: log+continue).
  **④–⑦ MEDIUM:** `upsert` preserves display cols (re-seed no longer NULLs the
  F-v2 backfills), migration ALTER race-guarded, marts `os.replace` Windows-retry,
  `/spectrogram` auth-gated (enumeration oracle closed — verified 303 live).
  **Hardening backlog (lower severity, deferred — do opportunistically):**
  single-instance worker lock (a manual 2nd worker can double-write a
  spectrogram), a `warehouse-audit` **distribution-sanity check** (flag
  implausible feature distributions — operationalizes journal #21, catches the
  feature-validity bugs synthetic tests can't), stamp population-`n` on
  perceptual rows (percentile-drift honesty), yt-dlp base62 track-id assertion,
  `www_redirect` host allowlist, `/logout`→POST. Journal #22 (the review method).
- ✅ **ROOTS REVIEW + BACKLOG CLEARED (2026-07-10, commits →c31f298, 299 tests,
  all audits green):** pipeline-partner review of plan + build per owner's ask.
  **Vision confirmed on evidence** (strategies/tools inventory below holds);
  the post-#22 surface (`/status` + poller) personally re-reviewed CLEAN
  (auth-gated, session-scoped, cache-only, textContent). **The whole journal-#22
  hardening backlog is now BUILT:** ① `www_redirect` → allowlist (spoofed Host
  could mint a 301 to an attacker domain; `WEBAPP_CANONICAL_HOST` config;
  spoof→200 + real www→301 both verified LIVE through the edge), `/logout` →
  POST-only (GET 405s; header form; cross-site <img> logout closed), track-id
  charset guard in `extract_one` (id becomes a filename; base62-only, worker
  twin of the webapp path strip); ② **single-instance worker lock** via the
  heartbeat (fresh other-pid beat → refuse; `--takeover` for the managed
  lifecycle — journal #23: the lock's first victim would have been its own
  restart; proven live both ways); ③ **FEATURE_DISTRIBUTION audit flag**
  (journal #21 operationalized: plausible ranges, 0–1 tier bounds, zero-spread,
  4/4-must-be-modal — the #19 bug would now be CAUGHT by the audit) +
  **population_n stamped** on perceptual rows (calibration honesty; parity-
  exempted). **Ops sweep via an Explore agent** (findings verified then fixed):
  app_control process matching ANCHORED to this repo (bare substring could
  Stop-Process another checkout/editor — doc claim corrected), cmd-metachar
  path guard, 5 MB log rotation, CI `permissions: contents: read`, launch.json
  http.server → 127.0.0.1. Accepted+documented: OAuth code in local gitignored
  access log (single-use PKCE), mutable action tags, 03:00-backup race (task
  not registered). Deployed via restart; suite 298→299 (a commit msg says 298 —
  miscount, this line is the truth).
- ✅ **INGESTION FLOW VALIDATED + LIVE PROGRESS (2026-07-09, commits 443b→d2ede0d,
  290 green):** pipeline-partner review of the ingestion path. **3 of the owner's
  asks were already satisfied by the existing design** (confirmed with evidence):
  new-user download (dashboard `enqueue`s misses → worker extracts), re-run per
  login (every dashboard load re-fetches all 3 top-track ranges + re-enqueues new
  ones), and cache efficiency (track-keyed **user-agnostic** cache = analyze once
  ever; `cache.get` instant hits, `enqueue` only true misses, failing tracks
  dead-lettered). **The one real gap — progress visibility — is now BUILT:** a
  cache-only **`GET /status`** (JSON: analyzed/total, queued/running/failed, the
  in-flight track by name, ETA=remaining×~50 s) that the dashboard polls every 5 s
  via a minimal inline poller → live progress bar + "Analyzing <song> · N of M ·
  ~X min left" + auto-refresh on done. **Cache-only by design = also the efficient
  path** (polling never re-hits Spotify). Song name via `textContent` (no XSS).
  `ingestion_status()` pure+tested; `cache.running_ids()` added. Deployed;
  `/status` live-verified. First inline JS in the app (no CSP).
- **Closeout** is ~DONE (2026-07-09): ① **email moved
  to free Cloudflare Email Routing** (dropped paid Google Workspace, ~$17 CAD/mo
  → $0) — `jordan@vercilloanalytics.com` catch-all forwards to
  `jvercillo@live.com`; MX `route*.mx.cloudflare.net` + SPF + DKIM
  (`cf2024-1._domainkey`) + DMARC (Cloudflare DMARC Management) ALL verified
  live via authoritative DNS. Invite CTA already switched to
  jordan@… (backup-on-`stop_app` also wired — on-demand running now protects
  the cache without the nightly task). Live gotcha: a manual MX/SPF delete
  flipped Email Routing to Disabled → **Onboard Domain** re-committed it (in
  SELF_HOSTING §1a, the $0-email template). ✅ **Forwarding PROVEN 2026-07-09**
  — a test email to jordan@… landed in the jvercillo@live.com Outlook inbox.
  **OWNER's last 2 manual bits (both cost-cleanup, non-blocking):** (a)
  **cancel the Google Workspace subscription** (Admin → Billing → Subscriptions;
  safe — MX is already Cloudflare, so cancelling doesn't touch forwarding), (b)
  delete the orphaned GCP Cloud DNS zone (~$0.20/mo). (autostart +
  nightly backup are scripted; extended quota is
  DEAD as an option, see the front-gate note below).
- **✅ NEW-USER PIPELINE HARDENED (2026-07-09, 4 commits df65650→ce325ed,
  264 tests green, audit ALL-GREEN):** Jordan's ask — "ensure new visitors'
  songs get downloaded + extracted." Verified the flow ALREADY WORKS live
  (a tester's uncached track went queued→done-with-spectrogram in **52 s**;
  dashboard queues misses → worker `--loop` extracts), then closed the
  ensure-gaps: **①** `worker_heartbeats` + `cache.beat()` (beats every poll
  AND between jobs via drain `on_progress`) + `requeue_stale_running()`
  (crash-orphaned 'running' jobs re-queue; before this a mid-job crash
  stranded the track forever) + app-verify **WORKER_DOWN / QUEUE_STUCK**
  flags (the audit had NO worker check — journal #16); **②**
  `perceptual.rebuild_marts()` — the one rebuild entry point (script + worker
  post-drain, atomic parquet replace) + mtime-keyed explore loaders, so new
  tracks reach `/explore` with no operator and no app restart (real proof:
  118 transformed, Thrice track joined, "The Groove" still #1 danceable);
  **③** seed ghost guard — metadata-only warehouse rows seed META only, and
  the live Hummer ghost row was deleted (cache is **118 real tracks / 119
  metas**; the earlier "119 tracks" claim here counted the ghost — journal
  #17); **④** `scripts/register_autostart.ps1` (webapp+worker at logon,
  backup 03:00, ExecutionTimeLimit-zeroed) + SELF_HOSTING §4 rewrite.
  Cache truth: 117 owner-corpus + 1 live-login extraction. **Front-gate
  truth (verified 2026-07-09, Spotify Feb-2026 policy):** dev mode caps the
  allowlist at **5 users** (dashboard shows "1/5 added"; was ~25), adds are
  manual-only (no API exists), and extended-quota mode now requires a
  registered business with ≥250K MAU — off the table for a personal pilot,
  so the 5-seat manual list is the PERMANENT gate. The app now says so:
  invite-request notice (jordan@vercilloanalytics.com) on the landing + error pages. ✅ **POLISH PASS DONE
  (2026-07-09):** spectrogram backfill — **117/117 rendered** (deep-dives all
  populated); album-art ♪ tile + initial-letter artist avatars for missing
  images (local files); 🎧 favicon + per-page titles; **www→apex 301
  middleware** (registered outside the session layer — host-scoped cookies
  made www logins strand sessions; verified LIVE: www…/explore?f=tempo → 301
  apex w/ path+query); ask-page → Explore link. 4 new tests → **255 green**;
  live edge checks all pass. ✅ **Epic F slice F3 DONE (2026-07-08): the
  `/explore` dashboard — Vision B's payoff. EPIC F RECOMMENDED SCOPE COMPLETE
  (F0+F1+F2+F3); only F-v2 remains.** `src/webapp/explore.py` (pure view
  logic): tier-grouped picker from the catalog; population histogram from
  `feature_stats` (one series + the visitor's ringed green dots + native
  <title> hover); **exact percentile chips** computed server-side vs the live
  population; feature×feature scatter over `track_perceptual` colored by the
  Epic-C clusters (gray = unclustered), labeled axes; per-window strip w/ the
  recent-vs-all-time delta sentence; marts-not-built empty state; unknown
  feature param falls back gracefully. Route `/explore?f=&x=&y=` (auth-gated,
  form-GET selects, no JS required beyond auto-submit), nav link, deep-dive
  stat links → explorer. **Real-data proof: 13-feature catalog served, 117
  perceptual rows, sample chips "danceability above 65% / loudness above 72%
  of corpus", strip delta "your last 4 weeks run 11 bpm higher than your
  all-time." 9 new tests (percentile math, histogram bars/dots/axis, scatter
  ring/gray/axes, strip means+delta, tier grouping, route auth/no-taste/
  not-built/happy-path/fallback) → 251 green.** ✅ **Epic F slice F2 DONE (2026-07-08):
  `feature_stats` mart + audit extension.** `compute_feature_stats` in
  `perceptual.py` — one row per catalog feature: n/mean/std/min/p5–p95/max +
  deterministic histograms (mode 2 bins, key 12, 0–1-calibrated fixed [0,1]×20,
  other measured min–max×20); `data/marts/feature_stats.parquet` via the mart
  builder. `warehouse-audit` gains `check_marts()` (importable, pytest-covered):
  **CATALOG_MART_DRIFT** (catalog↔track_perceptual exact-list, both directions
  + bridge-key dup check) and **STATS_MART_DRIFT** (catalog↔stats parity,
  required schema, bin_counts-sum-to-n); absent marts = note, not finding.
  **Proof: real build 117 tracks / 13 stats rows; extended audit → marts
  section {catalog 13×5, perceptual 117×15, stats 13×18}, 0 errors, both new
  flags false. 7 new tests (percentile ordering, bin sums, binning rules,
  drift-detection positive AND negative cases) → 242 green.** ✅ **Epic F slice F1 DONE (2026-07-08): `perceptual-v1`.**
  `src/store/perceptual.py` — pure transform over the 82 cached cols: 5
  measured (tempo/key/mode/duration/loudness-dBFS incl. str-"minor"→0 mapping),
  7 derived percentile-calibrated 0–1 (energy, danceability [~120bpm band ×
  pulse clarity × beat density], acousticness, speechiness, brightness, punch,
  dynamics), 1 experimental (valence_proxy, caveat in catalog).
  **Instrumentalness MOVED experimental→F-v2 during build** (summary stats
  can't see vocals; a fake proxy would cost the tier system its credibility —
  VISION_SPECS updated). `track_perceptual` cache table +
  `data/marts/{track_perceptual,feature_catalog}.parquet` via
  `scripts/build_feature_marts.py` (idempotent, versioned). **Real-data proof:
  117 tracks transformed, 13 catalog features; most-danceable = "The Groove"
  (136bpm, dance 1.00) — the track named The Groove topping danceability is
  the sanity check writing itself. 6 new tests (exact loudness math, blob
  ordering, ghost exclusion, catalog↔transform parity, roundtrip) → 235
  green; audit unchanged ALL-GREEN.** **DECIDED
  2026-07-08: Epic F = Vision B with F0 first; A3 (Ollama) PARKED with a
  validated plan** (VISION_SPECS A3: RTX 4070 Ti 12GB, `ollama list` verified;
  choice = gemma4:12b w/ `num_ctx: 8192` — default 262K ctx spilled 29% to CPU;
  it's a thinking model → pair `format="json"` w/ the A2 thoughts-first schema;
  qwen3:8b fast fallback; gemma2:2b retired). ✅ **Epic F slice F0 DONE
  (2026-07-08): A1 gold eval harness + A2 structured-output contracts.**
  `src/webapp/evalset.py` (deterministic grader: nonempty/must_cite/
  no_invention/plain_prose/archetype; disaggregated report + constant
  baseline) + `evals/golden_taste_v1.jsonl` (15 cases, versioned) +
  `evals/run_golden.py` CLI (exit-1 gate). `rag.py`: both LLM calls now emit
  JSON `{thoughts→answer/narrative, cited}` (thoughts FIRST per the KB card),
  fence-stripping parser `_parse_llm_json`, parse failures LOGGED + degrade to
  fallback (never fake success). **Proof: fallback 15/15; constant baseline
  0/15 with must_cite/archetype at zero while no_invention/plain_prose pass —
  the disaggregation shows which checks carry skill. The golden guard runs in
  CI via pytest ($0). 229 tests green.**
- **Prior decision context — [`docs/VISION_SPECS.md`](docs/VISION_SPECS.md)
  (2026-07-08): two visions specced + aggro/value-audited.** **Vision A** (LLM-KB
  review → 3 surgical upgrades: A1 gold eval set for `/ask`+`/classify` w/
  deterministic grader in CI, A2 structured-output JSON contracts, A3 optional
  Ollama $0-LLM path; + 2 deliberate rejections — no vector-store RAG (KB's own
  "small structured corpora don't need vectors"), no fine-tuning yet). **Vision
  B** (Audio-Feature Explorer: rebuild Spotify's DEPRECATED audio-features
  fields from our 82 cached columns as a versioned `perceptual-v1` transform w/
  honest tiers — 5 measured + 5 derived + 2 experimental + time_signature in v2;
  gold marts `feature_catalog`/`feature_stats`/`track_perceptual`; `/explore`
  dashboard: feature picker, population distribution w/ user overlay +
  percentile chips, feature×feature scatter colored by Epic-C clusters).
  **Recommendation: Epic F = B with A1+A2 as its first slice (F0), A3 queued.**
  Then the earlier closeout list still stands (below).
- **Prior next action — closeout + polish.** ① **Merge PR #7** (the whole app is
  running off `epic-a/feature-cache`); ② formal phone-off-wifi spot-check
  (reachability already proven via edge curl); ③ email finishers: DKIM TXT from
  admin.google.com → Cloudflare (+optional DMARC), test email to
  jordan@vercilloanalytics.com; ④ hardening: Task Scheduler autostart
  (webapp+worker), nightly `backup_cache.py` task, delete the orphaned Google
  Cloud DNS zone (~$0.20/mo), Tailscale re-auth, Cloudflare www→apex redirect
  rule; ⑤ Spotify extended-quota request + tester allowlist; ⑥ the owner's
  deferred polish/UX pass (e.g. local-file tracks show placeholder album art).
  Runbook: [`docs/SELF_HOSTING.md`](docs/SELF_HOSTING.md). ✅ **Epic E slice 1 DONE (2026-07-08):
  `/privacy` page (+footer link, route test), `src/store/backup.py` +
  `scripts/backup_cache.py` (WAL-safe sqlite backup API; verify/restore;
  `.pre-restore` safety; prune; RESTORE DRILL tested — incl. Windows
  file-lock lesson → `FeatureCache.close()`), and
  [`docs/SELF_HOSTING.md`](docs/SELF_HOSTING.md) — THE reusable $0 PC-hosting
  template (owner's explicit ask). 221 tests green.** ✅ **Epic D COMPLETE
  (2026-07-07): RAG taste classification.**
  `src/webapp/archetype.py`: deterministic archetype from real signals — home
  sound (dominant cluster), breadth (Loyalist ≥70% / Dualist two ≥85% /
  Eclectic), motion (D-9 σ-bands: Anchored/Drifting/Roaming/Shape-shifting) →
  "The {motion} {breadth}" + numbered evidence lines. `rag.py`: grounding now
  carries archetype+clusters+signature (richer `/ask` too); `TasteRAG.classify`
  — LLM narrative for the deterministic name (never rebrands) w/ deterministic
  fallback (D-5, $0). App: `_analytics_context` helper enriches session taste;
  archetype hero card on `/analytics` + POST `/classify` → `profile.html`.
  **Real-data proof: "The Drifting Dualist", home "Bright · Noisy" (54%),
  grounded fallback narrative "…Muse anchors it all." 8 new tests → 215
  green.** ✅ **Epic C COMPLETE (2026-07-07): population clustering +
  analytics dashboard.** `src/store/clusters.py`: versioned KMeans models
  (silhouette-chosen k) over ALL cached tracks + per-artist acoustic centroids;
  cluster naming via top-|z| `_CHARACTER_DIMS` (shared vocabulary w/ journal #9);
  online nearest-centroid assignment for new tracks; PCA (default) / UMAP map
  coords; tables `cluster_models`/`track_clusters`/`artist_profiles`. Webapp
  `/analytics` (`src/webapp/analytics.py` + template): **acoustic signature**
  (top-|z| vs population), cluster composition per window + **movement story**,
  the **cluster-map SVG** (population dim, user's songs ringed+colored),
  **artists-who-sound-alike buckets** (user's artists bolded). Categorical
  palette VALIDATED via the dataviz skill script (6 colors, dark surface, fixed
  order). Train: `uv run python scripts/train_clusters.py`. **Real-data proof:
  117 tracks → k=2 "Dark · Smooth"/"Bright · Noisy" (silhouette 0.115 — honest,
  homogeneous corpus), 59 artists → 2 buckets. Journal #13 (one all-None ghost
  track poisoned column intersection → coverage-based selection). 208 tests
  green.** ✅ **Epic B COMPLETE
  (2026-07-07): hover a track → its features (`taste.track_summary`); deep-dive
  `/song/{id}` — full features + **mel-spectrogram** (`/spectrogram/{id}`, served
  from data/spectrograms) + inline-SVG **radar** (`taste.radar_svg`) + **"songs
  like this"** (`FeatureCache.similar` — z-scored distance, pgvector in prod);
  `seed_cache.py --spectrograms` renders them from owner MP3s. Proven: real 128KB
  spectrogram + deep-dive render. 195 tests green.** **APP_SPEC is now v2
  (2026-07-07, owner constraint): LOCAL-FIRST at $0 — no GCP/BQ/Cloud Run;
  hosting = owner PC + free HTTPS tunnel (Cloudflare/Tailscale) (D-16); serving
  DB = SQLite+WAL default with `DATABASE_URL`→local-Docker-Postgres upgrade
  (D-12 amended); the DB IS the queue (worker `--loop`); cache = backed-up asset
  (D-17); residential IP is BETTER for yt-dlp than cloud. Owner actions now
  $0: Cloudflare account + domain DNS, Spotify redirect for the tunnel URL +
  extended-quota request, optional ANTHROPIC_API_KEY.** ✅ **Epic A COMPLETE
  (2026-07-07): the shared feature cache + extraction + webapp wiring.** `src/store/`
  (SQLAlchemy, SQLite-dev/Postgres-prod): `FeatureCache` (get/missing/upsert/enqueue/
  claim_next/fail/job_status; TrackMeta) + `extractor.py` worker (yt-dlp → librosa
  77-dim + mel-spectrogram → cache; audio transient, D-15) + `scripts/{run_extraction_worker,
  seed_cache}.py`. Webapp now sources the dashboard from the cache (`src/webapp/taste.py`:
  absolute acoustic profile + own-drift): reads hits, flags **analyzed**, queues
  misses, shows **"N of M analyzed · K analyzing…"** — retires owner-corpus overlap
  (D-11). **To demo real features: `uv run python scripts/seed_cache.py` warms the
  cache from the owner warehouse; a worker drains new misses.** Then B → C (ML
  clustering songs AND artists + drift viz) → E-partial (Dockerfile→Cloud Run) → D
  (RAG classification) → E-full. Owner still to do: GCP/domain, Spotify prod redirect
  + extended-quota request, prod `SESSION_SECRET_KEY` (+ optional Postgres
  `DATABASE_URL`, `ANTHROPIC_API_KEY`).
- **✅ P8 slice 2 (2026-07-05): RAG `/ask` grounded taste Q&A — the last of the 4
  pilot features.** `rag.py` (`TasteRAG`): grounds on the visitor's overlap
  insight + drift + top artists + top tracks + gold `column_descriptions`
  glossary; LLM (`claude-opus-4-8`, `WEBAPP_LLM_MODEL` override) with
  deterministic fallback (D-5); never raises. POST `/ask` over an in-session
  `taste` context cached at `/dashboard`. 7 tests → **173 green**, ruff clean.
  Committed on `p8/slice-1` (updates PR #6). Live-test of `/ask` still pending
  owner; no `ANTHROPIC_API_KEY` set yet → deterministic fallback runs.
- **✅ P8 pilot slices 1 + 1.5 (2026-07-05): FastAPI webapp, VERIFIED LIVE with a
  real Spotify login.** Slice 1: session-scoped PKCE (token in server session not
  the file cache; CSRF `state` gate; session-id rotation), `SessionStore` (TTL +
  sweep, signed cookie), bridge-key overlap-join insight, Jinja2 UI. Slice 1.5:
  album art (`album_image_url` — schema-safe), top artists + genres, per-visitor
  taste drift (`drift_profile` reuses the D-9 σ-shift; ≥2-track guard). **Live
  acceptance: 41/41 corpus overlap, drift Moderate 0.211σ (20 vs 20), no
  client_secret on the wire (D-8).** 18 webapp tests → **166 green**, ruff clean.
  **PR #6 (`p8/slice-1`→main) OPEN** (PR #5 plan already merged). Run: `uv run
  python scripts/run_webapp.py` → :8000 (needs `.env` SPOTIPY_CLIENT_ID +
  SESSION_SECRET_KEY; `:8000/callback` registered in the Spotify dashboard).
- **✅ P7 COMPLETE (2026-07-04): Spark↔pandas parity proven in CI.** The new
  `spark-parity` CI job runs `spark/parity_check.py` on real **Spark 4.1.2**
  (Java 17, Linux) every push/PR — GREEN: `features dedup 30=30`, `tracks dedup
  90=90`, `temporal centroid parity identical within 1e-3`. Artifact
  `docs/SCALING.md` (honest 10K/1M design: bottleneck is acquisition+DSP not
  transforms; GCS + BigQuery external tables; Spark-vs-Dataflow per stage;
  hash-bucket partitioning; one thin cloud slice = BigQuery + P5 MCP tool).
  Zero cloud spend (D-3). **P0–P7 COMPLETE.**
- **PR state (2026-07-04):** PR #1 (P0–P5) MERGED. PR #2 (`p6/ci`→main) &
  PR #3 (`p6/readme`→`p6/ci`) MERGED — **but #2 merged before #3, so `p6/ci`
  is 4 commits AHEAD of main: P6 batch-2 (exact feature-contract D-4, legacy
  archive, README rewrite) is stranded on `p6/ci`, NOT on main.** The P7 PR
  (`p7/scale-slice`→main) therefore delivers those 3 stranded P6 commits + the
  2 P7 commits together — one merge catches main fully current through P7.
  (Verify: `git log --no-merges origin/main..p7/scale-slice`.)
- **How to work:** `/pipeline-partner` for feature/design sessions (reads and
  updates this file automatically). `/warehouse-audit` after any pipeline run
  or transform change. Ground rules in `CLAUDE.md`.

---

**Purpose.** Master memory file. New session: READ THIS FIRST — caught up, no
re-derivation. Architecture/conventions ground truth is `CLAUDE_INSTRUCTIONS.md`
(module map, ADRs); this file tracks the *work*: verified status, results,
conventions, session log.

**How to update (protocol).** At session END: (a) rewrite status + ➡️ NEXT
ACTION, (b) update the phase-results section, (c) add new key files, (d) append
one dated Session-log line ending "**Left off:** …". Map, not transcript —
narrative goes to `notes/engineering_journal.md`, plans to
`notes/project_roadmap.md`. Fix stale facts on sight.

---

## 1. Key files map

| Path | What it is |
|---|---|
| `CLAUDE.md` | Bootloader: ground rules (bridge key, Parquet-only, API guardrails, synthetic tests). Stable. |
| `SPEC.md` | **The approved design (2026-07-03):** vision, JD/resume-gap mapping, phases P0–P7 w/ acceptance criteria, non-goals, decision log. Supersedes CLAUDE_INSTRUCTIONS' roadmap + roadmap.md gameplan detail. |
| `CLAUDE_INSTRUCTIONS.md` | The architecture manual: medallion design, module map, 77-dim feature spec, ADR-001…006, code standards, phase roadmap detail. Current-State table frozen at 2026-05-06. |
| `PR_REFERENCE.md` | Historical: the Copilot PR write-up for Phases 1–4. Describes a webapp + git history this repo copy does NOT contain (see journal #4). |
| `notes/project_roadmap.md` | Severity-ranked weaknesses + the phase gameplan with exit criteria. |
| `notes/engineering_journal.md` | Numbered insight journal — surprises, not progress. |
| `llm_knowledge_base/` | **READ-ONLY synced copy** of the course knowledge base (technique cards, skill patterns, tooling matrix). Canonical: `language-models/kb/` — see `llm_knowledge_base/KB_PROVENANCE.md`; never edit here, propose upstream. |
| `src/ingestion/` | Spotify PKCE auth, top-items fetchers, YouTube→MP3 downloader (rate-limited, idempotent), Parquet serializer. Tests: `test_ingestion.py`, `test_audio_downloader.py`. |
| `src/dsp/` | librosa loader, 77-dim feature extractor, batch collection extractor, optional PANNs embeddings. Tests: `test_dsp.py`, `test_collection_extractor.py`. |
| `src/warehouse/` | Medallion: `staging.py` (Bronze) → `cleansed.py` (Silver) → `modeled.py` (Gold star schema; fact denormalized, agent-optimized per ADR-002). |
| `src/search/` | FAISS store, UMAP visualizer, DAG pipeline. Test: `test_search.py`. |
| `src/analysis/` | Temporal drift (cosine, ADR-003) + matplotlib visuals. |
| `spark/` | PySpark jobs: temporal centroid aggregation, feature transform. |
| `scripts/run_pipeline.py` | The 7-step orchestrator (`--clean`, `--skip-download`, `--skip-extract`, `--limit N`). REBUILT 2026-07-03 — the uploaded copy was a notebook-runner; this now matches the CLAUDE_INSTRUCTIONS step table. |
| `.env` (local only, gitignored) | `SPOTIPY_CLIENT_ID` + `SPOTIPY_REDIRECT_URI` — that's ALL. PKCE-only project: no client secret exists anywhere (code/env/deploy) as of 2026-07-03. auth.py has no in-code fallbacks. |
| `notebooks/` | `pipeline_walkthrough.ipynb`, `temporal_analysis.ipynb` + build script. |
| `.agent_prompts/` | Role prompts: 01 Spotify API guardrails (2026 deprecations), 02 DSP architect, 03 data orchestrator. Imported from working drafts 2026-07-03. |
| `.claude/skills/` | The harness: pipeline-partner, warehouse-audit (+ `audit_warehouse.py`), env-verify. Design doc: `.claude/README.md`. |
| `src/analysis/clustering.py` | SPEC P1: 77-dim-space KMeans + coarse-genre rules + acoustic cluster naming. `VECTOR_77_COLUMNS` = the contract column list. Test: `test_clustering.py`. |
| `scripts/build_taste_map.py` | One command → `artifacts/taste_map.png` + `modeled/cluster_assignments.parquet`. Deterministic (seed 42). |
| `src/analysis/insights.py` | SPEC P2: pure section builders → versioned `insights.json` (schema v1) + `INSIGHTS.md`. Pipeline step 8. Optional LLM polish (D-5: additive, never load-bearing). Test: `test_insights.py`. |
| `scripts/build_insights.py` | One command → `artifacts/insights.json` + `artifacts/INSIGHTS.md` (`--llm-polish` optional). |
| `scripts/build_trend_charts.py` | SPEC P3: one command → 4 σ-normalized trend PNGs in `artifacts/` (radar, heatmap, distributions, artist flow). Test: `src/analysis/test_visualizations.py`. |
| `src/export/` | SPEC P4: `portfolio.py` (pure Jinja2 render, autoescape — P8-safe) + `templates/portfolio.html`. Test: `test_export.py` (self-containment + XSS). |
| `scripts/build_report.py` | THE one command: fresh gold layer → regenerate all artifacts → `taste_report.html` (0.99 MB, offline). `--no-rebuild`, `--llm-polish`. |
| `src/agent/` | SPEC P5: `warehouse_agent.py` (pure DuckDB retrieval core — 2-layer SQL security D-10; reused by P8 RAG) + `mcp_server.py` (FastMCP stdio: get_schema / query_warehouse / get_insights). Test: `test_agent.py` (30). Run: `python -m src.agent.mcp_server`. |
| `src/webapp/` | **SPEC P8 slice 1: FastAPI pilot.** `auth_web.py` (session-scoped PKCE — token in session, CSRF state gate, D-8 no secret), `sessions.py` (TTL `SessionStore` + signed cookie + rotate), `featurestore.py` (bridge-key overlap-join + acoustic insight), `app.py` (routes: `/ login callback dashboard logout healthz`), `config.py`, `templates/`, `static/`. Test: `test_webapp.py` (15). Run: `uv run python scripts/run_webapp.py` → :8000. |
| `docs/AGENT_ACCESS.md` | P5 artifact: MCP registration config (Claude Desktop/Code) + security model + live demo transcript. |
| `docs/SCALING.md` | P7 artifact: honest 10K/1M-track scaling design (bottleneck = acquisition+DSP; GCS/BigQuery; Spark-vs-Dataflow; the `spark-parity` CI proof). |
| `docs/P8_PLAN.md` | P8 build plan (FastAPI + Jinja2; session PKCE; feature-store overlap-join; RAG; 4-slice sequence). Slices 1, 1.5, 2 BUILT. |
| `docs/APP_SPEC.md` | **THE long-term product spec, v2 LOCAL-FIRST (2026-07-07): $0 external spend — owner-PC hosting via free HTTPS tunnel, SQLite+WAL serving cache (`DATABASE_URL`→Postgres upgrade), DB-as-queue worker `--loop`, clustering + acoustic signature + spectrograms + drift, RAG classification (Phase 2). Epics A✅ B✅ C→E→D + decisions D-11…D-17. Extends `SPEC.md`; supersedes its own v1 cloud assumptions.** |
| `artifacts/` | COMMITTED portfolio outputs (PNGs, reports) — unlike `data/`, these are deliverables. |
| `legacy/` | Archived pre-pipeline v0 (moved 2026-07-04, P6): `legacy/spotify/` (secret-based v0 scripts) + `legacy/00_tools/` (media_converter). Excluded from ruff/tests/CI; nothing in `src/` imports it. See `legacy/README.md`. |
| `data/` (gitignored) | `raw_audio/{track_id}.mp3` + `warehouse/{staging,cleansed,modeled}/` Parquet. Rebuild: `run_pipeline.py`. |

## 2. Phase results (verified vs. claimed)

- **Phases 1–3 (✅ VERIFIED 2026-07-03).** End-to-end proven on this machine:
  - **Env:** conda base py3.13.5 (see §3 for invocation); 55/55 pytest.
  - **Smoke** (`--skip-download --skip-extract`, 62.5s): 150 track entries
    (50×3 ranges, 117 unique), 105 artist entries → staging → cleansed →
    star schema (fact 150 rows, dim_tracks 117, dim_artists 59). Audit:
    zero errors, expected FEATURE_DRIFT only (no features yet).
  - **Real run** (`--limit 4`): 9 unique tracks — 9/9 YouTube downloads
    (192kbps MP3, `{id}.mp3`), 9/9 DSP extractions. First attempt failed
    9/9: conda ffmpeg lacks libmp3lame (journal #7) → Gyan FFmpeg 8.1.2 via
    winget. Rerun: all green in 290.5s; idempotency + Silver dedup observed
    working (12 dup rows removed across snapshots).
  - **Final audit ALL-GREEN:** errors 0; every flag false; fact 150 rows ×
    82 numeric feature cols; 9 MP3s ↔ metadata fully reconciled; only soft
    warning "108 tracks not yet downloaded".
  - **Feature contract clarified (journal #8):** `to_summary_vector()` = the
    frozen 77-dim FAISS contract (untouched). Warehouse tables now carry 82
    numeric feature cols (chroma_std ×12 + spectral_contrast_std ×7 were
    computed-but-never-serialized; spectral_bandwidth ×2 + flatness ×1 were
    spec'd-but-never-computed — all added). CLAUDE_INSTRUCTIONS' 77-table
    is imprecise (different membership than the vector's 77) — doc fix
    pending, audit tolerance ±7 covers it.
  - **Security (⚠️ action owed):** hardcoded client ID+SECRET removed from
    `auth.py` and legacy `spotify/spotify_config.py`; `.env` created;
    `.gitignore` now covers `data/` (PKCE token cache). **The old secret
    shipped in the public upload commits — Jordan must rotate it in the
    Spotify Developer Dashboard.**
- **SPEC P0 — full-corpus run (✅ COMPLETE 2026-07-03, 56.6 min).**
  Detached run `run_20260703_145234` + completion check: fetch 150 entries
  (117 unique) + 105 artists; downloads **108/108 success, 0 failed,
  0 no_match** (9 skipped-cached); DSP **108/108 extracted, 0 failed**.
  Warehouse: 117 MP3s all reconciled; cleansed_features 117×87 (82 numeric);
  fact 151×93; dim_tracks 118; dim_artists 60. **Audit ALL-GREEN** — only
  soft note: 1 metadata-only track (fell out of top-50 between the morning
  smoke and evening fetch — snapshot-union semantics working as designed;
  will self-heal if it re-enters the charts). PKCE-only auth proved live
  end-to-end (zero secret anywhere).
- **Old Copilot webapp — DECIDED (D-7): reinstated as SPEC P8 production
  pilot** (public site, per-visitor PKCE auth, RAG over the P5 core). The
  original FastAPI upload was never in this repo; P8 rebuilds lean. Not
  started; sequenced after P6.
- **SPEC P1 — taste map (✅ COMPLETE 2026-07-03, audit ALL-GREEN).**
  - **Warehouse:** artists path finished end-to-end — `fetch_artists_by_ids`
    (batch GET /artists) backfills primary artists missing from top-artists
    (28 backfilled, 1 API call); `build_cleansed_artists` (94×6, one row per
    artist); `dim_artists` enriched with genres (60×6). Track-level genre
    coverage **81/118** — the honest ceiling; Spotify 2026 genre arrays are
    often empty (journal #9).
  - **Clustering (`src/analysis/clustering.py`):** clusters in EXACTLY the
    frozen 77-dim vector space (`VECTOR_77_COLUMNS` mirrors
    `to_summary_vector`); standardized + L2-normalized (KMeans euclidean ≈
    cosine, ADR-003 doctrine); k by silhouette (chose k=3, 0.094 — music is
    a continuum, honest); deterministic (seed 42, verified by unit test).
    Clusters named ACOUSTICALLY via centroid z-scores ("Smooth · Dark" /
    "Noisy · Bright" / "Gentle · Loud") because genre metadata degenerates
    under a dominant artist (journal #9).
  - **Artifacts:** `artifacts/taste_map.png` (committable README hero;
    genre-colored, sized by temporal persistence, cluster-annotated) +
    `modeled/cluster_assignments.parquet` (117×8, bridge-keyed, audit-clean).
  - **Tests:** 23 in `src/analysis/test_clustering.py` + 7 in new
    `src/warehouse/test_warehouse.py` → suite total 85, all green.
  - One command rebuilds: `python scripts/build_taste_map.py`.
- **SPEC P2 — insight engine (✅ COMPLETE 2026-07-03).**
  - **`src/analysis/insights.py`:** pure section builders (corpus, drift,
    clusters, persistence, superlatives, genres) → versioned
    `artifacts/insights.json` (schema v1 — the contract P5's MCP
    `get_insights()` and P8's RAG read) + templated `artifacts/INSIGHTS.md`.
    Runs as **pipeline step 8** (skips politely on metadata-only smokes);
    standalone: `python scripts/build_insights.py [--llm-polish]`.
  - **LLM polish (SPEC D-5 honored):** optional executive-summary prose via
    Claude API (`claude-opus-4-8` default, `INSIGHTS_LLM_MODEL` override);
    adds a clearly-marked section, never touches deterministic tables,
    silently degrades on any failure (no SDK/credentials/API error).
  - **Drift metric FIXED en route (ADR-003 amended, D-9, journal #10):**
    cosine flatlined at 0.0000 on raw centroids (scale domination) and
    pegged at 1.4998 on z-centroids (centering geometry) — replaced with
    **RMS σ-shift** between standardized centroids. Sanity anchors:
    constant corpus 0.0 / strong synthetic ~2σ / real corpus **0.1405σ
    (Minimal Drift, stability 0.859)** — credible for this corpus (9
    all-three-ranges favorites, Muse ×31).
  - **Tests:** 13 in `test_insights.py` (schema-stability, crafted-winner
    superlatives, persistence counts, drift anchors, markdown determinism)
    → suite total 98, all green.
- **SPEC P3 — temporal trend visuals (✅ COMPLETE 2026-07-03).**
  - `python scripts/build_trend_charts.py` → 4 deterministic PNGs in
    `artifacts/`: `drift_radar.png`, `temporal_heatmap.png`,
    `feature_distributions.png`, `artist_flow.png` — each one plotter
    function fed from the gold layer alone.
  - **Honesty fix (journal #10 postscript):** radar/heatmap min-max
    normalization over 3 window-centroids pinned every axis to [0,1] by
    construction (a 0.75% brightness shift rendered as full-scale
    divergence, contradicting the 0.14σ verdict). Both plotters now take
    `corpus_stats` and normalize in σ units — radar rings = 1σ, heatmap
    diverging ±1σ — so visual divergence = effect size = drift-score
    units. Legacy min-max kept as fallback for the notebook path.
  - **plot_umap_by_time_range deliberately EXCLUDED** from artifacts: it
    recomputes UMAP on raw unscaled features (scale-domination artifact)
    and multi-range tracks would plot identical overlapping points;
    `taste_map.png` (P1) is the canonical projection.
  - Tests: 10 in `test_visualizations.py` (render + σ-mode + zero-std +
    degenerate inputs) → suite total 108, all green.
- **SPEC P4 — portfolio export (✅ COMPLETE 2026-07-03) → PHASE 5 DONE.**
  - `python scripts/build_report.py` = ONE command from a fresh gold layer:
    regenerates taste map + insights + trend charts (all deterministic),
    then renders **`artifacts/taste_report.html` — 0.99 MB, single file,
    every image a base64 data: URI, opens offline** (test-enforced: no
    external/file refs, no scripts).
  - `src/export/portfolio.py` (pure render, Jinja2 **autoescape ON** — track
    names are untrusted; P8 renders other users' libraries through this
    template, XSS-escape test included) + `templates/portfolio.html`
    (dark GitHub theme matching the charts).
  - Report sections: hero (drift σ / stability / persistent favorites),
    taste map + cluster table, σ-unit charts, top-10 per window,
    staying power + superlatives, genre chips, methodology footer
    (API-deprecation origin story, PKCE-no-secret, medallion, σ-shift).
  - Verified rendered in a browser (a11y snapshot: all sections + images
    load, zero console errors). Tests: 7 in `src/export/test_export.py` →
    suite total **115**, all green.
  - **Roadmap Phase-5 exit criterion met**; W-4 resolved.
- **SPEC P5 — Agent Access Layer / MCP (✅ COMPLETE 2026-07-03).**
  - **`src/agent/warehouse_agent.py`** — pure retrieval core (DuckDB +
    pandas, no MCP import): `get_schema()` (tables/cols/types + agent
    descriptions from `column_descriptions` + join-key notes),
    `query_warehouse(sql)` (read-only, returns `{ok,columns,rows,row_count,
    truncated}`, never raises), `get_insights()` (serves insights.json v1).
    Reused verbatim by P8's RAG.
  - **Security (D-10, journal #11) — two layers:** statement guard
    (`is_safe_sql`: single SELECT/WITH, denylist verbs+file-funcs) for a
    clear read-only contract; the REAL boundary is the DuckDB sandbox —
    gold Parquet → native in-memory tables → `enable_external_access=false`
    + `lock_configuration=true`. Bypassing the guard still can't read a file
    (PermissionException) or re-enable access (InvalidInputException); both
    proven by test.
  - **`src/agent/mcp_server.py`** — thin FastMCP stdio wrapper, lazy agent
    init, logs→stderr (stdout is JSON-RPC). Run: `python -m src.agent.mcp_server`.
  - **Deps added** (conda env + requirements): `mcp>=1.2.0`, `duckdb>=1.1.0`,
    `jinja2>=3.1.0`. pydantic auto-bumped 2.10→2.13, no breakage.
  - **Verified:** real MCP stdio handshake (initialize → list_tools =
    [get_schema, query_warehouse, get_insights] → query returns Muse 31 /
    Linkin Park 6 / Green Day 5 → DROP rejected); 5 live taste questions
    answered against the real warehouse; `docs/AGENT_ACCESS.md` has the
    registration config + transcript. Tests: 30 in `src/agent/test_agent.py`
    → suite total **145**, all green.
- **SPEC P6 — platform hardening (✅ COMPLETE 2026-07-04, 6 branches).**
  - **uv/pyproject** (`p6/uv-pyproject`): `pyproject.toml` (deps + dev extra +
    `[tool.pytest]`, `package=false`) + `uv.lock` (88 pkgs); requirements.txt
    kept as pip export.
  - **ruff** (`p6/ruff`): linter (not formatter), `select E,F,I,B; ignore
    E501`; **122 findings → 0** (import sort, unused-import, exception
    chaining `from`, `strict=` zips, `__all__`); UP deliberately excluded.
  - **CI** (`p6/ci`): GitHub Actions `uv sync --frozen` → ruff → pytest, on
    push+PR. **Caught a real cross-platform bug on run #1** — newer mpl on
    Linux (`boxplot(labels=)` renamed, `plt.cm.get_cmap` removed); fixed
    version-agnostically → green (~1m50s). Also stranded-faiss-fix folded in.
  - **feature-contract (D-4)** (`p6/feature-contract-audit`): COLUMN_DESCRIPTIONS
    26→93 (full 82-feature contract, generated families + hand-written base);
    audit now does EXACT-list verification (documented − metadata vs actual);
    `test_feature_contract.py` locks DSP output == docs (3 tests). 82==82.
  - **legacy** (`p6/legacy-archive`): `spotify/` + `00_tools/` → `legacy/`
    (+ `legacy/README.md`); ruff exclude simplified; W-7 resolved.
  - **README** (`p6/readme`): rewritten for the 90-second reviewer path (hero
    taste map, drift result, 3 commands w/ real output, MCP demo, CI badge).
  - Suite total **148** (145 + 3 contract tests), ruff clean, audit ALL-GREEN.
  - Resolves W-5 (env reproducibility), W-6 (CI), W-7 (legacy), W-8 (README).
- **Repo hardening + harness (2026-07-03 ✅).** Nested `audio-agentic-pipeline/`
  folder flattened to root; `.gitignore` added; committed `__pycache__`/
  anaconda db untracked; `.agent_prompts/` imported; CLAUDE.md bootloader +
  notes/ memory docs + 3 skills installed.

## 3. Working conventions

- **Ground rules** in `CLAUDE.md`; architecture + code standards in
  `CLAUDE_INSTRUCTIONS.md` (Google docstrings, typed signatures, logging not
  print, dataclass configs, snake_case columns).
- **Measure before claiming:** any pipeline/transform change → rerun
  `pytest src/ -v` + `/warehouse-audit`; record row counts and pass/fail here.
  A feature isn't "working" until the audit says the warehouse it produced is
  coherent.
- **Portfolio lens:** every feature should earn a line in the README/demo
  story for a platform-DE audience (scale, quality, DX, agents-on-data).
- **Python env (verified 2026-07-03):** conda BASE env is the project env —
  invoke as `C:\Users\jverc\anaconda3\python.exe` (py3.13.5, all deps incl.
  python-dotenv). ⚠️ Bare `python` on PATH is an unrelated dep-less 3.11.
  For runs with downloads, put Gyan FFmpeg first on PATH
  (`%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_…\ffmpeg-8.1.2-full_build\bin`)
  — conda's ffmpeg lacks libmp3lame. Harness scripts are uv single-file
  (PEP 723) so they run independent of the project env. Full uv/pyproject
  migration = roadmap W-5.
- **Git:** commit-sized reviewable chunks; Jordan pushes. History before
  2026-07-03 is two web-upload commits — treat PR_REFERENCE as narrative, not
  git truth.

## 4. Session log

- **(backfilled) 2026-05:** Copilot-assisted build of Phases 1–4 on a
  separate copy (see PR_REFERENCE). Docs written (CLAUDE_INSTRUCTIONS).
- **(backfilled) 2026-07-03 (upload):** Repo created on GitHub via web
  upload — nested folder, no webapp, bytecode included, README stub.
- **2026-07-03 (session 1):** Reviewed repo vs. docs (journal #4).
  Hardened structure (flatten, .gitignore, untrack bytecode/IDE db).
  Installed the playbook harness (bootloader, notes/, 3 skills, warehouse
  audit script) modeled on wasteland101/language-models. **Left off: nothing
  run yet — next is `/env-verify` → metadata-only smoke → small real run →
  `/warehouse-audit`, then Phase 5.1.**
- **2026-07-03 (session 2 — Phase V verification):** env-verify found the
  real env (conda base 3.13.5; 55/55 tests) plus a committed Spotify secret
  (scrubbed from auth.py + legacy config; journal #5) and a fictional run
  command — rebuilt `run_pipeline.py` as the documented 7-step orchestrator
  (journal #6). Smoke run green (150 entries, 62.5s). Real run: first
  attempt 0/9 downloads (conda ffmpeg lacks libmp3lame → winget Gyan build;
  journal #7), rerun 9/9 downloads + 9/9 DSP. Audit flagged the feature
  contract: to_summary_dict dropped 19 computed cols, 3 spec'd cols never
  computed — fixed extractor (warehouse 82 cols; vector stays 77; journal
  #8), patched audit META_COLS + column_descriptions exemption, re-extracted.
  **Final audit ALL-GREEN — W-1 RESOLVED, Phase V complete.** env-verify
  skill upgraded (capability checks). **Left off: warehouse verified but
  only 9/117 tracks have audio+features — next session: full run
  (`run_pipeline.py`, ~1.5–3 h background) + audit, then Phase 5.2 genre
  clustering. ⚠️ Jordan: rotate the Spotify client secret, then commit +
  push this session's changes (working tree only — nothing committed yet).**
- **2026-07-03 (session 3 — design/spec):** Jordan handed over lead design
  with the old working-folder materials (Copilot-era CLAUDE_INSTRUCTIONS +
  PR_REFERENCE, agent prompts, rendered temporal_analysis outputs, the
  Spotify Platform JD, resume). Wrote **`SPEC.md` v1.0**: vision anchored on
  the 2026 API-deprecation origin story; JD/resume-gap evidence mapping
  (day job proves BigQuery/Dataform — this repo must prove production
  Python, working Spark, CI, and BUILDING agent-data systems); phases P0–P7
  with acceptance criteria; AI in three deterministic-first roles. Key
  decisions: webapp DESCOPED (D-1), MCP Agent Access Layer added as P5
  (D-2), Spark-first scale slice w/ BigQuery stretch (D-3), feature
  contract becomes an exact column list in the audit (D-4). Doc map
  aligned: CLAUDE.md + roadmap now point at SPEC. **Left off: no code
  changes this session — next is SPEC P0 (full-corpus run + audit), then
  P1 taste map. Secret rotation still owed.**
- **2026-07-03 (session 4 — PKCE purge + P0 launch + pilot decision):**
  Jordan approved the spec, exercised owner override on the webapp (→ SPEC
  D-7: P8 production pilot — public site, per-visitor PKCE auth, RAG
  insights over a bridge-key feature store), and is rotating the old
  secret. Executed the **PKCE-only purge (D-8)**: deleted
  `get_public_spotify`/client-credentials flow from auth.py, fetchers now
  default to the PKCE client, exports/tests/notebook updated, legacy
  spotify_config tombstoned, `.env`/CLAUDE.md/env-verify/PR_REFERENCE
  scrubbed — zero `SPOTIPY_CLIENT_SECRET` references remain repo-wide;
  55/55 tests green. **Launched P0** (detached, pid 18852, snapshot
  `run_20260703_145234`, limit=50): PKCE auth from cache, downloads
  streaming. SPEC amended (P8, D-7/D-8, risks: dev-mode 25-user allowlist
  gate, pilot privacy). **Left off: P0 downloading in background — on
  completion run `/warehouse-audit`, record P0 numbers, then P1. Rotation
  in Jordan's hands.**
- **2026-07-03 (session 4, completion check):** P0 finished in 56.6 min —
  108/108 downloads, 108/108 extractions, zero failures; audit ALL-GREEN at
  full scale (117 MP3s, fact 151×93, 82 numeric feature cols; 1 soft
  metadata-only track from inter-snapshot chart movement). P0 acceptance
  criteria met; evidence recorded in §2. **Left off: warehouse is
  portfolio-ready — next is SPEC P1 (taste map: clustering.py + UMAP genre
  visual). Secret rotation still in Jordan's hands.**
- **2026-07-03 (session 5 — SPEC P1 built + accepted):** Artists path
  (batch genre backfill → cleansed_artists → enriched dim_artists; coverage
  81/118), `clustering.py` (77-dim contract space, cosine-normalized KMeans,
  silhouette k=3, deterministic), acoustic cluster naming after genre
  labels degenerated under a Muse-dominated corpus (journal #9),
  `build_taste_map.py` → `artifacts/taste_map.png` + bridge-keyed
  `cluster_assignments.parquet`. All 4 SPEC P1 acceptance criteria met;
  audit ALL-GREEN; 85 tests green. scikit-learn pinned in requirements.
  **Left off: P1 done — next is SPEC P2 (insight engine:
  `src/analysis/insights.py` → insights.json → INSIGHTS.md, pipeline step
  8). Secret rotation + commits still in Jordan's hands.**
- **2026-07-03 (session 6 — SPEC P2 built + accepted):** Insight engine
  shipped: pure section builders → schema-versioned insights.json +
  INSIGHTS.md; pipeline step 8 (8-step orchestrator now; smoke runs skip
  politely); `--llm-polish` per D-5 (claude-opus-4-8, additive-only,
  graceful degradation). **The drift instrument was broken and got fixed
  properly (journal #10):** cosine-on-raw read 0.0000 (scale domination),
  cosine-on-z read 1.4998 (centering forces ~120° angles) — final metric
  RMS σ-shift with sanity anchors at both ends; ADR-003 amended (SPEC D-9).
  Real corpus: **0.1405σ Minimal Drift, stability 0.859**. 98 tests green.
  **Left off: P2 done — next is SPEC P3 (temporal trend visuals wired to
  the real warehouse → artifacts/ PNGs). Secret rotation + commits still
  in Jordan's hands; consider committing P0–P2 as reviewable chunks.**
- **2026-07-03 (session 7 — SPEC P3 built + accepted):** 4 trend charts
  shipped via `build_trend_charts.py` (radar, heatmap, distributions,
  artist flow — one plotter each from the gold layer). Caught + fixed the
  visual twin of journal #10: min-max over 3 centroids pins axes to [0,1],
  amplifying 0.75% shifts to full scale — both charts now σ-normalized via
  `corpus_stats` so they AGREE with the 0.14σ drift verdict.
  `plot_umap_by_time_range` deliberately excluded (raw-cosine UMAP +
  duplicate-point occlusion); taste_map.png stays canonical. 108 tests
  green. **Left off: P3 done — next is SPEC P4 (single-file
  `taste_report.html`: Jinja2 + inline CSS + base64 PNGs + insights.json
  narrative; <10 MB, offline). Rotation + commits in Jordan's hands.**
- **2026-07-03 (session 8 — SPEC P4 built + accepted → PHASE 5 COMPLETE):**
  `src/export/` (pure Jinja2 render, autoescape + XSS test for P8 reuse) +
  `scripts/build_report.py` (regenerates ALL inputs deterministically, then
  renders). `taste_report.html`: 0.99 MB, fully self-contained
  (test-enforced), verified rendering in a browser via a11y snapshot.
  Determinism reconfirmed end-to-end on the rebuild (same k=3, same
  0.1405σ). 115 tests green. W-4 resolved — roadmap Phase-5 exit criterion
  met. **Left off: Phase 5 (P1–P4) done — next is SPEC P5 (MCP Agent
  Access Layer: get_schema / query_warehouse read-only / get_insights).
  Rotation + commits in Jordan's hands — the tree now holds P0–P4.**
- **2026-07-03 (session 9 — SPEC P5 built + accepted):** Agent Access Layer
  shipped. Pure `warehouse_agent.py` core + thin `mcp_server.py` (FastMCP
  stdio); 3 tools (schema / read-only query / insights). Security is
  capability-removal not denylist (D-10, journal #11): DuckDB native
  in-memory tables + `enable_external_access=false` + `lock_configuration=
  true` — sandbox proven to block file reads even when the SQL guard is
  bypassed. Installed mcp + duckdb (+ jinja2 pin); pydantic 2.10→2.13, no
  breakage. Verified via a real MCP stdio handshake + 5 live taste
  questions; wrote `docs/AGENT_ACCESS.md`. 30 new tests → **145 green**.
  **Left off: P5 done — next is SPEC P6 (platform hardening: uv/pyproject +
  lockfile, ruff, GitHub Actions CI, exact feature-contract audit per D-4,
  legacy archival, README rewrite).**
- **2026-07-03 (session 9 wrap):** P0–P5 committed as **11 reviewable
  commits** on branch `feat/insight-and-agent-layers` (security scrub first
  and isolated; verified no `.env`/`data`/secret tracked). **Spotify client
  secret ROTATED in the dashboard** — the last standing security item is
  CLOSED (PKCE never used the secret; rotation kills the git-history leak).
  **Left off: branch is committed but NOT pushed — Jordan pushes. Then P6.**
- **2026-07-04 (session 10 — SPEC P6 complete):** Jordan pushed + merged
  PR #1 (P0–P5 → main). Then P6 as **6 stacked branches / PRs** (per-piece
  for revertability): uv/pyproject+lock, ruff (122→0), GitHub Actions CI
  (green — caught a real matplotlib-version bug on Linux that local testing
  couldn't), exact feature-contract audit (D-4, 26→93 descriptions,
  82==82), legacy archival (W-7), README rewrite (W-8). Also folded in the
  stranded faiss lazy-load fix. Suite 148 green, ruff clean, audit
  ALL-GREEN, CI green on GitHub. PR #2 (`p6/ci`→main) open + mergeable;
  pieces 4–6 on further stacked branches. **Left off: P6 done — next is
  SPEC P7 (Spark scale slice + docs/SCALING.md). Merge the P6 PR(s) when
  ready; pieces 4–6 rebase onto main after.**
- **2026-07-05 (session 11 — SPEC P7 complete + P8 design):** P7 scale slice:
  `spark/parity_check.py` proves PySpark == pandas (dedup 30/90, centroid parity
  <1e-3) via a new `spark-parity` CI job on real **Spark 4.1.2** — caught a Java
  bug (lock resolves pyspark 4.1.2, which dropped Java 8/11; bumped CI to Java 17;
  journal #12). Wrote `docs/SCALING.md`. **PR #4 (p7→main) MERGED** — found that
  #2-before-#3 had stranded P6 batch-2 on `p6/ci`, so #4 carried it to main too;
  **main now current P0–P7.** Branch-tidy: pruned all 8 merged branches (local +
  remote) → repo is `main`-only. Stopped a 21h-orphaned local Spark bg task (dead
  process, stale UI chip). Then **P8 design APPROVED: FastAPI + Jinja2**, full
  build plan in `docs/P8_PLAN.md` (4 slices). Warehouse audit ALL-GREEN (117
  MP3s). **Left off: P8 design done — next is P8 slice 1 (`src/webapp/` FastAPI
  auth + dashboard). Jordan: register `http://127.0.0.1:8000/callback` +
  set `SESSION_SECRET_KEY` before end-to-end auth.**
- **2026-07-05 (session 11 cont. — P8 slice 1 built):** Plan committed (PR #5,
  `p8/plan`). Jordan registered the `:8000/callback` redirect URI + I generated
  `SESSION_SECRET_KEY` into `.env` (gitignored; infra, not the Spotify secret).
  Built `src/webapp/` (FastAPI + Jinja2): session-scoped PKCE, TTL SessionStore,
  bridge-key overlap-join insight, dashboard. 15 tests → **163 green**, ruff
  clean. Added web deps (fastapi/uvicorn/itsdangerous/python-multipart) + httpx
  (dev) to pyproject/lock. Live-smoked on :8000 — landing renders, `/login`
  builds the correct S256 authorize URL, no `client_secret` on the wire (D-8).
  **Left off: slice-1 code uncommitted on `p8/plan` working tree; awaiting
  Jordan's real-login acceptance click-through, then commit + slice 2 (RAG
  `/ask`). Dev server may still be running on :8000.**
- **2026-07-05 (session 11 cont. — P8 pilot VERIFIED LIVE + paused):** Real
  login worked end-to-end (fixed a Windows cp1252 crash on reused pipeline
  emoji prints → force UTF-8 in `run_webapp.py`; fixed the header auth-state +
  `energy 0` formatting bugs Jordan spotted). Committed slice 1 (`p8/slice-1`,
  `bc2cf41`). Then slice 1.5 enrichments (Jordan picked all 4): album art, top
  artists+genres, taste drift (`drift_profile` — reuses D-9 σ-shift) — verified
  live (41/41 overlap, **Moderate drift 0.211**, 20 vs 20), committed `3eff3c7`.
  PR #5 (plan) MERGED to main; opened **PR #6 (`p8/slice-1`→main)** for the
  pilot demo. 166 green, ruff clean. Dev server stopped (clean). **Left off:
  owner PAUSED — pilot locked in as a working demo. Next when resumed: RAG
  `/ask` (slice 2), then Dockerfile → Cloud Run, + a polish/UX pass. Merge
  PR #6 when ready.**
- **2026-07-07 (session 12 — RAG slice 2 + FULL-APP VISION SPEC):** Built P8
  slice 2 (RAG `/ask`, `rag.py` — grounded LLM w/ deterministic fallback, 7
  tests → 173 green), committed on `p8/slice-1` (PR #6). Then owner set the
  long-term vision; wrote **[`docs/APP_SPEC.md`](docs/APP_SPEC.md)** — the full
  product spec: per-user extraction + **shared track-keyed feature-cache DB
  (Postgres+pgvector)**, audio-features dashboard (hover/deep-dive/spectrogram),
  ML clustering of songs AND artists, drift dashboard, RAG classification
  (Phase 2); Epics A–E, build order, decisions **D-11…D-15** (D-11 supersedes
  P8's no-acquisition non-goal; D-13 flags longitudinal drift needs opt-in
  snapshots). **Left off: vision spec approved-pending; next concrete build =
  Epic A (feature-cache DB + async extraction). Owner still owns GCP/domain +
  Spotify prod config. `/ask` live-test + PR #6 merge still pending owner.**
- **2026-07-08 (session 13 — dual vision specs):** Pipeline-partner design
  session (audit ALL-GREEN, usual soft warning). Reviewed the newly-synced
  `llm_knowledge_base/` (7 technique cards) card-by-card against the live app;
  verified via live fetch that Spotify's `get-audio-features` is officially
  **Deprecated** (design target, never a data source — rule 3). Wrote
  **[`docs/VISION_SPECS.md`](docs/VISION_SPECS.md)**: Vision A = 3 surgical
  LLM upgrades (eval set, JSON contracts, optional Ollama) + 2 deliberate
  rejections grounded in the KB's own lessons; Vision B = the Audio-Feature
  Explorer (perceptual-v1 derived features w/ honest tiers, 3 gold marts,
  `/explore` dashboard). Aggro/value matrix + recommendation: **Epic F = B
  with A1+A2 as slice F0.** **Left off: awaiting Jordan's pick on
  VISION_SPECS.md; no code written this session.**
- **2026-07-09 (session 14 — new-user pipeline hardening):** Jordan added a
  tester and asked how we ENSURE new visitors' songs get downloaded+extracted.
  /resume verified: flow already worked live (their one uncached track:
  queued 00:45:39 → done 00:46:31, spectrogram + online cluster assignment) —
  but the audits exposed the ensure-gaps, closed in 4 pushed commits
  (df65650, 29a405f, 2db102c, ce325ed; 264 green; CI green on tip — the
  29a405f run auto-cancelled by the next push's concurrency, covered by the
  later runs): worker heartbeat + orphan re-queue + WORKER_DOWN/QUEUE_STUCK
  app-verify flags (the new flag caught its own blind spot on first run —
  journal #16); post-drain `rebuild_marts` + mtime-keyed explore loaders
  (117→118 in the marts, new tracks reach /explore unattended); seed ghost
  guard + deleted the live Hummer ghost row (journal #17 — "119 tracks" had
  counted it); `register_autostart.ps1` + SELF_HOSTING §4 + logs/ gitignore.
  Permission classifier correctly blocked bouncing live processes and
  registering persistence — handed to owner. **Left off: OWNER 2-min step
  (see ➡️ NEXT ACTION): stop consoles → register_autostart.ps1 →
  Start-ScheduledTask ×2 → app-verify ALL-false. Then the standing fork:
  F-v2 or the (smaller) closeout.**
- **2026-07-09 (session 14b — restart + invite flow + the 5-user reality):**
  Jordan added tester the first pilot user in the Spotify dashboard (screenshot: "1/5
  added") and stopped the app for the handoff. Agent restarted webapp +
  worker on the hardened code → app-verify ALL-GREEN (heartbeat live,
  public URL serving); task registration still owner's one-liner (classifier
  holds persistence for the owner). Answered the dynamic-allowlist question
  with verified facts: **Spotify's Feb-2026 policy caps dev mode at 5 manual
  adds (no API) and gates extended quota on registered-business + 250K MAU —
  the 5-seat list is permanent**; corrected every stale ~25/extended-quota
  claim across SPEC/APP_SPEC/SELF_HOSTING/chronicle/this file. Shipped the
  landing + error page **invite-request notice** (jordan@vercilloanalytics.com mailto;
  logged-out visitors only; 3 new assertions; verified on the live origin
  AND through the public edge — Cloudflare email-obfuscation wraps the
  address in served HTML by design, browsers decode it). Suite **265 green**
  (commit 3832289's message says 267 — miscount, the log here is the truth).
  **Left off: owner one-liner = register_autostart.ps1. Standing fork
  unchanged: F-v2 or closeout (DKIM/DMARC, GCP zone).**
- **2026-07-09 (session 15 — Opus 4.8; click-to-run controls):** Model
  switched Fable 5 → Opus 4.8 mid-day (clean handoff — tree synced, all work
  committed). Session teardown had killed the webapp + worker (site 502-ing);
  built **double-click start/stop/status** (`*_app.bat` → `scripts/app_control.ps1`,
  commit eeb6328) and used `start` to restore the app (app-verify ALL-GREEN,
  public edge 200). One build snag: PS 5.1 reads BOM-less files as ANSI →
  em-dashes broke the parse; rewrote the .ps1 ASCII-only. SELF_HOSTING §4 now
  documents easy/manual/autostart. **Left off: app UP under the click scripts;
  reboot persistence still optional via register_autostart.ps1. Standing fork
  unchanged.**
- **2026-07-09 (session 16 — Opus 4.8; $0 email + Epic F-v2):** Long
  multi-front session. **① backup-on-`stop_app`** wired (proven live). **②
  Email → $0:** dropped paid Google Workspace for free **Cloudflare Email
  Routing** — `jordan@vercilloanalytics.com` catch-all → jvercillo@live.com;
  MX/SPF/DKIM/DMARC all live (verified via authoritative DNS); invite CTA
  switched to jordan@…; hit + documented the Email-Routing "manual MX delete →
  Disabled → Onboard Domain" gotcha; clarified the domain's 3 free hats (site /
  Microsoft-Entra identity / CF email — `OwaUserHasNoMailboxAndNoLicense…` is
  expected). Forwarding proven end-to-end. Corrected every stale ~25/extended-
  quota claim (Feb-2026 policy = 5 seats, extended quota business-only). **③
  Epic F-v2 (2 of 3 slices):** F-v2a within-track **loudness curve** on the
  song page (951cb5a), F-v2b estimated **time_signature** as a measured
  /explore feature (199f8e3, catalog 13→14) — both promoted cache columns
  (frozen vector/82-col contract untouched), backfilled 117/117 from LOCAL
  MP3s (no re-download). Journals #18 (create_all builds, never ALTERs → forward
  migration) + #19 (backbeat masquerades as 2/4 → narrow the claim). **277 tests
  green, CI green, app deployed via `app_control restart`, all audits green.**
  Memory files written (domain setup, on-demand runtime). **Left off (owner
  PAUSED): remaining = F-v2c instrumentalness (honest source-separation or
  park), owner cost-cleanup (cancel Workspace + GCP zone), A3 Ollama epic.**
- **2026-07-10 (session 19 — roots review + hardening):** Owner asked for a
  plan/build review, security-risk hunt, and agents/skills leverage. Recall
  showed a #22 security review + ingestion-progress feature had landed since
  my context; re-reviewed the new `/status`+poller surface personally (CLEAN),
  confirmed the vision, then **cleared the entire #22 hardening backlog** in 5
  commits (→c31f298): www-allowlist + POST logout + track-id guard; the
  single-instance worker lock (+`--takeover` for managed restarts — journal
  #23); FEATURE_DISTRIBUTION audit checks + population_n stamps; and an
  Explore-agent ops sweep whose verified findings fixed app_control's
  machine-wide process matching, path guard, log rotation, CI permissions,
  and the LAN-exposed preview server. Live proof: spoofed-Host 200, GET-logout
  405, real www→apex 301 via the edge, 2nd-worker refusal, app-verify ALL
  GREEN. 299 tests; CI pending at wrap. **Left off: hardening backlog EMPTY.
  Next build unchanged — ② P popularity-context, or jump to ③ F-v3 structure
  timeline. A3 Ollama queued after the audio work.**
- **2026-07-10 (session 20 — slice ② P, popularity context):** Built in 3
  commits (P.1 capture+docs → P.2 surface → P.3 backfill, →4957f73). The
  journal-#20 correction went live: guardrail un-stripped (with the policy
  note), CLAUDE.md rule 3 + agent-prompt 01 corrected, popularity captured to
  `track_meta` (migration #4) via preserve-if-absent `remember_meta`;
  `/analytics` gained the taste-vs-popularity line (percentile vs corpus at
  n≥20, absolute bands below, silent under 3 values; honest caption) and the
  RAG grounding carries it labelled "Spotify metadata, not acoustic".
  Warehouse safety verified up front (fact build subsets explicit columns —
  D-4 contract untouched). Live backfill valued 119/119 in 3 calls. 304 tests,
  audits clean, deployed (app was owner-stopped on-demand; restart brought it
  up on the new code). **Left off: slice ② DONE — next is ③ F-v3 structure
  timeline (marquee), then ④ Epic G reco explorer (fully unblocked).**
- **2026-07-10 (session 21 — F-v3, the structure timeline):** Built the
  marquee in 3 commits (detection core → persistence+backfill → ribbon,
  →27fd23d). Simplified McFee-Ellis Laplacian segmentation; sections column
  (migration #5); 117/117 backfilled locally; ribbon + honesty caption on the
  song page. The build WAS the validation story (journal #24): synthetic
  fixture caught merge/coverage logic (incl. a count-based sync gate that
  pure tones fooled — coverage gate now), the corpus distribution caught
  fragmentation (25–63 fake sections) and the A|A coalesce artifact, and
  NAMED-song spot-checks caught representation blindness (KoC = one 366s
  section under chroma-only recurrence → chroma+MFCC stack; single-section
  tracks 24→9). 311 tests; deployed; app-verify ALL GREEN. **Left off: F-v3
  DONE — the within-track story is complete (spectrogram + loudness curve +
  fades + bar grid + section ribbon). Next: ④ Epic G recommendation explorer
  (capstone), then ⑤ A3 Ollama, ⑥ polish.**
- **2026-07-10/11 (session 22 — Epic G, the recommendation explorer):** The
  capstone in 2 commits (pure engine → surface, →bcd0fb3). The retired
  /recommendations rebuilt transparently: whitelisted tunables, z-distance
  ranking on the stats mart, visible seed targets, popularity as a
  constraint axis, missing-value exclusion, deterministic ordering. Real-data
  proof incl. the cross-feature consistency check (meter hunt = exactly
  F-v2b's 17 3/4-tracks). Owner asked for live browser validation at the end
  of builds → done for this deploy (landing + auth gates + www redirect
  through the real edge) and saved as a standing practice (memory +
  conventions). 325 tests, all audits green, deployed. **Left off: the
  audio-features roadmap (①–④) is COMPLETE — the app now rebuilds BOTH
  retired Spotify endpoints end-to-end. Next fork: ⑤ A3 Ollama (real $0 LLM
  for /ask+/classify, evals-guarded) or ⑥ polish. Jordan should log in and
  click through /recommend — seed a song and tune.**
- **2026-07-11 (session 23 — A3 Ollama + handoff):** Shipped A3: `/ask`+
  `/classify` answer via local gemma4:12b at $0 (unified provider `_chat`,
  format=json, num_ctx 8192, startup warm-up; deterministic fallback intact).
  The F0 golden evals earned their keep (journal #25): graded gemma4 5→9/15
  (paraphrases not hallucinations) despite a great smoke → owner chose gemma4
  as default with the eval score documented. Then refreshed the handoff
  harness (this file + SESSION_CHRONICLE brought current through A3; lessons
  #20–25). Verified live at handoff: tree clean+pushed, app-verify ALL GREEN
  (118 tracks, public up), warehouse-audit clean, CI green, 330 tests.
  **Left off: roadmap ①–⑤ COMPLETE; only ⑥ polish remains (DMARC tighten,
  loudness on /analytics) or a new direction. NEW SESSION: run `/resume`.**
- **2026-07-11 (session 24 — ⑥ polish: loudness arc on /analytics):** `/resume`
  verified all-green (app-verify 8 flags false, warehouse-audit 0 errors, tree
  clean+synced), then owner picked the loudness-on-/analytics polish item. Built
  "Your typical track's loudness arc" — a corpus roll-up (median within-track
  loudness *shape* + middle-50% IQR band) that surfaces the F-v2 loudness work on
  the aggregate taste page, not just the song deep-dive. One commit (c7ffe95):
  `cache.loudness_curves` bulk getter + pure `average_loudness_arc`/
  `loudness_arc_svg` + wiring + template + `.loud-band` CSS + 3 tests → 333 green.
  **Design surprise (journal #26):** an early test asserted the band brackets the
  central line; it failed on a skewed synthetic case because the IQR brackets the
  MEDIAN, not the mean → switched the central line mean→median (coherent p25/p50/
  p75 summary, also killed a float-ULP edge). Local suite showed 4 RAG-fallback
  failures — the known live-Ollama `.env` artifact (WEBAPP_LLM_MODEL=ollama:… so
  the no-key tests route to the real model); confirmed green the CI way
  (WEBAPP_LLM_MODEL=hosted → 333 pass). Deployed via `app_control restart` (no
  `-ExecutionPolicy Bypass` — CurrentUser is RemoteSigned; the classifier blocks
  the bypass flag); app-verify ALL-GREEN post-deploy, live edge 200/303, arc
  DOM-verified in the Browser pane (screenshot renderer was flaky — used
  read_page). Then, same session, walked the owner through **tightening DMARC to
  `p=quarantine`** in Cloudflare (verified live on both public resolvers) and
  scoped the optional **send-as-the-domain** paths (memory updated). Closed with
  a "ready to share?" discussion: the app is deployed/live but broad *async*
  sharing is gated by (a) on-demand hosting (the whole domain 502s when the
  PC/app is off), (b) the Spotify **5-seat allowlist**, and (c) a thin
  logged-out surface — so it's **demo-ready, not broadcast-ready**. **VISION
  DECISION LOGGED (owner, 2026-07-11): REAL data only — never fabricate synthetic
  rows to demo scale/benchmarks** (SCALING.md decision note + project-memory
  `real-data-only-no-synthetic-benchmarks`; tests keep their synthetic fixtures
  per ground-rule #5 — that's code-correctness, not product data). **Spark/scale
  is PARKED** — the P7 parity proof + SCALING.md already bank scale-readiness;
  revisit only with materially more real data or a need to speed up extraction.
  **Left off: ⑥ polish effectively COMPLETE; scale parked; recommended next build
  = the SHARE-READINESS pass (always-up front door so the link is never dead +
  a README/case-study that tells the engineering story), pending owner go — the
  first sub-choice there is 24/7 vs on-demand hosting. NEW SESSION: run
  `/resume`.**
- **2026-07-11 (session 25 — Vision C design session, Fable 5):** Owner brought
  a 12-idea list ("filter for all songs so anyone gets value without the pilot",
  playlists, MPD, talk-to-your-songs, ingestion UX, UI cut-offs, case study,
  public GitHub) → audited + organized into Epics H–L, four forks decided by
  owner (D-18 public corpus / D-19 MPD parked w/ 4 saved dbt+Recce references /
  D-20 filter-repo scrub / sequence H→L-lite→I→K→L-flip), spec written to
  VISION_SPECS §Vision C. Flagged en route: #9 progress UX partially EXISTS
  (/status + poller, enrich not rebuild); MPD = the legitimate real-data Spark
  un-park trigger; llm_knowledge_base can't go public (D-21); acquisition
  answer = harden yt-dlp matching, never switch to 30s previews (D-22).
  **Left off: spec + roadmap COMMITTED; nothing built yet. Next: build Epic H
  slice H0 (guest rendering core). NEW SESSION: run `/resume`.** Session close:
  **PILOT TRIAL T0 SET (owner ask): starts NOW — first window weekend of
  2026-07-11/12, before Epic H** (2/5 seats filled: the first pilot user 07-09, the second pilot user 07-10).
  Full per-tester runbook in VISION_SPECS §"Pilot trial — T0": start_app →
  invite ("~1–1.5 h, durable queue, come back anytime") → stagger testers →
  post-drain `train_clusters.py` (map dots need a retrain; analytics is
  instant via online assignment) → stop_app (auto-backup). Tester confusions
  feed H4/H6. **Epic M SPECCED (owner ask, 2026-07-11): auto tester lifecycle —
  detect new songs + ETA (mostly EXISTS via /status), auto-retrain on
  batch-drain (extend the ONE worker's post-drain hook, not new workers), email
  tester when done.** Decisions D-23 (email = Brevo relay + DKIM; DEPENDS on the
  send-as setup since DMARC=quarantine), D-24 (`user-read-email` scope →
  re-consent + opt-in checkbox + notifications table), D-25 (one worker + hooks,
  failure-safe). Slices M1 copy (trivial) / M2 auto-retrain (between trials) /
  M3 email subsystem (needs outbound-email groundwork). **→ Epic M PARKED by
  owner same-day (2026-07-11): revisit ONLY with materially more users + a paid
  email/Exchange account — the 5-seat Spotify cap blocks user growth, so the
  manual runbook covers ≤5 testers; D-23's email dependency is recorded for
  when it un-parks.** **For the LIVE trial: manual runbook only — do NOT
  hot-patch a running drain.**
  **✅ TRIAL RESULT — the first pilot user's run COMPLETED CLEAN (2026-07-11):** queue
  drained to 0 (42 done, **0 failed**), cache **118→159** (+41 of her real
  tracks, every one with a spectrogram); marts auto-rebuilt to 159 via the
  worker post-drain hook; `train_clusters.py` retrained songs (k=2, silhouette
  **0.115→0.146** — more real data, cleaner structure) + artists (64, k=2); app
  + warehouse audits ALL-GREEN. First real external user ingested end-to-end —
  the pilot flow is proven on a stranger's library, not just the owner's. Seat 2
  (the second pilot user) not yet run. **✅ VISION D SPECCED post-pilot (owner's 16-item list):
  most already covered (H/I/K/L); NEW = Epic N (explainability: σ/stats
  explainer + 12-archetype taxonomy), Epic O (dedup-as-flag + yt-dlp match
  hardening), Bug B1 (recommend-seed refresh). MPD+Spark UN-PARKED METADATA-ONLY
  (D-26 affirms D-19 / D-27 Spark for 66M-row metadata not the download path /
  D-28 dedup = flag not a 2nd ID / D-29 interleave). App STOPPED + cache backed
  up (159 tracks) at session close. Left off: Vision D Phase 1 is the next build
  (start with B1 or the quick UI wins); NEW SESSION: run `/resume`.**
