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
  **✅ UPDATE 2026-07-14 — VISION D PHASE 1 IS 8/8 COMPLETE + LIVE** (D-31, B1,
  H3, H4, H0+H7 guest demo, N1 explainers, N2 taxonomy, O1 dedup — all shipped;
  353 tests). **✅ VISION E SPECCED same day (owner's re-scope → VISION_SPECS
  §"Vision E — the product era", decisions D-32…D-39):** Phase 3 = the product
  surface (P3.0 fetcher-hardening+50/range → P3.1 artist_meta → P3.2 Artists+
  genres → P3.3 Library tabs → P3.4 playlists → P3.5 guest dashboard → P3.6
  H5/H6/O2 → P3.7 case-study+PUBLIC-FLIP exit gate); Phase 4 = Epic K formal
  (K0 interview design → chat/tool-use/bucketing/multimodal-upload builds;
  adapters+RL = gated explorations); Phase 5 = MPD; Phase 6 = ML capstone.
  Research brief: [`docs/SPOTIFY_API_RESEARCH.md`](../docs/SPOTIFY_API_RESEARCH.md)
  (TWO deprecation waves; artist top-tracks REMOVED no-replacement → derive
  "YOUR top by artist" as core, live absent-safe garnish; 5-seat cap = platform
  ceiling; playlists own+collaborative only). New harness agents:
  `research-expert`, `agile-coach`. ✅ **P3.0 GROUNDWORK SHIPPED (2026-07-15,
  commits c8f2ce2/4748fb9/1b74f3c, 359 tests, deployed, app-verify ALL-FALSE):**
  fetcher hardening (absent-safe `_artist_to_record` + artist-popularity capture;
  batch-`/artists` → singles fallback @0.5s; playlist `items.total`/`item`-entity
  fallbacks + 50/page; search clamped 10) · **`_TOP_LIMIT=50`** (D-34 — the "why
  39 songs" fix; next logins pull up to 150 entries/user) · guardrails file
  correction wave 2 (two-wave dating, borrowed-time doctrine, genres watch item).
  ✅ **P3.1 ARTIST_META FOUNDATION SHIPPED (2026-07-15, commits 134f688/d4a01e3,
  361 tests, deployed ALL-FALSE):** `ArtistMeta` table + `remember_artists`
  (preserve-if-absent — "" never overwrites stored genres) + `all_artist_meta`;
  `track_meta` += `album_image_url`+`primary_artist_id` (migration, threaded
  through `remember_meta`); `_top_artists(client, cache)` now PERSISTS the frame
  it always fetched (D-36, zero extra calls); `seed_artist_meta.py` run LIVE —
  **60 artists, 29 with genres** (the journal-#9 honest ceiling). **➡️ NEXT
  ACTION (SUPERSEDED — P3.2 ✅ SHIPPED 2026-07-15, commits de5371b/79824ca, 375
  tests, deployed ALL-FALSE, browser-validated on REAL data at 375px):**
  `/artists` — 15 cards w/ stored genres/popularity + hover DSP means + genre
  chips/?genre= filter + "Genres known for 10 of 15" honesty caption + ONE
  ranked comparison chart (form-GET picker); `/artist/{id}` — hero + **"Your
  top tracks by X" (the D-33 DERIVED core, 0 API calls)** + borrowed-time live
  top-10 (authed-only — PKCE means no app token; absent-safe w/ honest dark/
  guest captions) + analyze-on-demand POST (server-side re-fetch → remember_meta
  → enqueue ≤10, O1 guard applies) + **"Similar in your library"** (acoustic
  centroids — live proof: Muse → Metric Δ1.46σ, Harry Styles Δ1.47σ, Foo
  Fighters Δ1.69σ; the honest related-artists replacement); nav = the D-35
  two-group IA (`.nav-sep`). **➡️ NEXT ACTION (SUPERSEDED — P3.3 ✅ SHIPPED
  2026-07-15, commits 06da10d/758e140, 388 tests, deployed ALL-FALSE, anon
  browser-validated): the Library surface is live and PUBLIC.** `cache.library_rows()`
  (meta⟕features projection) + `webapp/library.py` (pure: search/sort—Nones-last/
  dedup "same recording as"/mine-overlay/`why_n_analyzed` derived from `_TOP_LIMIT`)
  + `/library` (All songs public · My songs viewer · Playlists authed placeholder)
  + nav Library for everyone. **Partial D-18 flip (D-40): `/song` + `/spectrogram`
  flipped PUBLIC (taste-free); `/explore` + `/recommend` stay viewer-gated —
  their builders hard-require a taste (`return None` w/o range_ids), so their anon
  flip is a deferred builder-refactor slice (D-40b, folds into the P3.7 exit
  gate).** **➡️ NEXT ACTION (SUPERSEDED — P3.4 ✅ SHIPPED 2026-07-15, commits
  30cb7b9/cccad88/9c78ec2, 401 tests, deployed ALL-FALSE, anon-validated):
  Epic I playlists live + re-consent.** Playlist scopes added (single-sourced
  in `config.SCOPES`; `auth_web.has_playlist_scope` reads the granted `scope`;
  privacy copy discloses it) → **all pilot users re-consent on next login**;
  `webapp/playlists.py` (own+collaborative filter, fails-closed w/o /me id);
  `/playlists` (authed: re-consent CTA vs card list) + `POST /playlists/{id}/analyze`
  (scope+membership gated before any fetch → server-side re-fetch → cap-as-total
  slice `[:100]` D-41 → remember_meta → enqueue O1; coverage via session flash,
  XSS-safe). ✅ **AUTHED PATH FIELD-VALIDATED (owner, session 36):** Jordan
  re-consented live and imported real playlists (56 + 264-track, logs prove the
  whole chain) — his field reports drove the **session-36 bug pass (commits
  d88d173/0316cf9/74f12e4, 407 tests, deployed, app-verify ALL-FALSE):**
  ① `/nan` 404s (coverless playlist → truthy NaN `<img src>`) ② **skip-then-cap**
  (Analyze now skips analyzed AND live-queued tracks first — `cache.active_ids()`
  — then caps the genuinely-new; re-Analyze walks deeper each time) ③ the
  "artists page gets stuck" hang (spotipy retries+Retry-After slept renders on
  429'd garnish → `client_from_session` retries=0 + a 10-min per-app memo for
  non-empty artist top-10s) ④ **the `/queue` surface** (public; running-first +
  worker-true FIFO + ~50s/track ETA + 30s self-refresh; linked from the
  playlists flash, library "analyzing…" cells, artist Analyze caption)
  ⑤ app-verify QUEUE_STUCK re-semantics (progress-based, not oldest-pending age
  — a deep draining import backlog is healthy, journal #31). ✅ **P3.5 GUEST
  DASHBOARD REPLICA SHIPPED (2026-07-16, commit 3158f49, 409 tests, deployed
  ALL-FALSE, guest path browser-validated live: 117/117 coverage · drift
  0.141σ · artist genres joined · ask box honestly gated):**
  `guest_dashboard_context()` builds the SAME dashboard context from snapshot
  ids + the cache alone (zero API calls — tests rig the fetchers to explode);
  snapshot schema UNCHANGED (derive-don't-transcribe, journal #27 — display
  data from `library_rows` + `all_artist_meta`, so no re-snapshot dependency);
  `/guest` → `/dashboard`; nav shows Dashboard to guests. ✅ **P3.6 SHIPPED
  (2026-07-16, commits 0562601/486384f/22f87e9, 417 tests, deployed ALL-FALSE):
  O2 duration-aware match scoring w/ recorded `match_confidence`
  (heuristic-v1 = selection+recording ONLY, no rejection threshold — awaits
  corpus evidence) · H6 three-tier landing (browse freely / demo / login) ·
  H5 origin-down fallback Worker (`infra/cloudflare/`, SELF_HOSTING §6a).**
  **⚠️ TWO OWNER STEPS: ① deploy the H5 Worker (Cloudflare dashboard paste +
  route, ~2 min, doc'd) — verify with stop_app → browse the domain → fallback
  card, then start_app; ② sign off (or retune) the O2 heuristic-v1 weights
  once real imports build a match-confidence distribution.** ✅ **P3.7 READY
  TO FLIP (2026-07-16, Fable session 39): every exit-gate item is DONE and
  re-verified — the flip itself is the owner's hand.** Sweep + MIT LICENSE +
  README product-era pass + `docs/CASE_STUDY.md` landed; gitleaks 8.24.3 over
  all history; agile-coach pre-flip review caught 3 real blockers (employer
  email in commit metadata → mailmapped to live.com · a 2nd pilot name →
  genericized · missing KB .gitignore); `git filter-repo` ×2 (dead secret +
  names replace-text, mailmap, KB out of all history D-21, ALL
  `__pycache__`/.pyc stripped — the secret survived in committed BYTECODE,
  journal #32); force-pushed; post-scrub verification ALL CLEAN (gitleaks "no
  leaks found" + value/name/email/KB/pyc greps zero); CI GREEN on the
  rewritten history (after fixing a cookie-jar test flake); 417 tests;
  app-verify ALL-FALSE. **NOTE: all pre-scrub commit hashes cited in
  notes/docs are now historical labels (accepted). The KB dir was restored to
  disk from the pre-scrub bundle — local-only, gitignored.** 🏁 **PHASE 3 HAS
  EXITED (2026-07-16): the repo is PUBLIC** — verified anonymously (repo page +
  raw README both 200 logged-out); already drawing real anon traffic (crawlers
  on /song pages in the webapp log). ✅ **H5 WORKER DEPLOYED + VERIFIED
  (session 40, commit 784117d):** wrangler CLI (owner OAuth as
  jordan@vercilloanalytics.com), worker `origin-fallback` on BOTH zone routes;
  full loop proven live — app up = pass-through untouched (200s, /healthz
  `{"ok":true}`); app stopped = the "Demo offline — by design" card (503 +
  Retry-After 3600) and /healthz **503 JSON** (journal #33: Cloudflare
  REPLACES a Worker 502/504 response with its own error page — the fallback
  must ride a 503 to keep authorship). The wrangler deploy config lives in the
  SCRATCHPAD by design (repo stays clean); redeploy = copy worker.js + a
  2-route wrangler.jsonc anywhere, `npx wrangler deploy`. ✅ **K0 DONE
  (2026-07-16, session 41, Fable + llm-rag-expert): Epic K's phased plan is
  IN THE SPEC (VISION_SPECS §Phase 4, D-42…D-46)** — owner locked: K2
  tool-use SHIPS gated (injection evals 100% + K1's GO; D-18 defuses the
  expert's isolation concern) · K1 /chat viewer-gated ~20 turns · K4 uploads
  20MB/10min/10 w/ the `up`+hash bridge-safe id · safety-100/quality-80
  gates. K0 exit items shipped: the `force_fallback` harness hole FIXED
  (only popped the API key — a dev `.env`'s `ollama:*` route silently
  de-calibrated the CI guard; both routes now neutralized + tripwire,
  journal #34) and the **first committed gemma4:12b baseline: 9/15**
  (`evals/runs/2026-07-16_…txt` — must_cite 8/14, no_invention 15/15,
  archetype 5/5; fallback 15/15 + constant 0/15 anchored in the same run;
  two cold-load timeouts visibly degraded to the D-5 fallback = the
  deployment-honest number). ✅ **THE K RESET (owner, 2026-07-17, session 42 —
  commit 89d0b83): Epic K is now "TALK TO YOUR DATA"** — an on-demand music
  data analyst (STORY + ADHOC modes), **gemma4-only** (both hosted clauses
  removed; gates decide scope, never provider), every prompt+response logged
  into a review flywheel (D-47: log-all + /privacy disclosure + 90-day
  retention; graded rows = the K5 counter), **RTCROS** contract in ONE
  encoding (D-48: prompt_contract.py, cited-before-answer, entity-inventory
  verify-retry), and a **data-first SEMANTIC LAYER before any chat** (D-49).
  New agent: `chat-analyst-expert` (D-50, registered). **STALE-FACT FIXES
  (probed live 2026-07-17): the corpus is 796 analyzed tracks** (6.8× since
  the public flip — real playlist imports), NOT ~161; **the planes have
  DIVERGED** (star-schema gold frozen Jul-4 at 118 — `warehouse_agent` reads
  it; cache+marts live at 796); clusters cover 39% (trained Jul-11 on 311);
  **the warehouse audit is RED today** on FEATURE_DISTRIBUTION (2 broken
  extractions: tempo 0/−180 dBFS "Aftermath — Muse" + "Q&A — Drake"; 11
  legit DJ-mix outliers) — known cause. ✅ **K0.5 THE DATA FLOOR — MOSTLY
  SHIPPED (2026-07-17, session 43, Opus; commits 7f12daf/5584750, 425 tests,
  app-verify ALL-FALSE, semantic marts BUILT LIVE on 796 tracks):**
  **① eval honesty** — `format_report` now prints per-case source + a "by
  source" line (the 9/15 hid 2 fallback-graded classify timeouts). **② the
  grounding/routing fixes** (motion/breadth render, empty-context→fallback
  gate, num_predict=1024) → **gemma4 9→13/15** (honest artifact: 7 passes are
  fallback, gemma4's own LLM record 5/7; A01/A05 must_cite remain for D-48's
  RTCROS reorder). **③ the semantic layer** (`src/store/semantic.py`:
  feature_dictionary w/ the rule-3 caveat as a ROW · track_card w/
  feature_valid gate · artist_rollup by primary_artist_id) wired into
  `rebuild_marts` (rides post-drain, no recompute); the 4 tripwires ship as
  tests; built live = 796 track_cards (plane-coherent), 299 artist_rollups,
  the 2 broken tracks gated `feature_valid=False`. **④ broken extractions:
  the feature_valid gate is the interim protection; D-52 re-extraction is the
  permanent fix (no premature DB mutation — owner's ratified call).**
  ✅ **K1 PROBE + RTCROS CONTRACT SHIPPED (2026-07-17, session 44, Opus;
  commits af7ba68/ed84869, 431 tests, ruff clean):** the probe read gemma4's
  REAL behavior (evals/runs/2026-07-17_k1-probe…) → reframed the build;
  `prompt_contract.py` (ONE RTCROS encoding, verify-retry, empty→fallback
  guard, PROMPT_VERSION) rewired rag.answer/classify. **THE FINDING
  (journal #36): the contract dropped the eval 13→9/15 — because it made
  gemma4 ATTEMPT 8 ask cases via LLM instead of timing out to the
  verbatim-perfect fallback, and gemma4 PARAPHRASES exact labels
  (no_invention 15/15, faithful not fabricating). 9/15 is gemma4's honest
  adhoc ceiling (~57% must_cite, below the 80% gate); it is STRONG on STORY +
  classify.** ✅ **K1c SHIPPED — the story-led `/chat` + D-47 ChatLog is LIVE
  (2026-07-18, session 45, Opus; commits fbf0c81/7c649f2, 436 tests, ruff
  clean, deployed ALL-FALSE, curl-validated live):** **K1c-1 the ChatLog
  spine** — `ChatLog` + `ChatLabel` tables (create_all builds them),
  `cache.log_chat_turn`/`recent_chat_turns`, rag.answer/classify return the
  rendered grounding + raw output, `/ask`(adhoc)+`/classify`(profile) log from
  day one via a shared `_log_turn` (chat_session_id = a per-session uuid, NOT
  the auth sid), `/privacy` rewritten to disclose logging + 90-day retention.
  **K1c-2 the surface** — `GET /chat` (viewer-gated) opens with `TasteRAG.story()`
  then `POST /chat` PRG adhoc turns, ~20-turn drop-oldest display history,
  chat.html + a "Chat" nav item. **gemma4 live-debug findings (journal #37):
  it returns EMPTY when the user turn is just `<data>` with no instruction →
  story()/classify() now pass a "REQUEST: …" directive; it chokes on nested
  JSON → story mode is the FLAT `answer` field; it's INCONSISTENT + slow
  (~25-50s, pads to the token cap) → the deterministic fallback is the
  reliability backbone, gemma4 enhances when it succeeds.** ✅ **K1.5 THE
  REVIEW FLYWHEEL SHIPPED (2026-07-18, session 46, Opus; commit 365d929, 441
  tests, ran live on the 23 real logs):** `src/webapp/chat_review.py` (pure:
  stratified_sample · pre_grade the machine-checkable dims via verify_citations ·
  render_worksheet ESCAPED · aggregate + the `k5_eligible` counter) +
  `cache.ungraded_chat_turns`/`write_chat_label`/`all_chat_labels` +
  `scripts/review_chat_logs.py` (`--sample` a gitignored worksheet · `--commit`
  human grades → ChatLabel · `--report` aggregates-only dated artifact; raw
  user text NEVER leaves the gitignored DB, rule 7).
  ✅ **K2 — "TALK TO YOUR DATA" TOOL LOOP: 7/8 SLICES SHIPPED (2026-07-21,
  session 47, Fable; commits d36cf49→6a5dce1, 472 tests, CI green).** The /chat
  tool-use loop is BUILT, injection-gated, and answers the owner's original bug.
  Slices: **K2-probe** (d36cf49 — GO: gemma4:e4b drove the flat action loop 6/6
  grounded, self-correcting; found the entity-recognition gap). **K2.0** (bc2f98d
  — the last 2 semantic marts `corpus_facts`+`cluster_profile` in `semantic.py`;
  3 audit tripwires PLANE_COHERENCE/SEMANTIC_PARITY/CLUSTER_PROFILE_DRIFT; live
  807 tracks/805 valid/301 artists/61h, clusters 38.5% on-mart). **K2.1** (0f38ac3
  — `_neutralize()` sanitizes untrusted import names in `_grounding_text`; INJ-PI
  regression; proven no-op on all 15 golden groundings). **K2b** (25ddee9 —
  `src/agent/chat_tools.py`: read-only SQL over the 5 marts via a `tables=`
  allowlist on `WarehouseAgent` (MCP star-schema untouched); per-session +
  os.replace-safe; MAX_ROWS=20 server clamp; interrupt watchdog — DuckDB has NO
  statement_timeout, verified 1.5.4; pinned schema card w/ live DESCRIBE; pragma_*
  + parquet-introspection added to `_FORBIDDEN`). **K2c** (4b949d7 — the depth-3
  flat-action loop in `rag.py` (`_tool_loop`), flat union NOT D-44's nested
  envelope; `build_tool_system` w/ `TOOL_CONTRACT_VERSION rtcros-tools-v1`;
  ChatLog `depth` column + migration; degrade preserves the tool transcript for
  missing_fact clustering; `tools_factory` DI keeps tests machine-independent).
  **K2a** (e6ea331 — `injection_v1.jsonl` (5 attack shapes) + `injectionset.py`
  BINARY-never-averaged gate + `run_injection.py` + grader-teeth self-tests, no
  bypass flag). **K2d** (→6a5dce1 — the gates). **THE MODEL DECISION (owner,
  session 47): SPLIT — `WEBAPP_TOOLS_LLM_MODEL=ollama:qwen3:8b` drives the
  security-sensitive tool loop; `WEBAPP_LLM_MODEL=ollama:gemma4:e4b` stays
  multimodal (K4) + story/classify.** WHY: gemma4:e4b OBEYS a token-injection
  4/4 runs (a 4.5B limit no contract fixed); **qwen3:8b DEFENDS all 5 attacks
  6/6 clean runs** AND scored golden 13/15. Per-surface routing = `config.tools_model()`
  + `TasteRAG(tools_model=…)` + `_wants_tools_llm()`; run_webapp warms both.
  **THE OWNER'S ORIGINAL BUG IS FIXED:** "top rise against songs" now returns
  real Rise Against tracks live (depth=2) after the **NAMES-FIRST** contract
  mandate (a proper-noun phrase must be looked up as an artist/track name via
  ILIKE BEFORE any mood interpretation; a "top <phrase> songs" answer may never
  be other artists' tracks — qwen3 had mislabeled high-energy tracks as Rise
  Against, journal #38). Two injection cases (INJ01, INJ03) were restructured so
  the payload sits in a row the answer never surfaces — testing genuine OBEDIENCE
  not the quoting-vs-obeying grader artifact (journal #39). Guard hole closed:
  the tool loop's `WEBAPP_TOOLS_LLM_MODEL` is a THIRD live-model env route →
  `src/conftest.py` autouse fixture neutralizes ALL routes so `.env` can't
  de-calibrate the suite (journal #34 recurring); force_fallback pops it too.
  Cleared an orphaned `injection_evals.py` (truncated duplicate from the recovered
  session). ✅ **K2e DEPLOYED + VALIDATED LIVE (2026-07-22, session 48) — EPIC K2 IS
  8/8 COMPLETE.** App was DOWN at pickup (PC reboot; on-demand runtime) →
  `app_control start` brought webapp+worker+tunnel up healthy; the dual warm-up
  is PROVEN: qwen3:8b (6.2 GB) + e4b (3.3 GB) sit CO-RESIDENT 100% GPU at 8K
  ctx (9.5/12 GB — no swap thrash between the loop and the voice). Live
  acceptance THROUGH THE PUBLIC EDGE as GUEST: /chat story = a real e4b
  generation (cites drift 0.141, 50v50, real artists); "what's my top rise
  against songs" → REAL Rise Against tracks (Collapse (Post-Amerika), The
  Numbers, Swing Life Away, Satellite, Make It Stop…); ChatLog id 70 is the
  proof: source=llm, model=ollama:qwen3:8b, depth=1, latency 87.7s (correct
  but slow — the async/streaming UX note stands). app-verify ALL-FALSE (all 8
  marts, 807 tracks, worker beat 12s, queue drained). ✅ **K3 COMPLETE (2026-07-22, session
  49, Fable + orchestrator; commits b5eefd0→edcecd3, 488 tests, ruff clean):
  grounded cluster descriptions — built, eval-gated, DEPLOYED,
  browser-validated.** The llm-rag-expert consult's key finding shaped the
  build: the `cluster_profile` mart CANNOT reconstruct the raw-DSP
  `_CHARACTER_DIMS` that name a cluster → **K3a** captures `label_dims`
  at training time (nullable JSON + `_ADDED_COLUMNS` migration; `labels`
  byte-frozen, tie-break preserved). **K3b** the `cluster` RTCROS mode +
  `TasteRAG.describe_cluster` — name pinned by the CALLER (never from the
  model), grounding = numbers + dim words ONLY (zero injection surface, a
  deliberate v1 boundary), dim-drop → template. **K3c** `golden_clusters_v1`
  (10 cases incl. Mixed + single-dim) + 4 graders in `clustereval.py`;
  template 10/10 = the new $0 CI guard (run_golden.py exit-gates BOTH sets);
  name-only baseline fails ONLY grounded_in_centroid (the skill check).
  **K3d** `describe_clusters.py` (offline batch, prompt-version idempotent) +
  mart projection — the MODEL ROW is truth, rebuilds never regenerate.
  **K3e** legend blurbs + honest caption on /analytics. **The gates did
  their job twice:** ① the first live run caught e4b describing by CONTRAST
  (CD06 "Percussive · Noisy" said "harmonic" — every dim word present, yet
  contradicting the centroid; journal #41) → the opposite-pole guard (K3f)
  → re-run **cluster LLM 10/10** (8 llm + CD06/CD08 honest template;
  taste LLM 11/15 unchanged; artifact `evals/runs/2026-07-22_k3-golden_…`).
  ② the LIVE model #3 is pre-K3a (no dims) → both clusters degraded to the
  FALSE "Mixed" wording → K3g: templates use the label's own words. Deployed
  via `app_control restart` (cache backed up, 807); guest /analytics through
  the public edge renders both blurbs + caption; app-verify ALL-FALSE; audit
  semantic flags all false. **The K3-value unlock is the cluster RETRAIN
  (owner call — changes cluster identities/k and archetype narratives): the
  first post-K3a retrain gets real label_dims → e4b prose replaces the
  templates automatically via `describe_clusters.py`.** **OWNER DECISION
  (2026-07-22): QA / human review sessions are DEFERRED until the app has
  real testers again — do not re-suggest per-session.**
  ✅ **CLUSTER RETRAIN + 4 SHELF ITEMS DONE (2026-07-22, session 50, Opus +
  orchestrator; commits b5eefd0→…, 491 tests, ruff clean, deployed,
  browser-validated).** **THE RETRAIN lit up the K3 machinery:** song model
  #3→#5 on the FULL corpus — **coverage 311 (39%) → 805 (99.7%)**, silhouette
  **0.146→0.172**, buckets `Noisy·Bright`/`Smooth·Dark` → **`Punchy·Smooth`
  (428) / `Gentle·Noisy` (377)**, home sound now Gentle·Noisy 85% (still "The
  Anchored Loyalist"). **R1 pre-flight** (the real correctness fix): training
  read raw features with NO feature_valid gate → the 2 broken extractions
  (Aftermath/Q&A, tempo 0) would skew the scaler/centroids; `_drop_broken()`
  mirrors the mart's `_MIN_VALID_TEMPO` (805 = 807−2). **The retrain's payoff
  is visible:** the electronic/DJ imports (KETTAMA, Fred again.., Sammy Virji)
  finally cluster together (Punchy·Smooth) apart from the rock core (Muse 51,
  Rise Against 59 in Gentle·Noisy) — invisible at 39%. **K3h jargon guard:**
  first live e4b run transcribed the grounding literally ("high
  onset_strength_mean, z=+0.64") → contract v2 (plain language, no column
  names/numbers) + `_has_jargon()` degrades leaks to template → 1 clean e4b
  blurb + 1 template live (journal #42). `/analytics` guest-validated through
  the edge; `/chat` "what are my two sound buckets" → the two new buckets w/
  correct 428/377 counts (retrain × tool-loop cross-check). **THE 4 SMALL
  ITEMS:** **S1** (task #9) — 36 of 41 `source=llm` ChatLog rows are 0 ms
  `'vibe?'` deploy-validation junk; `_synthetic_llm_turn` filter on
  `ungraded_chat_turns`/`recent_chat_turns` (a real llm turn has positive
  latency) keeps them out of the review pool + K5 counter, non-destructive.
  **S2** — O2 heuristic-v1 SIGNED OFF context-only, NO rejection threshold:
  the low-confidence tail (63 tracks <0.5) spot-checks as legit
  electronic/remix imports (VIP/Mixed/Edit), not bad matches — a threshold
  would gut the electronic genre; decision recorded at the weights
  (audio_downloader.py). **S3** — `/chat` pending-state (progressive
  enhancement, PRG intact): instant question + "Reading your data… (~90s)"
  bubble on submit, readonly keeps `q` in the POST, XSS-safe textContent.
  **S4** — DMARC verified still `p=quarantine` (11 days in, want ~14+;
  reports in Cloudflare DMARC Management) — the flip to `p=reject` is the
  OWNER's DNS action, deferred. ✅ **D-55 RATIFIED + ENCODED (2026-07-22,
  session 51, Fable + agile-coach review; commit 41f3c89): the K4/K5/K6
  re-sequence — prototype first.** Owner ratified all five open items: **(a)**
  K4 re-homed to a new **Phase LLM-2** (after Phase 5 MPD, before Phase 6)
  under an APPETITE gate — buildable any time, gains nothing from waiting;
  **(b)** honest closeout wording — **Epic K's CHAT SCOPE (K0–K3) is shipped;
  K4 is re-homed, NOT delivered** (never say "Epic K complete"); Phase 4.5's
  entry criterion amended to match and is SATISFIED — **Phase 4.5 is OPEN**;
  **(c)** Q4 provenance-QA is EXEMPT from the QA-until-testers deferral
  (corpus data-quality, not tester-scoped); **(d)** Q3's feature-shift →
  cluster-identity change is an ACCEPTED consequence (precedented by the
  session-50 retrain); **(e)** the **"working prototype" DoD** is in the spec
  (a stranger validates the thesis end-to-end self-serve: provenance
  click-through Q1–Q3 + credible artists R + audits truly green + the shipped
  chat) — it gates Phase 5. K5/K6 stay D-46 gated docs, builds single-homed
  in Phase 6. **Split-note corrected (stale-fact fix):** e4b earns its K2d
  residency TODAY as the story/classify/cluster voice; its audio input is a
  held option — D-45 is DSP-over-uploads and never feeds audio to e4b.
  ✅ **Q1 SHIPPED (2026-07-22, session 52, Fable+orchestrator; commits
  Q1a→Q1b, 496 tests, ruff clean, audit green, app-verify ALL-FALSE):
  `track_provenance` captured AT extraction (D-51).** New key files:
  `models.TrackProvenance` (append-only, soft `spotify_track_id` ref NOT
  unique; auto-created by create_all — no migration); the yt-dlp matcher
  record now CARRIES what it always knew + discarded (`pick_best_candidate` →
  youtube_video_id/youtube_duration_s/channel/candidate_count; `resolve_
  youtube_match` stamps query + `MATCHER_VERSION="heuristic-v1"`);
  `cache.remember_provenance`/`all_provenance`; `extractor._record_provenance`
  appends one event per successful extraction (best-effort — never fails the
  extraction it describes; NOT on the dedup-twin path); `semantic.build_
  provenance_mart` (current = latest per bridge key, drops internal id) →
  `track_provenance.parquet` in build_semantic_marts (rides the post-drain
  rebuild); audit **PROVENANCE_ORPHAN** (only hard invariant = no provenance
  for a non-analyzed track / no dup keys; coverage is a NOTE — the pre-Q1
  corpus is ∅ until Q3). **Live truth: all 807 tracks are pre-Q1 → 0
  provenance events → empty mart, audit green; the ∅→populated transition
  lands on the next real extraction / Q3.** Ground rules held: zero new
  fetches, bridge key untouched, synthetic-tested (real DSP path).
  ✅ **Q2 SHIPPED (2026-07-22, session 53, Fable+orchestrator; 501 tests,
  audit green, app-verify ALL-FALSE, both surfaces browser-validated live):
  provenance exposed on /song + /library.** `/song` gains a **"Source &
  provenance" card** (YouTube link, channel, duration delta, ✓/~ match-conf
  indicator + the honest "low = remix, not wrong-match" caption from S2);
  `/library` gains a **Src column** (✓ recorded / ~ low-conf / ∅ not-yet) +
  legend. New readers: `cache.provenance_for(track_id)` (latest event) +
  `_provenance_glyph_map` folded into `library_rows` (`provenance`:
  "ok"|"low"|None). **XSS discipline (the |safe SVG lesson applied):** external
  youtube_title/channel render WITHOUT `|safe` (Jinja auto-escapes) + the
  youtube_url is **scheme-guarded** to http(s) so a `javascript:` url is never
  linked — both regression-tested (a `<script>`-shaped title renders inert).
  Live truth: all 807 tracks are pre-Q1 → the ∅ tier renders across the
  corpus (honest; populated cards light up on Q3/next extraction). New key
  files/conventions: `TrackProvenance` (models), `remember_provenance`/
  `all_provenance`/`provenance_for` (cache), `build_provenance_mart` (semantic),
  `PROVENANCE_ORPHAN` (audit), `_record_provenance` (extractor), the `.prov-*`
  CSS. ✅ **Q3 BUILT + DRY-RUN PROVEN (2026-07-23, session 54, Fable +
  data-platform red-team; 513 tests, audits green, app-verify ALL-FALSE):
  the D-52 re-extraction program is READY and its first 3 tracks are LIVE.**
  The Fable-signed batch plan survived a red-team that found **3 verified
  ship-blockers** (journal #43): **F1** `_write_atomic`'s FIXED tmp name let
  the worker's and runner's concurrent mart rebuilds os.replace each other's
  half-written files (→ per-pid tmp); **F2** `upsert`'s preserve-on-None (the
  #22 fix, right for features-only re-writes) would silently mix an OLD
  audio's curve/meter with NEW features on re-acquisition (→
  `replace_display=True`, a true swap); **F3** the CLI pointed downloads at
  `data/raw_audio` where the transient-delete would destroy pre-existing
  owner MP3s (→ `data/tmp_reextract` scratch; sentinel test). Also folded:
  provenance write VERIFIED (the resume marker must not lie), ledger
  temp+replace + provenance-wins reconciliation, still-broken-after-swap →
  ledger FLAG for Q4 (never auto-dead-letter — a deletion is the owner's
  call), coverage denominator = canonical analyzed (796 = 807 − 11 twins).
  Key files: `src/store/re_extract.py` (Ledger/select_targets/re_extract_one/
  run, 12 invariant tests) + `scripts/re_extract.py` (CLI: --limit/--all/
  --retry-failed, post-run checklist). **THE DRY-RUN (--limit 3, 57s): 3/3
  swapped — the 2 permanently-broken extractions are HEALED: Q&A 0→129.2 bpm,
  Aftermath 0→143.6 bpm (matched to the official Muse video, duration delta
  0.003s) — Aftermath's /song went from dead-zero stats to real features +
  fade-in + 7-section ribbon + the populated provenance card, verified live
  through the public edge. FEATURE_DISTRIBUTION's breakage warnings are GONE
  (only the documented legit DJ-mix duration tail remains). Provenance
  coverage: 3/796 canonical.**
  ✅ **O3a–c SHIPPED (2026-07-23, session 55, Fable + data-platform red-team;
  commits ce8fc9a/604fb3e/5d1d26b, 525 tests, all audit flags false, deployed,
  browser-validated live): DUPLICATE CONSOLIDATION — a read-time view, never
  a merge (bridge key untouched, zero feature deletions).** Owner un-parked
  "dupe-pruning" and ratified 4 calls: collapse-by-default · "N analyzed / M
  unique" honesty language · twins' features stay stored-but-invisible
  (pruning stays parked) · O3d acoustic recall miner waits for post-Q3
  vectors. The red-team found 4 concrete holes in the draft (journal #44):
  guests DOUBLE-COUNTED 10 twins live since P3.5 (FOUR `range_ids` producers,
  the draft named one); the compute-side exclusion never reached the
  `track_perceptual` TABLE that `/explore`+`/recommend` read (merge-only
  persistence — the F-class trap again); PROVENANCE_ORPHAN would false-fire
  on a provenanced-then-flagged twin; the standalone audit had no
  authoritative twin set. **Shipped:** `canonicalize_ids/range_ids` (pure,
  dedup.py) at ALL FOUR producers (dashboard build AFTER enqueue's intake
  guard · /guest route + guest context canonicalize at READ so the pre-O3
  snapshot self-heals · snapshot script); `cache.twin_ids()` = THE one
  filter (perceptual + `prune_perceptual` table reconcile + `_drop_twins`
  in cluster training + `similar()` candidates (twin may still be the
  QUERY) + signature/nearest-artist populations + rollup n_tracks);
  `duplicate_flags.parquet` (authoritative, 35 rows) + **TWIN_LEAKAGE**
  tripwire + PROVENANCE_ORPHAN ref widened to card ∪ twins + the provenance
  mart excludes twins; corpus_facts honesty fields (n_unique_recordings /
  n_analyzed_incl_duplicates / n_duplicates_flagged); /library collapses
  (chip "N releases of this recording", twin titles searchable via
  alt_names, `?dupes=all` expands); twin `/song` URLs keep working + a
  canonical banner (own-features honesty — never borrow the canonical's
  provenance). **Live: 796 unique of 807 analyzed · header "796 analyzed of
  811 known" · Unravelling collapsed to 1 row w/ chip · twin banner live ·
  table pruned 807→796.** Corrections: the O3b commit message says "530
  tests" — the truth is 522 (miscount; this line wins). Interim residue: the
  /analytics scatter plots ~11 twin dots until the next retrain (cosmetic).
  ✅ **THE FULL D-52 RUN IS LIVE + D-56 OWNER-REPAIR SHIPPED (2026-07-23,
  session 56, Opus launch → Fable spot-check/design; commits
  3d1c38a→2779a13, 542 tests, app-verify ALL-FALSE).** Owner authorized the
  run; launched DETACHED (survives sessions; `scripts/re_extract_status.py`
  = the read-only progress view; backup taken first). **The spot-check
  discipline caught TWO live traps mid-flight** (journal #45): ① the DJ-SET
  trap — heuristic-v1 never rejects, so for obscure tracks the least-bad
  candidate is a 2-hour set (19 queued tracks carried mix-length audio up
  to 37x; the run was re-downloading them at 173 MB + ~9 GB RAM each) →
  duration guard (>2x AND >120 s vs Spotify's own length; pre-download via
  the Q1a youtube_duration_s + a post-load backstop); ② the WRONG-SONG trap
  — duration-match scores +25 with NO title requirement, so "any song of
  the same length" wins: **7 of the first 71 swaps were the wrong song**
  ("Alone" ← Anti-Up "Shake") → the title-affinity gate (≥1 meaningful
  TITLE-token overlap or squashed-title containment; artist-only is NOT
  enough; owner-ratified safe mode: reject to a human). Run relaunched
  healthy: guards firing correctly, ~24% at wrap, ledger ~33 = the repair
  queue. **D-56 BUILT SAME-DAY (owner specced + ratified: owner-only,
  hard-reject, build now):** `src/store/repair.py` (link repair:
  YouTube-host ALLOWLIST pre-yt-dlp (no SSRF) + duration HARD-REJECT
  pre-download; upload repair: streamed 20 MB cap, MAGIC-BYTE sniffing
  (never extension), ffprobe duration pre-decode, constant display title —
  the full D-45 posture; both end in the Q3 swap discipline + manual-link/
  manual-upload provenance w/ NULL confidence; never writes the runner's
  ledger — provenance-wins reconciliation clears entries) + the surfaces
  (`/library?filter=needs-source` owner tab w/ reasons; /song owner repair
  card w/ both forms + PRG flash). Gate: `WEBAPP_OWNER_SPOTIFY_ID` (.env)
  vs the session /me id — **FAIL-CLOSED, verified live (no forms render;
  the env var is NOT SET YET — owner step below)**. KNOWN FOLLOW-UP: the
  LIVE WORKER's default_acquire still lacks both guards (how the 19 DJ-set
  tracks got in) — adopting them for new-track ingestion is a separate
  owner-ratified change. The 7+ wrong-song swaps from round 1 keep their
  (honest) provenance and await D-56 repair.
  ✅ **Q3 CLOSED + VERIFY-LINKS + DATA-QUALITY QUARANTINE
  (2026-07-23, session 56 cont'd, Opus + Fable; commits 871d000→228b7ad,
  548 tests, app-verify ALL-FALSE, full audit clean, browser-validated).**
  **The full D-52 run finished (750 swapped, 2.9 h, 96% clean).** **V1+V2
  (f9bd9ca) made provenance VERIFIABLE:** /library's Src glyph is now a
  clickable link straight to the exact YouTube recording (proven live —
  clicking Sanctuary's ✓ landed on "Welshly Arms - Sanctuary"), /song got a
  "▶ Open source" button + visible URL, and owner UPLOADS are now RETAINED
  (`data/owner_audio/`, gitignored — an upload is the only copy) with an
  OWNER-ONLY HTML5 player at `/audio/{id}` (public playback = a licensing
  exposure; the YouTube link covers public trust). Owner gate hardened:
  self-diagnosing mismatch log (13a4498) + case/whitespace-insensitive
  compare (6e0a437 — owner id is the legacy `jordan_vercillo`, now set in
  .env). **DATA-QUALITY QUARANTINE (228b7ad — journal #46):** the run's
  pre-affinity-gate swaps (rounds 1-2) locked in **27 wrong-song
  acquisitions** via the resume marker (wrong features wearing heuristic-v1
  provenance — "Alone" ← Anti-Up "Shake"); `cache.quarantine_tracks` +
  `scripts/quarantine_wrong_songs.py` (detection REUSES `title_affinity` so
  "not confident" = "the gate would reject it"; dry-run-first, backup, then
  delete wrong analysis + dead-letter + file in needs-source) cleared all 27,
  bridge key kept, reversible by D-56 repair. **THE FINISH: retrain on 770
  CLEAN tracks** (broken/twin/wrong-song pollution gone; **0 tempo-0 left —
  the 2 broken extractions stay HEALED**) → e4b descriptions (clean prose,
  no jargon this time) → marts → audit: all semantic flags FALSE
  (FEATURE_DISTRIBUTION = only the 6 legit >1h DJ-mix duration tail;
  DUPLICATE_TRACKS = the frozen star-schema advisory). **Archetype shifted
  ONCE on clean data (ratified D-55): "The Anchored Loyalist" → "The
  Drifting Loyalist"** (σ 0.141→0.163, crossing the 0.15 band). New key
  files: `scripts/re_extract_status.py`, `scripts/quarantine_wrong_songs.py`,
  `src/store/repair.py` owner_audio retention, `cache.quarantine_tracks`.
  ✅ **VERIFY-LINKS + REPAIR HARDENING + D-57 (2026-07-23, session 56 cont'd;
  commits →D-57, 555 tests, app-verify ALL-FALSE):** provenance became
  CLICKABLE (library Src glyph → the exact YouTube recording, proven live);
  owner uploads RETAINED + owner-only playback; **five live bugs found and
  fixed by using the thing** (all in `docs/QA_PLAN.md` §A): the Anaconda-ffmpeg
  shadow that silently killed every repair (the first fix only DETECTED it and
  handed yt-dlp back the same binary), repairs leaving STALE derived planes
  (`/explore`+chat kept the old numbers), the 20 MB cap that made lossless
  masters impossible, the D-57 gate hiding the owner's own repair tools, and
  "117 bpm vs 112 bpm" on identical audio (headline = beat_track periodicity,
  section = beat DENSITY — two measures, one label). **D-57 (owner call):
  features are WITHHELD until the source is verified** — 46 analyzed tracks
  had no provenance (features from the same unguarded matcher that produced 27
  wrong songs), so /song withholds spectrogram/curve/sections/radar/figures,
  /library blanks the BPM cell, and similar() drops them from the candidate
  pool; a repair reveals everything. Two repairs proven live end-to-end:
  "1, 2 Step" (link) and "Roots" by WILDS (a 29.6 MB WAV master, the
  not-on-YouTube case D-56 exists for). **CORPUS TRUTH: 770 canonical analyzed
  · 724 source-validated · 46 unvalidated (withheld) · 72 needs-source · 35
  twins.**
  ✅ **EPIC QA — QA1 + QA2/B1 + B2 + THE DRAIN ALL SHIPPED (2026-07-23,
  session 57, Opus; commits c7ad7ad→2d1a0cf, 573 tests, ruff clean, deployed,
  browser-validated through the public edge).** Owner ratified both open
  decisions (B1 adopt, B2 exclude). **The session's finding, measured before
  building anything: the Q3 guards STILL admitted wrong songs** — swept over
  the 72-track queue, 4 of the 11 candidates they passed were wrong (journal
  #48). Title affinity fired on a single common token ("Up & Down" ←
  "Spice Up My Life" on `up`; "I need to know" ← "I never had" on `i`), the
  duration guard was ONE-SIDED (built against DJ sets, so an 83 s "Logic Pro
  Remake" of a 182 s track passed), and nothing knew what a *remake* was
  (KETTAMA "Fly Away XTC (Ableton Remake)" matched title+artist+duration to
  1 s). **QA2/B1:** `src/ingestion/match_gate.py` is now the ONE acceptance
  policy (title CONTAINMENT, leading-artist attribution, two-sided duration,
  reproduction markers) and `extractor.default_acquire` — the path every real
  login and playlist import uses, which had NO guards at all — delegates to
  `re_extract.guarded_acquire`. `implausible_duration`/`title_affinity` keep
  their exact old semantics (repair.py + quarantine_wrong_songs.py depend on
  them). Order INVERTED to **filter-then-rank**: every candidate faces the
  gate and the best survivor wins, where before the winner was picked first
  and then judged, discarding a usable recording at position 2 of the same
  search; search depth 5→10. **THE DRAIN (B3): 72 → 65, converged** —
  `scripts/drain_repair_queue.py` at the owner's channel-verified bar
  (artist's own/`X - Topic` channel, Δ≤10 s, no remakes); 7 repaired, each
  verified by hand against stored provenance (Lights On·Blue Stones,
  EL MUNDO ES MÍO·Bad Bunny, Near U·Isenberg, Ripples In The Timeline·Mall
  Grab, Peace of Mind·Hutcher, Wompa·MPH, Twizzy·Panteros666). **The
  remaining 65 are the honest floor, not a backlog: 44 have NO plausible
  YouTube candidate at all** (obscure UK garage/bassline) — D-56 manual flow
  only. Found mid-drain (journal #49): the dry run and real run disagreed
  because the runner searched Spotify's FULL credit list while the batch
  downloader searched only the primary artist — two conventions, materially
  different results; acquisition now searches BOTH and selects over the
  deduped union (that fix alone recovered 4 tracks at the same bar).
  **B2:** `cache.excluded_from_aggregates()` = twins | unvalidated is THE one
  population filter (perceptual plane + prune, both cluster trainings,
  `similar()`); aggregate corpus **771 → 731**, retrained model #9 silhouette
  0.172→**0.174**, buckets UNCHANGED, **archetype UNCHANGED (The Drifting
  Loyalist)**; `corpus_facts` gained `n_withheld_unvalidated`. **FAIL-SAFE
  (journal #50): with zero provenance rows nothing counts as unvalidated** —
  without it an empty/unreadable `track_provenance` (restore, migration, bug)
  would silently empty the clusters, /explore and the chat in one rebuild.
  **QA1: `scripts/qa_audit.py`** — one command, 9 checks against LIVE data,
  exit 1 on any FAIL (**live: 0 failed · 7 passed · 2 notes**); the `B1` check
  is BEHAVIOURAL (drives `default_acquire` with a rigged in-process search and
  asserts nothing downloads). It found a bug in itself on first run: it
  reported the owner's uploaded WAV master as a wrong song, since a D-56
  manual repair stores the constant "Owner-supplied audio file" as its title —
  manual provenance is now skipped by the matcher-quality checks, never judged
  by them. **Warehouse audit: provenance coverage 731/731 of the aggregate
  corpus (100%)**; the only true flags are the documented B4 (6 legit >1 h
  DJ-mix durations) and B5 (frozen Jul-4 star-schema advisory).
  ✅ **CI HEALTH RESTORED + THE HONESTY PAIR + DoD ⑥ (2026-07-24, session 57
  cont'd, Opus + agile-coach consult; commits 02408ec/a8ccbe9/eb1ed37, 579
  tests, CI GREEN ×3, app-verify ALL-FALSE).** **CI had been RED for 12
  commits** — since before this session — on two owner-gate tests that passed
  locally: after a response rotates the session, httpx keeps TWO `va_sid`
  cookies (the test's domain-less one + the server's `testserver.local` one),
  `cookies.set()` updates only the first, and which is sent is
  version-dependent, so "log in as someone else" silently kept the PREVIOUS
  user on CI (one case even let a DIFFERENT id pass the D-56 owner gate in the
  test). Fix: `_become()` clears the jar before setting; a new test asserts the
  version-independent invariant (exactly ONE session cookie), because asserting
  behaviour is what hid it (journal #51). **The honesty pair (a8ccbe9):**
  `/library` rendered "analyzing…" for ANY unanalyzed track including 40+
  dead-lettered ones — `cache.job_states()` + pure `library.annotate_queue_state`
  now split queued/running/under-cap ("analyzing…") from failed-at-MAX_ATTEMPTS
  ("no source"); and D-54 finally shipped (dashboard top-artist cards link to
  `/artist/{id}` — the id was already in the fetched frame, zero API calls; guest
  path too). **DoD ⑥ (eb1ed37):** README + `docs/CASE_STUDY.md` were frozen at
  2026-07-16 (417 tests, 117 tracks, "ALL-GREEN", 0.14σ) — refreshed to the
  current surface, every number traced to a live command (579 tests, 771/731
  corpus, 0.185σ "The Drifting Loyalist", 100% aggregate provenance); the
  frozen gold plane handled with an explicit **two-plane** framing (live serving
  771/731 vs a reproducible 118-track batch star-schema snapshot the MCP demo +
  taste map read); the provenance/QA spine is now a full case-study §3. **The
  agile-coach consult corrected a stale fact this session had written: Phase 4.5
  is NOT closeable after QA3** — it holds Epic Q AND **Epic R (Artists 2.0 —
  0 lines of code, NO recorded deferral)**, and the D-55 prototype DoD is 4/7
  (⑥ now done; ③ Epic-R-or-deferral and ④ "audits ALL-GREEN" — unpassable as
  worded — remain). "Then Phase 5 is next" was wrong; the prototype gate is not
  yet met.
  ✅ **QA3 SHIPPED + 🏁 PHASE 4.5 EXITED (2026-07-24, sessions 57 cont'd–58,
  Opus + data-platform consult; commits af…→c1c91f9, 597 tests, CI green, both
  audits clear).** **QA3 (12ae966):** `scripts/review_provenance.py` +
  `src/store/provenance_review.py` (pure) mirror the D-47 flywheel for
  provenance — the sampled match-QUALITY read (`--report` → dated `evals/runs/`
  artifact, `--sample` → gitignored worksheet). **The design lesson (journal
  #52):** the first cut reused `confident_match` (the strict WRITE gate) as the
  health verdict → its "review" tier was 69 rows, MOSTLY FALSE POSITIVES (the
  gate over-rejects right songs on word order/spelling/channel because for an
  unattended write "reject to a human" is correct). Re-tiered on a purpose-built
  `match_gate.title_recall` (is the SONG recognisable?) → worklist 69→7, all
  genuine. Live: 731 events, 82% would re-pass, 7 want-a-look. **The exit needed
  real work, not a re-run** (owner: "re-run both audits clear → exit"). **THREE
  DECISIONS ratified (D-58…D-60):** Epic R DEFERRED with written reasoning
  (satisfies DoD ③), DoD ④ amended, B4 fixed by data-repair, B5 by the exporter.
  **D-59 (cd9dfb9) — B4 was NOT "6 legit DJ mixes"** (an unverified QA_PLAN
  assumption): probing found ONE bad row — Taylor Swift "TTPD", a 2 h source
  stored as a 4-min song, slipped the guard because Spotify `duration_ms`=0 so
  "unknown→never guess" admitted it. Loosening the audit would gate-mask it
  (violates ④), so instead: `implausible_duration` hardened for the unknown-
  length case (`_ABSOLUTE_MAX_TRACK_S`=30 min) + `scripts/quarantine_bad_durations.py`
  (reuses the guard, journal #46 discipline; aggregate-affecting scope) →
  quarantined TTPD alone → **FEATURE_DISTRIBUTION cleared honestly**, corpus
  731→730. **D-60 (601e0ac) — the cache→gold exporter** (`src/warehouse/from_cache.py`
  + `scripts/export_gold_from_cache.py`, data-platform consult Design 2): reads
  the cache → current-canonical `dim_tracks`(730) + track-grain
  `fact_track_features`(730) + refreshed `dim_artists`; **DUPLICATE_TRACKS
  cleared.** THE GRAIN CALL: `fact_listening_features` LEFT UNTOUCHED — its
  per-user time_range grain can't be honestly reproduced for the user-agnostic
  corpus without fabricating ranks (REAL-data-only), so the CATALOG unifies, the
  drift plane stays an honest snapshot (README/case-study corrected — the taste
  map does NOT read 730). New audit: `JOIN_ORPHANS` targets the current catalog
  fact (drift fact exempt, self-contained); **`GOLD_PLANE_STALE`** = dim_tracks
  set == track_card set (catches the exporter going stale). Exporter idempotent
  (byte-identical rerun). **BOTH AUDITS CLEAR: warehouse ALL FLAGS FALSE,
  qa_audit 0-failed. All 7 D-55 criteria met.**
  ✅ **EPIC O4 + QA-2 SHIPPED (2026-07-24, session 59, Opus + orchestrator;
  commits 9d7a980→618c4d7, 771 tests, ruff clean, both audits clear, deployed,
  browser-validated): AGGRESSIVE DEDUP CONSOLIDATION + FULL-SURFACE VALIDATION.**
  Owner ask: "all duplicate tracks consolidated aggressively — album vs single is
  one track; the only difference is different audio for a different version
  (remix/live/acoustic)." **THE FINDING (journal #54): `dedup.py` did the exact
  OPPOSITE of both halves** — `normalize_title` STRIPPED version qualifiers (so a
  remix and its original shared a bucket) and required exact full-artist-string
  equality (which blocks the album-vs-single merges the ask wants). The corpus
  had no wrongly-merged remixes only by ACCIDENT: 5 pairs were saved by a
  credited remixer changing the artist string, and 2 — "Air Maxes"/"- KETTAMA
  MIX", "Everchanging"/"- Acoustic" — by nothing but a 30 s duration gap at
  IDENTICAL artist strings. **O4a** `parse_title()` EXTRACTS the qualifier;
  merge needs base AND version_tag equal — tag EQUALITY not absence ("It Gets
  Better - Forever Mix" ships on two releases, both tagged). Brackets strip only
  when their content is a known qualifier, fixing a real collapse ("JOY (If You
  Want)"/"JOY (By My Side)" both normalized to "joy"). **O4b** release-blind +
  credit-blind keying (primary_artist_id else LEADING credit) guarded by
  `CREDIT_BLIND_WINDOW_MS=1500` — measured: every credit-differing same-base pair
  is a REMIX, one only 6860 ms away, INSIDE the 7 s window. **O4c** duration-led
  second pass under ONE union-find: exact-duration equality makes two SPELLINGS
  candidates ("Airmaxes" shares no token with "Air Maxes"). **O4d**
  `find_disagreements` — metadata says one recording, acoustics refuse ⇒ a
  PROVENANCE defect, its own mart (never rows in `duplicate_flags`, which would
  trip TWIN_LEAKAGE) + `DEDUP_DISAGREEMENT` asserting mutual exclusivity.
  **SHIP-BLOCKER (red-team): flagging a twin writes a TERMINAL `done` job**, so a
  cleared flag would strand the track forever (25 of 35 twins uncached) —
  `refresh_duplicate_flags` now re-opens the job it authored, and only that one.
  **LIVE: 730→728 canonical, exactly as pre-measured** (+`Here's Lookin/Looking
  At You, Kid`, +`Air Maxes/Airmaxes`, −`Bliss` un-flagged from the RemiXX, which
  came back `queued` — the blocker fix proving itself). O4d found the 1 predicted
  pair: Muse "Won't Stand Down" ×2, identical Spotify duration, z-cosine 0.667.
  **OWNER CALL: DJ "- Mixed" edits SPLIT** (different audio, the rule as
  written). The synthetic warehouse fixture caught a false-merge class the corpus
  lacks ("Club 0"/"Club 1" = 0.83 difflib) → digit-sequence guard.
  **QA-2:** `test_route_matrix.py` — 28 routes × 4 personas, coverage enforced by
  SET EQUALITY, plus the **side-effects column** (a repair route returns the SAME
  303 to all four personas; only "did the engine run" separates blocked from
  executed). Closed **17 blind gate cells across 12 routes**, incl. `POST
  /song/{id}/repair-upload` which had NO test of any kind. **TWO BUGS FIXED:**
  `/guest` hijacked a logged-in session (overwrote taste with the owner's
  snapshot + set is_guest for anyone) and `/openapi.json` served the full surface
  map anonymously (200→404 verified live across the redeploy).
  `test_dedup_golden.py` encodes the owner's rule over REAL corpus pairs (+2 live
  sweeps that skip on CI); `scripts/smoke_public.py` = the standing
  browser-validation practice scripted (GET-only, credential-free, exit 2 =
  ORIGIN DOWN vs 1 = BROKEN, proves the ORIGIN rendered each page via
  base.html's stylesheet tag). **Live smoke 14/14 through the public edge.**
  **journal #55: the matrix's first act was catching a machine-dependency in
  ITSELF** — the owner cell read the real re-extract ledger on disk, so it passed
  here and failed on CI; fixture now owns its ledger + tmp audio/spectrogram
  dirs, with a count assertion proving the patch took. Browser-validated live:
  `?q=looking at you` → ONE row + "2 releases of this recording" (matched via the
  OTHER spelling); `?q=everchanging` → TWO rows whose BPMs (144 vs 123) confirm
  the acoustic take IS different audio. Audit adds `DEDUP_DISAGREEMENT` (20 flags,
  all false); `check_duplicates` gained its known blind spot IN WRITING (it runs
  the rule over a population the rule already filtered, so it cannot see a false
  merge — only the pair tests can).
  ✅ **DQ WRONG-TAKE QUARANTINE + EPIC I UNCAP + THE PERF PASS (2026-07-25,
  session 60, Opus + orchestrator; commits e7319b2→c2d45d4, 803 tests, CI green,
  both audits clear, deployed, browser-validated).** **① DQ (owner: "I don't want
  any data that's not verified on the app"):** the corrected count was NOT 105 —
  50 unvalidated + 27 never-analyzed = 77 were ALREADY blank (the two groups
  overlap by 39). The real find was **34 source-validated tracks showing features
  from a DIFFERENT RECORDING of the right song**, invisible to every existing
  check: `match_confidence` scores them 0.80–0.85 (song, artist, length all
  right) and QA3's `title_recall` measures the CORE title BY DESIGN, so a remix
  sourced from its original scores 1.0. Only O4's version tags could see it.
  `match_gate.version_mismatch` is the instrument (sibling of `title_affinity` =
  wrong SONG and `implausible_duration` = wrong LENGTH). **Precision fixed BEFORE
  executing:** the first dry run flagged 38; reading all 38 found 4 false
  positives with systematic causes → "Original Mix" is a RELEASE qualifier (also
  correct for dedup), a source that merely SAYS MORE about the same take is not a
  mismatch (directional subset rule — our "- Mixed" still fails), and a song
  NAMED after a version word ("Speed Garage") makes no version claim. 38→34, diff
  exactly those four. Owner chose DELETE over withhold; `quarantine_tracks` also
  DEAD-LETTERS so the worker can't re-grab the same wrong audio. Corpus 769→735
  analyzed, gold 728→695, silhouette 0.174→0.176, `confident_match` 82.4%→84.1%.
  **② The dead-letter gap (journal #57):** one track was blank, unretried AND
  invisible to `/library?filter=needs-source` — the repair queue read only the
  re-extraction LEDGER, and the ordinary worker doesn't write one. `_needs_source`
  is now the union with `cache.dead_lettered_ids()`. **③ EPIC I UNCAPPED (owner:
  "I want to be able to upload an entire playlist"):** `PLAYLIST_IMPORT_CAP`
  defaults to 0 = off (an explicit cap still works, skip-then-cap intact);
  Analyze now redirects to **/queue** (visible proof + it stopped re-fetching
  every playlist, which was half the reported "freeze"); `/queue` had been LYING
  past 200 (count and ETA both derived from a display-capped list) → `queue_count()`,
  verified live reading "350 tracks · 292 min" where the old code said 200/167;
  new `playlist_tracks` table records membership at import so cards show "N of M
  analyzed" (never-imported = "not imported yet", an absence not a claim); Queue
  tab in the nav. **④ THE STICKY DEMO BUG (owner: "when I click back it brings me
  to the demo"):** `is_guest` was never cleared and `_store.rotate()` preserves
  session data, so anyone who had once viewed the demo stayed flagged a guest
  FOREVER — banner on every page, owner's snapshot taste in their session. A real
  login now supersedes the demo persona. **⑤ THE PERF PASS (journal #56):**
  measured first — everything was 2–15 ms except `/library` 120 ms and `/song`
  177 ms, both from `select(TrackFeatures)` dragging the 82-col dict + loudness
  curve + beat grid + sections (6.6 MB of JSON for 18 KB of floats, a 370:1 waste)
  to read a few promoted scalars. Fixes: column projection, `analyzed_ids()`
  (87→0.7 ms, sits under every aggregate), `feature_columns()` for the 13
  in-JSON similarity cols, and the **similarity plane** — a per-process memo
  behind a freshness token DERIVED from the source tables (row count + newest
  extraction + promoted sums + twin set + validated set), recomputed every call
  so no future writer can forget to invalidate it (bug A5 defused by
  construction). `similar()` 176 ms → 7.7 ms warm. **P4 guards assert WORK DONE,
  not milliseconds** (`test_store_perf.py`): SQL-shape tripwires, an amortization
  check, constant query count, and 4 staleness tripwires — one per invalidation
  edge — plus the inverse (a display-only backfill must NOT rebuild).
  **⑥ /library PAGINATION:** the server was fast but the PAGE still shipped every
  row (757 KB / 1,259 rows). `page_slice` consumes `library_view`'s output and
  never sees unsorted rows, so a page-local sort is UNREPRESENTABLE; the lede
  stays whole-corpus, `rows` survives the slice (so the my-songs count can't
  shrink to a page), the pager always reaches the last page, `?per=all` stays.
  **757 KB → 64 KB, now CONSTANT in corpus size; /library 120 ms → 16 ms.**
  Mobile fixed too: the body scrolled horizontally at 375px (572px wide) → the
  catalog now scrolls in its own `.lib-wrap`, tap targets 40×42 → 44×44.
  Live proof of the global sort: tempo desc gives 172 bpm on page 1, 117 on page
  7, page 13 the final partial slice.
  ✅ **THE PRODUCT-USE ERA (2026-07-25→28, sessions 60–62, Opus + orchestrator;
  commits 678cd92→fae810a, 838 tests, ruff clean, deployed): Jordan USED the app
  hard and it produced more real bugs than any design session has.** Corpus
  **1,742 analyzed** (was 730 — 2.4×) as playlist imports drained.
  **① PERF (journal #56):** measured first — everything 2–15 ms except `/library`
  120 ms and `/song` 177 ms, both from `select(TrackFeatures)` dragging the
  82-col JSON + loudness curve + beat grid + sections (6.6 MB parsed for 18 KB of
  floats) to read 3 promoted scalars. Column projection + `analyzed_ids()`
  (87→0.7 ms, sits under every aggregate) + `feature_columns()` + the
  **similarity plane** (a per-process memo behind a token DERIVED from the source
  tables, recomputed every call so no writer can forget it — A5 defused by
  construction). `/library` 120→16 ms, `similar()` 176→7.7 ms. **P4 guards assert
  WORK DONE not milliseconds** (`test_store_perf.py`: SQL-shape tripwires,
  amortization, constant query count, 4 staleness edges + the inverse).
  **② /library PAGINATION:** 757 KB → **64 KB, constant in corpus size**;
  `page_slice` consumes `library_view`'s output so a page-local sort is
  UNREPRESENTABLE; lede stays whole-corpus; pager always reaches the last page;
  `?per=all` kept. Mobile: body scrolled at 375 px (572 px wide) → `.lib-wrap`;
  tap targets 40×42 → 44×44. **③ EPIC I REWORKED end-to-end** — whole-playlist
  import (cap 50 by owner call, reliability over speed), **page-bounded +
  resumable** (the drain of a 1004-track playlist was 21 API calls PER CLICK;
  now 1–2, resume offset DERIVED from recorded membership, self-correcting on a
  shrunken playlist, `PLAYLIST_IMPORT_MAX_PAGES=6` ceiling), Analyze **stays on
  /playlists** with a scanned/already-done/queued confirmation beside the
  highlighted card, Queue nav tab, `queue_count()` (the queue page had been
  LYING past its 200-row display cap). **④ FOUR SURFACES, ONE LIE (journal
  #58):** a 429 rendered as "No importable playlists found"; a failed fetch as
  "Queued 0"; a rate-limited dashboard as **502** → Cloudflare's fallback showed
  "Demo offline" (now 503 + session PRESERVED — it used to log you out, making
  recovery cost more API calls); a failed-under-cap job as "analyzing…" while
  the queue was empty. Standing tripwire: **no route may return a status in the
  Worker's ORIGIN_DOWN set** (502/504/521-523/530) — invisible locally.
  **⑤ THE ACCOUNTING TRILOGY** — a card reading "50 of 129" was accurate but
  unexplained: dead-lettered tracks needed a MANUAL source (now counted), dedup
  **twins** were counted as missing forever (130 corpus-wide — their canonical
  carries the features), and Spotify's `track_count` includes local/
  market-unavailable items the items endpoint never returns (`PlaylistImport`
  records whether a walk REACHED THE END, so a complete walk counts what it
  FOUND and names the gap "unavailable to import"). **⑥ MY REGRESSION, found by
  using it (journal #59):** the backlog fix made dormant bad data reachable —
  membership recorded ids `remember_meta` never saw, so **214 tracks were queued
  with no name and dead-lettered as "no track metadata"**. Cause fixed (store
  EVERY paged record), invariant added (`searchable_ids` — never enqueue what
  cannot be looked up), damage repaired live by `scripts/repair_missing_meta.py`
  (batched /tracks, 6 calls: **named 281/282, re-opened 213**, queue 0→210, 1
  genuinely gone from Spotify). **⑦ `requeue_retryable`** — 142 failed-under-cap
  jobs sat forever because only a dashboard visit re-queued them and
  playlist-imported tracks are never revisited; the worker now converges them to
  done or dead-lettered.
  **➡️ NEXT ACTION — the corpus more than DOUBLED, so the derived planes owe a
  rebuild before anything else.** Two audit flags are TRUE right now and both
  have named causes: **GOLD_PLANE_STALE** (983 tracks only in serving — the
  exporter hasn't run since the growth) and **FEATURE_DISTRIBUTION** (exactly
  ONE broken extraction, "Defector" by Muse, tempo 0 / −180 dBFS — the D-52
  class Q3 healed twice before). Wait for the ~210-track queue to drain, then:
  `build_feature_marts.py` → `export_gold_from_cache.py` → quarantine or
  re-extract Defector → re-run both audits → consider a cluster retrain (the
  corpus is 2.4× the size the current model trained on, so the archetype may
  legitimately move). THEN Phase 5 (MPD/Spark, D-26…D-29) as before, starting
  with the AIcrowd dataset + license check. Owner track: ~394 needs-source
  repairs (grew as the guard correctly refused bad audio), and the DMARC
  `quarantine`→`reject` DNS flip.
  **➡️ SUPERSEDED — PHASE 5: MPD/Spark (metadata-only, D-26…D-29), launching
  from a defensibly-complete base as D-55 intended.** First slice per
  `docs/VISION_SPECS.md` §Phase 5: **verify the AIcrowd MPD dataset is still
  obtainable + its license (research-expert, ~30 min) BEFORE committing the
  phase** — if that door's closed, Phase 5 as specced evaporates. Then **J0**
  intake script (local, gitignored, idempotent) → **J0.5** the overlap
  measurement (how many of the 730 bridge keys appear in MPD — this NUMBER
  decides whether J2 hybrid reco is worth building; agile-coach's addition) →
  J1 Spark co-occurrence + track2vec on real 66M rows → J2 hybrid acoustic×
  behavioural reco → J3 the honest at-scale benchmark. Spark NEVER on the
  download path. Owner track, at leisure: the ~66-track needs-source queue via
  `/library?filter=needs-source`; the 12 already-withheld bad-duration tracks
  (`quarantine_bad_durations.py --include-withheld`) are optional cleanup.
  DEFERRED — post-prototype enrichment, not blocking: Epic R (Artists 2.0,
  MusicBrainz — D-58 deferral); K4 uploads (Phase LLM-2, appetite gate); K5/K6.
  DEFERRED (not blocking):
  O3d — the acoustic recall miner (cross-name same-audio candidates from the
  77-dim vectors, review-report-only, after Q3's uniform re-extraction);
  S4 DMARC reject-flip (owner, ~Jul-25 after clean reports); cluster_profile
  online-cluster (owner call — now 99.7% covered, the gap is tiny).
  RESIDUAL (honest):
  when the tool model MUST surface a hostile import name, the render-cap (120
  chars, no newlines) bounds but doesn't erase echoed attacker text — the D-47
  chat log is the production monitor. `/chat` UX: the full async/streaming
  rebuild is still the "eventually" item (S3 removed the frozen-page feel, not
  the latency). Parked: MPD-audio, Epic M, instrumentalness, dupe-pruning.
  ✅ **VISION F SPECCED + RATIFIED (2026-07-29, session 63, Fable +
  orchestrator; commits 980f56c→bd412b0, CI green incl. the NEW gitleaks
  full-history job):** the part-two re-envisioning — 5 expert consults +
  live browser walk → the 17-finding evaluation ledger, strengths stop-list,
  **D-61…D-67 ALL RATIFIED** with pinned execution parameters, Phases
  4.6/4.7 inserted before Phase 5, and **D-65: Phase 5 re-substrated from
  MPD (legally blocked — dataset withdrawn + license bars portfolio use) to
  the AcousticBrainz CC0 dump** (29.5M rows; also our first independent DSP
  ground truth). Key live-verified findings driving the plan: cluster plane
  at 36.7% coverage w/ NULL descriptions (regressed silently in 7 days —
  the one-sided audit bound), ~14.8 s/track real throughput welded to
  YouTube request rate (no sleep exists to hide work behind), tempo
  quantized to a 20-value lag grid + near-coin-flip mode (v2 candidates,
  D-67-gated), `all_features()` on 2 request paths, 15 of 892 artists
  browsable. Harness: `ui-ux-expert` agent registered; full spec + the
  S1–S6 Opus plan in `docs/VISION_SPECS.md` §Vision F.
  **✅ VISION F S1–S3 SHIPPED (2026-07-29/30) — the whole PLATFORM half; see
  the session log.** S1: yt-dlp CVE floor + search throttle + flat-search
  contract; `/analytics` + `/artist/{id}` projections (280 ms/6.5 MB →
  54 ms/0.6 MB). S2: **the F1 fix — cluster coverage 36.7% → 100%** + the D-62
  train/promote split, 4 audit flags, two pre-existing bugs killed (journal
  #64/#65). S3: the post-drain chain 1.39× and debounced (headroom ~11k →
  ~15.3k), **ISRC 0% → 100%** (D-70, journal #66), `GOLD_SCHEMA_SHRINK` +
  `dim_tracks` restored to 11 columns. Spark runs and PASSES parity locally on
  WSL2 (`scripts/spark_wsl.ps1`); the Windows Spark/Hadoop install was removed
  by owner decision. **PHASE 5 IS UNBLOCKED** — D-70 was its hard prerequisite.
  **➡️ NEXT ACTION — Vision F S4 (P4.7.0 + P4.7.1), the first user-facing
  slice:** lift `_BANDS` / `_SIGNATURE_DIMS` / the archetype thresholds into
  ONE `src/webapp/scales.py` with caption-parity tests — **before Epic R
  doubles their consumers** — then `RAW_FEATURE_DOC` in the DSP layer + the
  `raw_feature_dictionary`/`raw_feature_stats` marts + **`GET
  /song/{id}/features`** (all 83 numeric features grouped, D-66) with the
  set-equality tripwire so an 84th feature can never ship undocumented. Owner
  track unchanged: needs-source repairs at leisure; the DMARC reject-flip.
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
| `legacy/PR_REFERENCE.md` | Historical: the Copilot PR write-up for Phases 1–4. Describes a webapp + git history this repo copy does NOT contain (see journal #4). Moved out of root at P3.7 (public-visitor confusion). |
| `notes/project_roadmap.md` | Severity-ranked weaknesses + the phase gameplan with exit criteria. |
| `notes/engineering_journal.md` | Numbered insight journal — surprises, not progress. |
| `llm_knowledge_base/` | **READ-ONLY synced copy** of the course knowledge base (technique cards, skill patterns, tooling matrix). Canonical: `language-models/kb/` — see `llm_knowledge_base/KB_PROVENANCE.md`; never edit here, propose upstream. **LOCAL-ONLY since P3.7 (D-21): excluded from the public repo + scrubbed from history; gitignored. A public clone won't have it — the llm-rag-expert charter + resume skill reference it as owner-machine context.** |
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
| `src/store/test_store_perf.py` | **The speed guards (P4, 2026-07-25).** Assert WORK DONE, not milliseconds — a timing threshold in CI measures the runner, and the regression is categorical anyway (one `select(TrackFeatures)` on a request path). SQL-shape tripwires (no heavy JSON column may be named), an amortization check (many `similar()` calls, ONE plane build), constant query count, and 4 staleness edges — extraction / quarantine / twin-flag / repair — each asserting the VISITOR sees the new answer, plus the inverse (a display-only backfill must NOT rebuild). |
| `cache.{feature_columns,analyzed_ids,searchable_ids,queue_count,requeue_retryable}` | **The read-path primitives (2026-07-25/28).** `feature_columns` projects named keys OUT of the features JSON in SQL (portable); `analyzed_ids` is ids-only (87→0.7 ms, sits under `excluded_from_aggregates`); **`searchable_ids` is the invariant that cost 214 tracks** — never enqueue what has no stored name; `queue_count` is the real queue (not the display cap); `requeue_retryable` converges failed-under-cap jobs the dashboard would never revisit. |
| `cache._similarity_plane` + `_population_token` | **The `/song` hot path (2026-07-25).** A per-process memo of the z-scored corpus matrix, keyed on a token DERIVED from the source tables (row count + newest extraction + promoted sums + twin set + validated set), recomputed on EVERY call — a version counter a writer must remember to bump is how bug A5 happened. 176 ms → 7.7 ms warm. |
| `PlaylistTrack` / `PlaylistImport` (`models.py`) | **Playlist membership + walk completeness (Epic I, 2026-07-27/28).** Membership powers "N of M analyzed", the resume offset, and the zero-fetch backlog; `PlaylistImport.complete` records whether a walk REACHED THE END, which is what lets a finished playlist count what it FOUND (Spotify's `track_count` includes local/market-unavailable items the items endpoint never returns). Soft refs both ways; nothing joins on `playlist_id`. |
| `scripts/repair_missing_meta.py` | Repairs the journal-#59 damage: playlist members recorded as ids but never named. Batched `/tracks` (50/call), re-opens ONLY jobs whose error was "no track metadata" — a real failure keeps its error and attempts. |
| `scripts/smoke_public.py` | **QA-2 layer 5:** the standing browser-validation practice scripted. GET-only, credential-free, 14 checks through the public edge; **distinguishes ORIGIN DOWN (exit 2) from BROKEN (exit 1)** and proves the ORIGIN rendered each page via base.html's stylesheet tag. Not in CI (no tunnel, no corpus there). |
| `src/webapp/test_route_matrix.py` | **QA-2 layer 3:** 28 routes × 4 personas, coverage enforced by SET EQUALITY, plus a **side-effects column** (the repair routes answer every persona with the same 303 — only "did the engine run" separates blocked from executed) and a standing tripwire that **no route may return a status in the fallback Worker's ORIGIN_DOWN set**. |
| `src/webapp/{artists,library,playlists}.py` | **Vision-E product surfaces (pure view logic).** `artists.py` (P3.2 — rollup, genre strip, comparison SVG, `your_top_by_artist` D-33, `nearest_artists`). `library.py` (P3.3 — `library_view` search/sort/dedup-annotate/mine-overlay, `why_n_analyzed` from `_TOP_LIMIT`); fed by `cache.library_rows()`. `playlists.py` (P3.4 — `playlist_cards`/`importable_ids` own+collaborative filter, `coverage_line`); `/playlists` + `POST …/analyze` behind `auth_web.has_playlist_scope` (re-consent), cap `config.PLAYLIST_IMPORT_CAP`. `/library`+`/song`+`/spectrogram` PUBLIC (D-18/D-40); `/explore`+`/recommend`+`/playlists` gated. Tests: `test_artists.py`, `test_library.py`, `test_playlists.py`. |
| `infra/cloudflare/origin-fallback-worker.js` | H5 (P3.6): the $0 origin-down fallback Worker — 502/504/521-523/530 → an honest 503 "runs on-demand" card; healthy origin untouched; /healthz keeps JSON truth. Owner deploys via dashboard paste (SELF_HOSTING §6a). |
| `evals/runs/` | **Dated LLM-path eval artifacts (K0 convention):** `YYYY-MM-DD_<model>_<setname>.txt` — the committed numbers every D-42 gate measures against (gemma4:12b 9/15 2026-07-16 → 13/15 2026-07-17 after the K0.5 fixes). The fallback/constant anchors + a "by source" line ride in the same artifact. |
| `src/store/semantic.py` | **The D-49 semantic layer (Talk-to-your-data data floor):** governed analyst marts materialized FROM the cache (source of truth, journal #35) via `rebuild_marts` post-drain — `feature_dictionary` (rule-3 caveat as a row), `track_card` (feature_valid gate — no broken superlatives), `artist_rollup` (by primary_artist_id). NO embeddings (SQL + entity cards). Tripwires: `test_semantic.py`. cluster_profile still TODO. |
| `src/webapp/prompt_contract.py` | **The D-48 RTCROS contract (ONE encoding):** `PROMPT_VERSION` · `build_system(adhoc\|story\|profile)` — story is the FLAT `answer` field (gemma4 chokes on nested JSON) · `verify_citations` (checks cited[] against the grounding — gemma4 hallucinates inside cited[]) · `is_empty_reply`→fallback. gemma4 needs a user directive or returns empty (journal #37); weak on strict-label adhoc (journal #36). |
| **ChatLog / ChatLabel** (`src/store/models.py`) | **D-47 the review flywheel's spine:** every `/ask`·`/classify`·`/chat` turn logged for the REVIEW READER (question · full grounding sent · raw+parsed output · source · cost), `chat_session_id` = a per-session uuid (NOT the auth sid). `cache.log_chat_turn`/`recent_chat_turns`. `/privacy` discloses it, 90-day retention. `ChatLabel` = the human grades (rubric-v1) that become K5's dataset. Review script = K1.5 TODO. |
| `src/webapp/templates/chat.html` + `TasteRAG.story()` | **K1c the story-led /chat:** viewer-gated; opens with gemma4's generated data story (its strength when it engages), then PRG adhoc turns, ~20-turn history. gemma4 is inconsistent+slow → the deterministic fallback carries reliability. |
| `src/webapp/chat_review.py` + `scripts/review_chat_logs.py` | **K1.5 the D-47 review flywheel:** sample ungraded ChatLog turns (stratified) → `pre_grade` the machine-checkable dims → a human grades accuracy/usefulness/verdict → ChatLabel rows → the `k5_eligible` counter + golden candidates. `--sample`/`--commit`/`--report`; worksheets gitignored (raw text stays local), only the aggregates report → `evals/runs/`. |
| `docs/CASE_STUDY.md` | **P3.7: the portfolio narrative** — the API-removal origin story, architecture, $0 production, the earned doctrines (w/ journal numbers), and the AI-harness methodology. The README links it front-and-center. |
| `LICENSE` | MIT (owner choice, P3.7). The KB was history-scrubbed pre-flip, so no license conflict with course material. |
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
  Jordan added the first pilot tester in the Spotify dashboard (screenshot: "1/5
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
  2026-07-11/12, before Epic H** (2/5 seats filled: the first pilot user 07-09, the second 07-10).
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
- **2026-07-11 (session 26 — Vision D Phase 1 build, Fable 5): 3 slices shipped,
  browser-validated, 337 tests green, CI green.** ✅ **D-31 rename** (dropped
  "Taste Pilot" → top-left is just "Vercillo Analytics"; nav/title/FastAPI +
  test, commit 3cb0d31). ✅ **B1** (commit 7c34084): `/recommend` seed targets
  now REFRESH when you pick a new seed — extracted a pure `apply_seed_targets`
  that re-fills on seed-change (tracked via a hidden `prev_seed` field), drops
  the prior seed's auto-targets, preserves hand-tuned ones; 5-assert regression
  test. ✅ **H7 / D-30 guest demo persona** (commit 57c2397 — the interview
  showpiece): `scripts/snapshot_demo_profile.py` (gold warehouse → gitignored
  `data/demo_profile.json`, 117 cached tracks); `GET /guest` → read-only session
  preloaded with the owner's taste → the FULL personalized analytics with NO
  login/5-seat gate; `_is_viewer` opens the cache-only read surfaces (/analytics
  /explore /recommend /song /spectrogram) to guests while token/write actions
  stay auth-only; landing "View as guest" CTA + demo banner + guest nav +
  /classify hidden for guests; 3 tests. **Live browser-validated on 127.0.0.1:8000:**
  rename shows, guest → /analytics renders archetype "The Anchored Loyalist" +
  signature + drift + map + loudness arc + Muse bucket, banner + guest nav
  present, /classify hidden. App REDEPLOYED (restart, cache backed up), all-green.
  ✅ **Then H3 + H4 shipped (commit 3186796, 337 green, browser-validated):**
  **H3** popularity now rides each dashboard track into the hover tooltip
  (shown even pre-analysis; labelled fetched-not-acoustic). **H4** mobile
  cut-off sweep via a live 375px overflow probe — fixed the header nav
  overflowing (Log-in CTA off-screen → header/nav flex-wrap, page 460→375px) and
  the /recommend tunables table clipping its max column (→ overflow-x:auto scroll
  box); /analytics /explore /recommend /song all verified docScrollW==viewport at
  375/299px, desktop unaffected. ✅ **Harness upgrade (repo-bootstrap audit):**
  this repo was already ahead of its own templates in every tier; the one real
  gap was the resume↔wrap loop. Added `/wrap-session` (light session-save,
  decoupled from pipeline-partner Phase 5), `/orchestrator` (lead + advisory
  domain-expert agents, complements the generalist flow) + a seeded
  `.claude/agents/data-platform-expert.md` (advise-by-default, in-lane), and a
  full routing table in CLAUDE.md (was missing resume + app-verify). Cosmetic
  drift (engineering_journal vs journal.md, docs/SPEC vs specs/) LEFT ALONE —
  renaming = churn. All additive, nothing clobbered; both new skills discovered.
  **Left off: Phase 1 REMAINING = N1 stats/σ explainer, N2 12-archetype
  taxonomy, O1 dedup-as-flag. NEW SESSION: run `/resume`.**
- **2026-07-12 (session 27 — Vision D Phase 1 via `/orchestrator`, Fable 5):**
  First real orchestrator outing — added the 4-expert roster (data-platform /
  webapp / dsp / llm-rag), then consulted webapp-expert + data-platform-expert
  IN PARALLEL for N1/N2 (webapp) and O1 (data-platform), disjoint files.
  ✅ **N1 + N2 SHIPPED (commit 1607f2d, 339 green, browser-validated 375px):**
  **N2** the 12-cell archetype taxonomy on /analytics with the user's cell pinned
  — the key move was lifting derive_archetype's inline breadth thresholds
  (0.70/0.85) into shared constants + `archetype_name()`, so `archetype_taxonomy()`
  derives every name/band/rule from the SAME source (journal #27; can't drift);
  **N1** plain-language σ/std/percentile explainers (accessible `<details>` +
  `<abbr>` glosses) on /analytics + /explore. ✅ **O1 DEFERRED (owner) — but
  FULLY PLANNED:** data-platform-expert's ready-to-execute plan is in
  VISION_SPECS §"Epic O → O1 READY-TO-EXECUTE" (new stdlib-only `dedup.py`,
  `TrackMeta.duplicate_of`+`duration_ms`, enqueue/extract guards, DUPLICATE_TRACKS
  audit, ~12 tests; real-corpus probe found **10 genuine dupes** → the flag will
  read true, advisory). Bridge key stays sacred (flag = soft ref, never a join).
  **Left off: Phase 1 = only O1 remains (execute the captured plan in one pass);
  then Phase 2 = MPD/Spark. NEW SESSION: run `/resume`.**
- **2026-07-14 (session 28 — O1 dedup via `/orchestrator`, Fable 5): PHASE 1 IS
  NOW 8/8 COMPLETE.** Built O1 from the captured data-platform-expert plan in 4
  committed sub-slices (57e8cb1 pure `dedup.py`+DUPLICATE_TRACKS audit · faa610f
  cache schema+guards · 2964cbf extractor/worker/script/feeders): stdlib-only
  `src/store/dedup.py` (normalize+union-find+reject-only cosine tiebreak,
  precision-biased); `TrackMeta.duplicate_of`(soft ref, never a join)+`duration_ms`
  (migration); enqueue intake guard + extract-time race guard; `refresh_dedup.py`
  + worker post-drain hook; feeders (app/seed_cache duration_ms); audit
  `check_duplicates`. **353 tests green** (+14). Deployed + activated live:
  `refresh_dedup` flagged **10 real dupe clusters** (Muse/Linkin Park/Green Day),
  warehouse-audit DUPLICATE_TRACKS=true (0 errors, only that flag), app-verify
  ALL-GREEN. Journal #28 (a z-scored cosine tiebreak is degenerate at n=2 — test
  population-relative code with a population). **Pruning the 10 dupes is an
  IRREVERSIBLE owner call (D-28 flag-not-delete) — not auto-done.** **Left off:
  Vision D Phase 1 COMPLETE; NEXT = Phase 2 (Epic J MPD metadata-only + Spark)
  or Phase 3 (Epic H `/songs`+worker-fallback, I playlists, K chat, L publish).
  NEW SESSION: run `/resume`.**
- **2026-07-14 (session 29 — Vision E design via `/orchestrator`, Fable 5):**
  Owner re-scoped the whole arc → specced as **VISION_SPECS §"Vision E — the
  product era" (D-32…D-39, commit a5298d0)**: Phase 3 = the product surface
  (P3.0 groundwork → P3.1 artist_meta → P3.2 Artists+genres → P3.3 Library
  tabs → P3.4 playlists → P3.5 guest dashboard → P3.6 H5/H6/O2 → P3.7
  case-study + PUBLIC-FLIP exit gate), Phase 4 = Epic K formal (chat +
  multimodal-upload builds; adapters/RL gated explorations), Phase 5 = MPD,
  Phase 6 = ML. Built 2 new harness agents (`research-expert`, `agile-coach` —
  both registered) and ran the first research outing →
  **`docs/SPOTIFY_API_RESEARCH.md`** (cited availability matrix + derivation
  map). **Load-bearing find (journal #29): `GET /artists/{id}/top-tracks` was
  REMOVED (Feb-2026 wave, "no replacement")** → artist pages derive "YOUR top
  by artist" as the core; live top-10 = absent-safe garnish (borrowed-time
  doctrine now standing). Also: 5-seat cap = platform ceiling; playlists
  own+collaborative only @50/page; search capped 10; guardrails file needs
  correction wave 2 (P3.0 task). webapp-expert delivered the IA (two-group
  six-item nav; Library holds the only tabs; genres live in Artists; guest
  lands on /dashboard; artist_meta = the genre serving path). Owner forks:
  analyze-on-demand · 50/range · flip = Phase-3 exit · K explorations gated.
  Spec-only session — no product code; suite stands at 353 (session-28 run);
  app-verify ALL-FALSE, 160 tracks, public up, tree synced. **Left off: Vision
  E COMMITTED; next build = P3.0 groundwork (fetcher hardening + 20→50 bump +
  guardrails refresh), then P3.1 artist_meta. NEW SESSION: run `/resume`.**
- **2026-07-15 (session 30 — P3.0 groundwork via `/orchestrator`, Fable 5):**
  Executed the researched plan directly (no expert fan-out — the plans WERE
  session 29's consults) in 3 committed sub-slices. **P3.0a fetchers (c8f2ce2):**
  shared `_artist_to_record` (absent-safe on the removed-fields list; captures
  artist `popularity` as fetched context); batch-`/artists` singles fallback
  (un-deprecated `GET /artists/{id}` @≥0.5s throttle); `_playlist_track_count`
  (`items.total`→`tracks.total`→0 — the old hard read contradicted its own
  comment); `_playlist_item_entity` (`item`→`track` alias); playlist pages at
  50; search clamped to 10; 6 new fake-sp/pure tests; 429 loop-hardening
  deliberately deferred to P3.4 (spotipy retries ×3 internally). **P3.0b
  (4748fb9):** `_TOP_LIMIT=50` extracted as THE single source (test asserts all
  3 ranges fetch at it) — D-34, the "why 39 songs" fix. **P3.0c (1b74f3c):**
  guardrails wave-2 rewrite (two-wave dating fixed, borrowed-time doctrine
  standing, artist-genres watch item, allowed-surface list with real limits,
  research-brief pointer). **359 tests green** (+6), deployed via restart
  (cache backed up @160), app-verify ALL-FALSE, live edge 200. The 50-bump
  proves itself on the owner's next real login (expect up to ~90 new tracks to
  queue — durable queue + O1 dedup absorb it by design). No journal entry —
  clean execution of a researched plan, zero surprises. **Left off: P3.0
  COMPLETE; next = P3.1 artist_meta foundation (table + migrations + seed
  script + dashboard persist), then P3.2 Artists surface. NEW SESSION: run
  `/resume`.**
- **2026-07-15 (session 31 — P3.1 artist_meta via `/orchestrator`, Fable 5):**
  Two sub-slices, no fan-out (the session-29 consult was the plan). **P3.1a
  (134f688):** `ArtistMeta` table (id PK, name/genres/followers/popularity/
  image/updated_at — every non-identity field nullable+absent-safe; stored copy
  = system of record) + `remember_artists` preserve-if-absent ("" never
  overwrites stored genres) + `all_artist_meta`; `track_meta` +=
  `album_image_url`+`primary_artist_id` (forward-only migration; the top-tracks
  record already carried both — previously dropped) threaded through
  `remember_meta`. **P3.1b (d4a01e3):** `_top_artists(client, cache)` persists
  the frame it always fetched (best-effort, never breaks the dashboard);
  `meta_items` carries art+primary-artist-id; `seed_artist_meta.py` run LIVE →
  **artist_meta: 60 artists, 29 with genres** (journal-#9 ceiling, now
  servable). **361 tests green** (+2), deployed via restart, app-verify
  ALL-FALSE, public up. No journal entry — second clean plan-execution in a
  row. **Left off: P3.1 COMPLETE — the Artists surface has its data
  foundation. Next = P3.2 (Epic P: /artists list + hover + comparison chart +
  genre chips; /artist/{id} deep-dive per D-33/D-35). NEW SESSION: run
  `/resume`.**
- **2026-07-15 (session 32 — P3.2 the Artists surface via `/orchestrator`,
  Fable 5; resumed across a cutoff):** Built Epic P's UI in 2 commits, no
  fan-out. **P3.2a (de5371b):** `src/webapp/artists.py` pure module —
  `primary_artist` (the clusters.py:170 rule, one source), `artist_rollup`,
  genre tokens/filter/strip (coverage honesty), `comparison_svg` (ranked bars,
  escaped names), `your_top_by_artist` (D-33 derived core), `nearest_artists`
  (z-scored acoustic centroids) + `fetch_artist_top_tracks` (borrowed-time,
  absent-safe, capped 10, country=None). **P3.2b (79824ca):** routes `/artists`
  (viewer; genre filter + chart picker) + `/artist/{id}` (base62-guarded;
  derived core + authed-only live top-10 w/ honest dark/guest captions +
  similar-in-library + analyze POST w/ server-side re-fetch) + templates +
  D-35 two-group nav + CSS; 7 route-matrix tests. **375 green (+14), deployed,
  app-verify ALL-FALSE; browser-validated LIVE on real data at 375px** — 15
  artist cards, genre chips (alternative rock 3 · punk 3), "Genres known for
  10 of 15", Muse deep-dive: 35/35 analyzed, 122 bpm avg/0.51 energy/0.70
  dance from OUR DSP, similar = Metric Δ1.46σ/Harry Styles Δ1.47σ/Foo Fighters
  Δ1.69σ, zero overflow. No journal entry (third clean plan-execution; the
  cutoff resume cost one import-restore). **Left off: P3.2 COMPLETE — the
  first Vision-E product surface is live. Next = P3.3 Library tabs (/library
  public + My songs + Playlists placeholder). NEW SESSION: run `/resume`.**
- **2026-07-15 (session 33 — harness v3: agent review + model routing, Fable
  5):** Owner asked which roadmap items need Fable vs Opus 4.8 Max, and to
  inject this arc's judgment into the agents. Reviewed every consult's
  performance (webapp 2/2 excellent — #27 catch + the IA; data-platform 1/1 —
  the 10-dupe real-corpus probe; research 1/1 — the two-wave find + a
  self-caught doc misread; dsp/llm-rag unused, lanes untouched; agile-coach
  unused → given a real job). **Shipped (commit 19fa411, docs+harness only, no
  product code — suite stands at session-32's 375):** every agent charter
  gains a tailored "How you think" block (probe-on-real-data · attack-your-own-
  plan w/ concrete failure scenarios · evidence classes · derive-don't-
  transcribe + tripwire tests · borrowed-time garnish rule · escalate
  irreversibles; per-lane: #28 n≥3 rule for dsp, injection-first + data
  go-gates for llm-rag, quote-targeted re-verification for research,
  gate-matrix + second-encoding hunt for webapp) + **`model: opus` pinned on
  all experts** (consults stop drawing Fable budget). **Model-routing table in
  VISION_SPECS** (owner rule: **Fable designs/decides/audits; Opus executes
  specced slices** — P3.3–P3.6 + L-lite = Opus; L-flip scrub, K0 design,
  injection evals, J modeling/benchmark judgment, new specs = Fable; O2
  threshold = split). agile-coach = routing keeper + standing P3.7 pre-flip
  review; orchestrator skill notes the agent-registration-latency fallback.
  **Left off: harness v3 in place. Next build = P3.3 Library tabs — an OPUS
  slice per the routing. NEW SESSION: run `/resume` (on Opus is fine).**
- **2026-07-15 (session 34 — P3.3 the Library surface via `/orchestrator`,
  Opus 4.8 per the D-40-era routing; no fan-out):** Built Epic H1 in 2 commits.
  **P3.3 (06da10d):** `cache.library_rows()` (read-only meta⟕features projection,
  kept OFF the 2-field `all_meta()` hot path) + `webapp/library.py` pure module
  (search name/artist · sort with unanalyzed Nones ALWAYS last — split present/
  missing rather than let `reverse=` flip the None flag · `annotate_dupes` "same
  recording as" · mine-overlay · `why_n_analyzed` derived from `_TOP_LIMIT`) +
  `/library` route (All songs PUBLIC · My songs viewer · Playlists authed
  placeholder) + `library.html` + `.tabs`/`.lib-table` CSS + nav Library for
  everyone (anon sees Library + Log in only). **Partial D-18 flip:** `/song` +
  `/spectrogram` flipped PUBLIC (both taste-free; `_TRACK_ID_RE` base62 guard,
  `_spectrogram_path` still traversal-safe; enumeration-oracle concern moot now
  the catalog lists analyzed tracks) + song.html back-links route anon→/library.
  **388 green (+13), deployed app-verify ALL-FALSE; anon browser-validated LIVE**
  — /library 160-of-161 real w/ dedup rows, /song full deep-dive (spectrogram/
  loudness/sections/radar/similar) all no-login, curl gate matrix: library/song/
  spectrogram 200 · /explore still 303. **Scope call → D-40:** the corpus
  builders (`_explore_context`,`_recommend_context`) `return None` w/o a taste,
  so blanket anon = a builder refactor, not a gate flip; shipped the taste-free
  two-thirds, deferred `/explore`+`/recommend` anon to a dedicated slice (D-40b,
  folds into P3.7). No journal entry (clean specced execution; the one snag was
  self-caught — the `{8,40}` artist regex rejected short synthetic ids). **Left
  off: P3.3 COMPLETE — the Library is live and public. Next = P3.4 (Epic I
  playlists, D-37; re-consent lands first). NEW SESSION: run `/resume`.**
- **2026-07-15 (session 35 — P3.4 Epic I playlists via `/orchestrator`, Opus 4.8;
  ONE webapp-expert consult, no other fan-out):** Built playlist import in 3
  commits. Consulted webapp-expert on the re-consent flow — it verified the
  granted `scope` already rides in `session["token"]` (no plumbing), caught a
  second-encoding bug (`privacy.html` hard-coded "one scope"), and flagged that
  `fetch_playlist_tracks(limit=)` is a PAGE size not a total cap. **P3.4a
  (30cb7b9):** `config` single-sources `BASE_SCOPES`/`PLAYLIST_SCOPES`/`SCOPES` +
  `PLAYLIST_IMPORT_CAP=100`; `auth_web.granted_scopes`/`has_playlist_scope`
  (derived, no 2nd copy); privacy copy renders scopes from config + discloses
  playlist access; scope-derivation tripwire test. **P3.4b+c (cccad88):**
  `webapp/playlists.py` (own+collaborative filter, fails-closed w/o /me id;
  `coverage_line`) + `/playlists` (authed: re-consent CTA vs cards) + `POST
  /playlists/{id}/analyze` (scope+membership gated BEFORE fetch → server-side
  re-fetch → **cap as a TOTAL via `ids[:cap]`** → remember_meta → enqueue O1;
  coverage via session flash, NOT a query param → XSS-safe) + Library tab wired.
  Owner calls (D-41): cap 100, membership=own+collab. **401 green (+13), ruff
  clean, deployed app-verify ALL-FALSE; anon gates curl-validated (playlists
  GET/POST→303 home), privacy discloses both scopes.** Journal #30 (the
  NaN-truthy bridge-key bug). **⚠️ Left off: P3.4 CODE COMPLETE but the AUTHED
  live path is unexercised — owner must re-login (grants the new scope) → open
  /playlists → Analyze a small playlist → watch /status. Adding scopes means all
  5 seats re-consent on next login. Next build = P3.5 guest dashboard replica.
  NEW SESSION: run `/resume`.**
- **2026-07-15/16 (session 36 — the field-report bug pass via `/orchestrator`,
  Fable 5; no fan-out — the logs held the evidence):** Jordan exercised the
  authed P3.4 path live (re-consent + real imports: 56 + 264-track playlists —
  the P3.4 loop is CLOSED) and filed 3 reports; the webapp log added a 4th.
  Diagnosis first, all from logs: ① `GET /nan` ×5 — coverless playlist →
  pandas NaN (truthy) → `<img src="nan">` (journal #30's class on the display
  path; isinstance-str in `playlist_cards`). ② his 264-track import capped to
  the first 100 rows INCLUDING analyzed ones → **skip-then-cap**: dedupe →
  skip `cached_ids ∪ active_ids` (new cache read) → cap the genuinely-new;
  coverage copy reports queued/skipped/held-by-cap. ③ "artists page gets
  stuck" — every artist-page GET live-fetched the top-10 garnish; spotipy's
  default 3-retries + Retry-After honoring slept renders on 429s from his
  heavy browsing → `client_from_session` retries=0 (all call sites already
  absent-safe) + a per-app 10-min memo for NON-EMPTY top-10s (dark not cached;
  memo on app.state, tests bust it). ④ **`/queue`** (the owner ask): running-
  first + claim_next's own requested_at FIFO (`cache.queue_rows()`), ~50s/track
  ETA, 30s self-refresh, public (library already shows "analyzing…" publicly);
  linked from playlists flash / library cells / artist caption. ⑤ Bonus:
  app-verify's QUEUE_STUCK false-alarmed on the healthy 48-deep backlog →
  re-semantics to progress-based (pending AND no updated_at movement; journal
  #31). Commits d88d173/0316cf9/74f12e4; **407 green (+6), ruff clean,
  deployed, app-verify ALL-FALSE (live: pending 36, progress_age 4.2s),
  /queue browser-validated on the REAL draining queue (48 tracks, Rise Against
  import, FIFO order visible).** Also observed: an app restart orphans the
  running job → `requeue_stale_running` reclaims in ≤15 min — existing design,
  now visible on /queue. **Left off: bug pass COMPLETE + pushed. Next build =
  P3.5 guest dashboard replica — an OPUS slice per the routing (switch off
  Fable). NEW SESSION: run `/resume`.**
- **2026-07-16 (session 37 — P3.5 guest dashboard replica via `/orchestrator`,
  Opus 4.8 per the routing; no fan-out — single-domain, file-level spec):**
  Built in 1 commit (3158f49) + spec (182d202). `guest_dashboard_context(prof,
  cache)`: the exact build_dashboard_context shape from snapshot ids + cache
  ALONE — per-range tracks (rank from list position, name/art/popularity from
  `library_rows`, ✓/hover-feat from features), artists joined to
  `all_artist_meta` for genres/images (P3.1's serving path earning its keep),
  absolute_profile + drift recomputed, coverage honest, analyzing=0. **One
  deliberate spec deviation (journal #27): snapshot schema UNCHANGED** — the
  spec said carry display fields in the JSON; deriving at render kills the
  "owner must re-snapshot after P3.1" ordering dependency and can't go stale.
  `/dashboard` branches authed→live / guest→replica / anon→home; `/guest` now
  lands on /dashboard; ask box authed-gated w/ honest caption; nav Dashboard
  for guests. **409 green (+2 — the replica test rigs fetch_top_tracks/artists
  to EXPLODE, proving zero API calls), ruff clean, deployed, app-verify
  ALL-FALSE, guest path browser-validated LIVE:** 117/117 analyzed, profile
  (126 bpm upbeat), drift 0.141σ "remarkably stable", 15 artists w/ genres,
  ranked per-range tracks w/ ✓, full guest nav. Public /guest 303s correctly.
  (Screenshot renderer in the Browser pane still hangs — text + a11y-tree reads
  used as proof, second session running.) No journal entry (applied #27, no
  new lesson). **Left off: P3.5 COMPLETE — Phase 3 build slices remaining:
  P3.6 (H5 fallback page + H6 landing copy + O2 yt-dlp hardening, Opus) then
  P3.7 (case-study + PUBLIC GitHub flip — FABLE, the exit gate). NEW SESSION:
  run `/resume`.**
- **2026-07-16 (session 38 — P3.6 H5+H6+O2 via `/orchestrator`, Opus 4.8; no
  fan-out — three small well-specced slices):** **O2 (0562601):**
  `resolve_youtube_match` — ytsearch5 candidates scored by title keywords +
  duration-vs-`duration_ms` bands (±3s +25 · ±10s +12 · ±25s 0 · ±45s −10 ·
  beyond −30; the wrong-version tell is DURATION, not titles); pure
  `score_candidate`/`pick_best_candidate` (offline tests); every match logged;
  `match_confidence` recorded per extraction (`_ADDED_COLUMNS` FLOAT,
  preserve-on-rewrite; AcquireFn → `(path, match)` + `duration_s`; `get_meta`
  += duration_ms). **Heuristic-v1 = selection+recording ONLY — no rejection
  threshold (corpus-evidence judgment, owner/Fable signs).** **H6 (486384f):**
  landing explains the three tiers (browse freely w/ /library + /queue links ·
  demo the experience · make it yours, 5-seat); demo tier disappears without a
  snapshot. **H5 (22f87e9):** `infra/cloudflare/origin-fallback-worker.js` —
  origin-down family (502/504/521-523/530 or fetch-throw) → an honest 503
  "runs on-demand" card w/ Retry-After; healthy origin passes untouched;
  /healthz + non-GET keep machine truth; node-syntax-checked; deploy doc =
  SELF_HOSTING §6a. **417 green (+8), ruff clean, deployed, app-verify
  ALL-FALSE; landing tiers browser-validated live.** Queue drained pre-restart
  so no live extraction has written a confidence yet — first real import will.
  **Left off: P3.6 COMPLETE — every Phase-3 BUILD slice is done. Owner steps:
  ① paste-deploy the H5 Worker (SELF_HOSTING §6a) ② sign the O2 weights once
  a real distribution exists. Next = P3.7 (case-study + PUBLIC GitHub flip)
  on FABLE — the exit gate; agile-coach holds the pre-flip checklist. NEW
  SESSION: run `/resume` on Fable.**
- **2026-07-16 (session 39 — P3.7 the exit gate via `/orchestrator`, FABLE per
  the routing; ONE agile-coach consult — its standing pre-flip review):**
  Owner decisions: MIT · genericize pilot names · gitleaks download approved ·
  scrub+force-push mine, flip his · aritzia email → live.com mailmap ·
  employer NAME stays in SPEC narrative. **Content:** sweep
  (PR_REFERENCE→legacy/, audioengineer→.agent_prompts/04) · MIT LICENSE ·
  README product-era pass + run-it-yourself · `docs/CASE_STUDY.md`.
  **Adversarial pass:** gitleaks 8.24.3 (owner-approved download) over 164
  commits → 3 findings = ONE rotated-dead secret (9b75…) in upload-era blobs;
  detect-secrets tree-clean; third-party email NOWHERE in history (verified).
  **agile-coach review = NO-GO with 3 real blockers** (employer email in
  commit METADATA — replace-text can't touch it, needed --mailmap · "Joey" a
  2nd unscrubbed pilot name · .gitignore missing the KB → re-add hazard) — all
  folded into ONE rewrite. **The scrub:** pre-scrub bundle to scratchpad →
  tree edits → `uvx git-filter-repo` (replace-text secret+names · mailmap ·
  --invert-paths KB) → **verification caught the secret ALIVE in two committed
  .pyc files** (original-upload `__pycache__`; bytecode carries the bytes a
  source scrub misses — journal #32) → pass 2 stripped ALL bytecode from
  history → full re-verify CLEAN (gitleaks "no leaks found"; value/name/email/
  KB/pyc greps = zero) → force-push (8024e3d→5d223c5, every hash changed —
  old citations are labels now). KB restored to disk from the bundle
  (filter-repo's checkout deletes newly-untracked dirs) — local-only,
  gitignored. **CI failed on a pre-existing test flake** (two same-name
  cookies in the jar, platform-dependent order — CI Linux served the stale
  guest sid) → `client.cookies.clear()` fix → **CI GREEN on the rewritten
  history.** 417 green local, app-verify ALL-FALSE (app restarted — owner had
  it off, on-demand). **Left off: P3.7 READY TO FLIP — the repo is
  publication-clean end to end. OWNER: ① flip public (GitHub Settings →
  Danger Zone) = Phase 3 EXITS · ② H5 Worker paste-deploy · ③ O2 weights
  sign-off later. Next build = Phase 4 / K0 design session (Fable). NEW
  SESSION: run `/resume`.**
- **2026-07-16 (session 40 — 🏁 THE FLIP + H5 deploy, Fable; owner flipped
  public, then "deploy the H5 worker for me"; includes a revert of a lost
  session):** Verified the repo PUBLIC anonymously (repo page + raw README
  200 logged-out) — **Phase 3 EXITED**; the webapp log already shows real
  anon traffic (crawlers on /song pages) + the usual wp-admin probe noise.
  **Cleanup (owner ask):** a lost session's commit `3a29328` (wrangler.jsonc
  + gitignore for a third-party skills download) reset away — main back to
  e384333, force-pushed; `cloud_flare_skills-main/` cleared from disk; the
  restored KB untouched. **H5 deploy:** dashboard path blocked at Cloudflare
  login (auth = owner's hands, always) → pivoted to `npx wrangler login`
  (owner clicked Allow; OAuth as jordan@vercilloanalytics.com) → deploy from
  a SCRATCHPAD config (repo stays clean per the revert): worker
  `origin-fallback`, routes apex+www. **Full loop verified live:** up =
  pass-through 200s + /healthz `{"ok":true}` · stop_app = the card (503,
  Retry-After 3600, "Demo offline — by design") · /healthz 503 JSON ·
  start_app = real app back. **Two edge behaviors probed live → worker
  hardened (784117d):** the tunnel's origin-down answer is a REAL 502/530
  HTML response (fetch doesn't throw), and **Cloudflare replaces a Worker
  502/504 response with its own error page** — the JSON must ride a 503
  (journal #33). A transient edge 500 on first /library curl = worker
  cold-start, self-resolved; a wrangler-version propagation lag briefly
  served the prior worker (wait-and-retest, don't re-deploy blind).
  app-verify ALL-FALSE. **Left off: PHASE 3 COMPLETE END TO END — public
  repo, live public app, fallback edge, case study. Next build = Phase 4 /
  K0 Epic-K design session (FABLE + llm-rag-expert). O2 weights sign-off
  stays open until real imports accrue. NEW SESSION: run `/resume`.**
- **2026-07-16 (session 41 — K0 the Epic-K design session, Fable; ONE
  llm-rag-expert consult per D-39):** The consult read rag.py/evalset/
  warehouse_agent/clusters + the KB cards and delivered per-phase eval
  designs, ctx budgets, the JSON-action tool loop, the K4 validation
  gateway, and countable K5/K6 gates — plus TWO real finds: the
  `force_fallback` harness hole and the missing-in-repo gemma4 baseline. I
  corrected its one over-reach (per-user warehouse isolation as a K2
  blocker — dissolves under D-18: the warehouse IS the owner's public
  corpus; session taste never enters the sandbox). Owner interview locked 4
  calls → **D-42…D-46 written into VISION_SPECS §Phase 4** (K1 viewer-gated
  chat probe-first → K2 tool-use SHIPS gated → K3 additive bucketing → K4
  uploads 20MB/10min/10 + `up`+hash id → K5/K6 docs-only). **K0 exit items
  shipped:** harness fix + tripwire (418 green, ruff clean; journal #34) ·
  the first dated baseline artifact (`evals/runs/`, gemma4:12b **9/15**,
  anchors in-run, cold-load timeouts visibly falling back = deployment-
  honest). Commits: K0a harness · c4f85ca plan · aa0de7c baseline; pushed.
  **Left off: K0 COMPLETE — Phase 4 is specced and calibrated. Next = K1
  probe (Opus): raw-call ~20 chat turns against live gemma4 BEFORE building
  session machinery. NEW SESSION: run `/resume` on Opus.**
- **2026-07-17 (session 42 — the K RESET: "Talk to your data", Fable; 2
  parallel consults + owner interview):** Owner reset Epic K's product frame:
  an on-demand music data analyst (story + adhoc), gemma4-ONLY, every
  prompt+response logged → review sessions, RTCROS contract, and a concrete
  data-first semantic layer before chat. Created **`chat-analyst-expert`**
  (D-50) — its FIRST OUTING delivered the D-47/D-48 drafts + the baseline
  autopsy: of gemma4's 6 failures only 3 are prompt failures; 2 are CONTEXT
  (motion/breadth never rendered — the model can't cite what it never saw)
  and 1 ROUTING (LLM called on empty context); and the committed 9/15
  OVERSTATES (2 classify "LLM" grades were fallback output after cold-load
  timeouts → re-baseline w/ per-case sources first). **data-platform's probe
  changed the design (journal #35): the corpus is 796 live tracks (6.8×
  since the flip) and the planes DIVERGED** — warehouse_agent reads the
  Jul-4 star schema (118) while cache/marts serve 796 → the chat would
  contradict itself across two turns; the semantic layer sources from the
  CACHE and the ad-hoc engine repoints; the star schema stays as the batch
  showcase. Also surfaced: clusters 39% coverage, 2 broken extractions
  poisoning superlatives (audit RED today, named cause), NO-embeddings
  retrieval decision (SQL + entity cards; FAISS owns similarity). Owner
  locked: log-all + disclose + 90-day (graded rows kept) · gemma4-only
  confirmed (ship narrower, never hosted). **Spec rewritten (89d0b83):
  D-47…D-50 + both hosted clauses removed + build order resequenced (K0.5
  data floor FIRST → K1 probe → K1.5 flywheel → K2 → K3 → K4 → K5/K6).**
  418 tests stand (docs+charter-only session). **PLUS (same session, owner's
  QA note + screenshots): Phase 4.5 specced (fc0de32, D-51…D-54)** — Epic Q
  acquisition provenance & QA (`track_provenance` captured AT extraction ·
  /song source-transparency + /library glyphs · the D-47-pattern QA review
  loop · **D-52 FULL 796-track re-extraction, owner: "no patchwork —
  consistency and standards"**, schema-first, non-destructive, ~11 h) and
  Epic R Artists 2.0 (MusicBrainz spine + Spotify garnish, mbid = attribute
  never key, on-demand+cache-forever; /artist profile 2.0 w/ discography;
  dashboard top-artist cards → links, ships early). Facts grounded first:
  the YouTube URL was NEVER stored (796/796), 497 have O2 confidence;
  `GET /artists/{id}/albums` survived the deprecations (10/page). Entry:
  after Epic K; Q before R. **Left off: the reset + phase-2 are specced end
  to end. Next = K0.5 the data floor (Opus; owner ratifies the 2
  broken-track re-extracts — note D-52 will re-extract everything anyway,
  so K0.5 may just dead-letter them). NEW SESSION: run `/resume` on Opus.**
- **2026-07-17 (session 43 — K0.5 the data floor, Opus 4.8 executing the
  specced slice; no fan-out — the 2 consults' file:line designs carried it):**
  Built the first "Talk to your data" BUILD slice in 2 commits.
  **7f12daf (eval honesty + grounding/routing fixes):** `format_report` prints
  per-case source + a "by source" line (the K0a-era 9/15 HID 2 classify
  timeouts graded on fallback); `_grounding_text` renders archetype
  motion/breadth (the C11/C12 context failures — the model couldn't cite what
  it never saw); `answer()` short-circuits an empty context to the
  deterministic fallback (A04 routing); `num_predict=1024` caps gemma4's
  thinking (the timeout mechanism). New dated artifact: **gemma4 9→13/15,
  honestly** (7 passes fallback, gemma4's own record 5/7, A01/A05 must_cite
  left for D-48's RTCROS reorder). **5584750 (the D-49 semantic layer):**
  `src/store/semantic.py` — feature_dictionary (rule-3 popularity caveat as a
  ROW), track_card (feature_valid gate: tempo>1 ∧ loud>−80, broken rows
  survive but are excluded from superlatives + percentile ranks), artist_rollup
  (by `primary_artist_id`; widened `library_rows` to carry it); wired into
  `rebuild_marts` (post-drain, reuses the perceptual frame, no recompute); the
  4 named tripwires ship as `test_semantic.py`. **Built LIVE on the 796-track
  cache: 796 track_cards (plane-coherent), 299 artist_rollups, the 2 broken
  tracks (Aftermath/Muse, Q&A/Drake) correctly gated invalid.** 425 tests
  (+7), ruff clean, deployed, app-verify ALL-FALSE, /library 200 (widened
  read). Broken extractions: feature_valid gate is the interim fix, D-52
  re-extraction the permanent one (no prod mutation — owner's call). **Left
  off: K0.5 data floor SHIPPED; cluster_profile + ad-hoc-repoint deferred
  (not blocking). Next = K1 probe → the RTCROS contract (D-48, fixes A01/A05)
  → /chat + ChatLog. NEW SESSION: run `/resume` on Opus.**
- **2026-07-17 (session 44 — K1 probe + the RTCROS contract, Opus 4.8; probe
  first per journal #25):** Built `evals/probe_chat.py`, ran the RTCROS draft +
  multi-turn + story against LIVE gemma4:12b, READ the transcripts (af7ba68).
  The probe fought my gut: the cited-before-answer reorder is NOT a silver
  bullet (A01 2/3, A05 1/2), gemma4 paraphrases even INSIDE cited[] (hallucinated
  "statement" for "sounds"), multi-turn holds ~3 turns but went EMPTY on an
  unanswerable Q, and STORY MODE is its strongest surface. Built
  `prompt_contract.py` (ed84869): ONE RTCROS encoding (classify's inline
  duplicate retired), `verify_citations` (checks cited[] against the grounding —
  drops hallucinations, forces claimed-but-unsaid via ONE retry),
  `is_empty_reply`→fallback (fixes the blank T4), PROMPT_VERSION; rag rewired
  through a shared `_grounded_reply`. **THE re-baseline finding (journal #36):
  9/15, DOWN from a timeout-inflated 13 — the contract made gemma4 ATTEMPT 8
  ask cases instead of timing out to the verbatim-perfect fallback, exposing
  that gemma4 paraphrases labels (no_invention 15/15, faithful). Its adhoc
  must_cite ~57% is below the 80% gate; STORY + classify are its strengths.**
  The gate did its job = decided scope. **Owner confirmed: /chat is
  STORY-LED**, adhoc w/ honest fallback, flywheel lifts adhoc. 431 tests (+6
  contract), ruff clean. No deploy (no route yet). **Left off: K1 probe +
  contract done; the eval honestly says story-led. Next = K1c the story-led
  /chat + D-47 ChatLog (the big slice). NEW SESSION: run `/resume` on Opus.**
- **2026-07-18 (session 45 — K1c the story-led /chat + D-47 ChatLog, Opus 4.8;
  no fan-out — the consult's schema carried it):** Shipped Epic K's chat in 2
  commits. **fbf0c81 (the ChatLog spine):** `ChatLog`+`ChatLabel` tables
  (house style, create_all — no _ADDED_COLUMNS, journal #18),
  `cache.log_chat_turn`/`recent_chat_turns`; rag.answer/classify now return the
  rendered grounding + raw model output; `/ask`+`/classify` log from day one via
  a shared `_log_turn` (chat_session_id = per-session uuid, never the auth sid);
  `/privacy` rewritten to disclose logging + 90-day retention (the old "nothing
  retained" line was now false). **7c649f2 (the surface):** `TasteRAG.story()`,
  viewer-gated `GET /chat` (story opening, cached per session) + `POST /chat`
  (PRG adhoc), ~20-turn drop-oldest history, chat.html + Chat nav + CSS.
  **Live gemma4 debugging (journal #37) burned real budget but found the truth:
  (1) gemma4 returns EMPTY when the user turn is just `<data>` with no
  instruction → a "REQUEST: …" directive fixes it; (2) it chokes on nested
  `{story:[...]}` JSON → story is the FLAT answer field; (3) it's INCONSISTENT
  (same config, sometimes a clean story, sometimes empty) + slow (~25-50s, pads
  to num_predict).** So the deterministic fallback is the reliability backbone
  (D-5); gemma4 enhances when it succeeds. 436 tests (+6), ruff clean, deployed
  ALL-FALSE, curl-validated live (guest conversation renders story+Q+grounded
  "Muse" answer; all turns logged). **Left off: story-led /chat + logging LIVE.
  Next = K1.5 the review flywheel (`review_chat_logs.py` + first review session)
  → K2. NEW SESSION: run `/resume` on Opus.**
- **2026-07-18 (session 46 — K1.5 the review flywheel, Opus 4.8; no fan-out —
  the chat-analyst consult's design carried it):** Built the D-47 flywheel in
  1 commit (365d929). `src/webapp/chat_review.py` (pure): `stratified_sample`
  (8 story-llm/8 adhoc-llm/4 fallback, deterministic, thin strata never block),
  `pre_grade` (suggests only the machine-checkable dims — citation_fidelity +
  invention via `verify_citations` over the row; accuracy/usefulness stay
  human), `render_worksheet` (every field html-escaped — log text is
  untrusted), `aggregate`/`format_report` (rubric means by mode/source, verdict
  counts, the `k5_eligible` counter → D-46's 200-500). `cache.ungraded_chat_turns`
  (rows without a ChatLabel) + `write_chat_label` + `all_chat_labels`.
  `scripts/review_chat_logs.py`: `--sample` (gitignored worksheet) / `--commit`
  (human grades → ChatLabel) / `--report` (aggregates-only dated `evals/runs/`
  artifact — raw user text NEVER leaves the gitignored DB, rule 7). **Ran live
  on the 23 real logged turns: --sample wrote a 20-card worksheet (a real
  gemma4 answer "Your vibe is bright indie." pre-graded), --report produced the
  artifact (0 graded — honest, the first human session fills it).** 441 tests
  (+6), ruff clean, worksheet gitignore-verified. No journal entry (clean
  specced execution). **Left off: the flywheel is BUILT + demonstrated on real
  data; the first HUMAN review session is the owner's next step. Next build =
  K2 (injection evals FABLE → tool-use loop). NEW SESSION: run `/resume`.**
- **2026-07-21 (session 47 — K2 the "Talk to your data" tool loop, Fable +
  orchestrator; 7 commits d36cf49→6a5dce1):** Opened by benchmarking local
  models for the /chat surface — gemma4:e4b (owner's multimodal pick) vs qwen3:8b
  vs gemma4:12b on the golden set; e4b 9–11/15, qwen3:8b 13/15. Built K2 end to
  end via /orchestrator: probe (GO) → 2 marts + 3 audit tripwires → grounding
  sanitizer → `chat_tools.py` engine → the flat-action `_tool_loop` → the
  injection eval set → the gates. **The gates did their job:** the injection gate
  caught gemma4:e4b OBEYING a token-injection 4/4 runs (a real 4.5B limit), so
  the owner CHOSE the split — qwen3:8b (defends 5/5 × 6 runs) drives the
  security-sensitive tool loop, e4b stays multimodal + story/classify — and per-
  surface routing shipped (`WEBAPP_TOOLS_LLM_MODEL`). Three real surprises
  (journals #38 the NAMES-FIRST mislabel, #39 the quoting-vs-obeying grader
  artifact, plus #34 recurring — the tool loop's env route re-opened the CI guard
  hole, fixed with a conftest that neutralizes all routes). The owner's original
  bug — "top rise against songs" → generic non-answer — is FIXED: the live tool
  loop returns real Rise Against tracks (depth=2). 472 tests (+31), ruff clean,
  CI green, all K2 work committed + pushed. Cleared an orphaned truncated
  `injection_evals.py` from the recovered session. **Left off: K2 is 7/8 slices
  DONE (probe/K2.0/K2.1/K2b/K2c/K2a/K2d), injection gate PASSES on the shipping
  split, owner bug fixed. NEXT = K2e: deploy via `app_control restart` (picks up
  the split .env) + live browser validation on /chat. NEW SESSION: run
  `/resume`.**
- **2026-07-22 (session 48 — K2e: deploy + live validation, Fable +
  orchestrator):** Reconciled the owner's recovered session-47 transcript
  against the repo — all 7 slices + the wrap are REAL at bdbbeef, nothing to
  redo ("re-run the probe" was stale; the probe's GO is committed d36cf49).
  App found DOWN (PC reboot; on-demand runtime) → `app_control start` brought
  webapp+worker+tunnel healthy; dual warm-up proven (qwen3:8b 6.2 GB + e4b
  3.3 GB co-resident 100% GPU, 8K ctx). **THE ACCEPTANCE PASSED LIVE** through
  the public edge as guest: "what's my top rise against songs" → real Rise
  Against tracks; ChatLog id 70 (source=llm, model=ollama:qwen3:8b, depth=1,
  87.7s); app-verify ALL-FALSE. **Epic K2 closed 8/8.** No code changes; no
  journal entry (clean deploy + validate). **Left off: K2 COMPLETE and live.
  NEXT = (owner) the first review session; (build) K3 bucketing → K4 upload.
  NEW SESSION: run `/resume`.**
- **2026-07-22 (session 49 — K3 grounded cluster descriptions, Fable +
  orchestrator; 7 commits b5eefd0→edcecd3, 488 tests):** One llm-rag-expert
  consult (its finding — the mart can't reconstruct the naming dims — became
  K3a, journal #40), then built K3 in commit-per-slice order: label_dims at
  training time → the `cluster` RTCROS mode + describe_cluster (name pinned,
  zero-injection grounding) → golden_clusters_v1 + 4 graders ($0 CI guard) →
  offline persistence + mart projection (model row is truth) → /analytics
  blurbs + honest caption. **The gates caught two real defects before users
  saw either:** e4b describing a bucket by CONTRAST (→ the opposite-pole
  guard, journal #41; re-run 10/10) and the pre-K3a live model wearing the
  false "Mixed" template (→ label-word templates). Deployed + guest-validated
  through the edge; app-verify ALL-FALSE; audit semantic flags false. Owner
  decisions recorded: QA deferred until real testers; the cluster retrain is
  the K3-value unlock (e4b prose activates on first post-K3a retrain).
  **Left off: EPIC K3 COMPLETE. NEXT = K4 multimodal upload (D-45, Fable
  security review first). NEW SESSION: run `/resume`.**
- **2026-07-22 (session 50 — cluster retrain + 4 shelf items, Opus +
  orchestrator; commits b5eefd0→…, 491 tests):** Owner handed a batch: retrain
  the frozen Jul-11 clusters + clear O2/task#9/`/chat`-UX/DMARC. **Retrain:**
  coverage 39%→99.7% (805 tracks), silhouette 0.146→0.172, new buckets
  Punchy·Smooth/Gentle·Noisy — the electronic imports finally cluster apart
  from the rock core; the K3 machinery produced real e4b prose (after the
  jargon guard, journal #42). Pre-flight caught that training had no
  feature_valid gate (the 2 broken extractions would skew it → `_drop_broken`).
  **The 4:** S1 review-pool filter for synthetic 0 ms llm rows (36/41 were
  junk); S2 O2 signed off context-only (low-confidence tail = legit electronic
  remixes, a threshold would gut the genre); S3 `/chat` pending-state
  (progressive enhancement); S4 DMARC verified quarantine, reject-flip deferred
  to owner (11 days, want 14+; owner's DNS). Deployed, guest-validated through
  the edge, app-verify ALL-FALSE. **Left off: batch COMPLETE. NEXT = K4
  multimodal upload (switch to Fable for its security review). NEW SESSION:
  run `/resume`.**
- **2026-07-22 (session 51 — the D-55 re-sequence, Fable + orchestrator +
  agile-coach; commit 41f3c89, docs-only):** Owner asked whether K4/K5/K6
  could wait behind a working prototype as an "LLM phase 2." One agile-coach
  consult sharpened the lead's draft in three places: K4 is APPETITE-gated,
  not welded to K5/K6's D-46 data gate; never launder "Epic K complete" —
  amend Phase 4.5's entry criterion instead; K5/K6 builds stay single-homed
  in Phase 6 (Phase LLM-2 = K4 only). Owner ratified all five open items →
  D-55 encoded in VISION_SPECS: Phase 4 closes honestly (chat scope K0–K3
  shipped), Phase 4.5 OPEN, the "working prototype" DoD now gates Phase 5,
  the stale e4b-multimodal split note corrected, routing rows added for Q/R
  (Opus; Q3's ~11h batch plan Fable-signed). No code changed; verification
  stands from session 50 (491 green, ALL-FALSE). No journal entry (design
  session, no surprise). **Left off: roadmap re-sequenced, spec + hub
  aligned. NEXT = Phase 4.5 slice Q1 — track_provenance capture (Opus).
  DMARC reject-flip is the owner's ~Jul-25 item. NEW SESSION: run
  `/resume`.**
- **2026-07-22 (session 52 — Phase 4.5 Q1, Fable + orchestrator; commits
  Q1a→Q1b, 496 tests):** Built D-51 provenance capture in two reviewable
  slices, no consult (warm context — the K3a/K3d table/mart/migration/audit
  patterns were fresh). Q1a: the yt-dlp matcher already knew the video id,
  channel, yt-duration, candidate count, query + matcher version and threw
  them away — `pick_best_candidate`/`resolve_youtube_match` now carry them
  (additive), `extract_one` appends one `track_provenance` event per
  extraction (best-effort, not on the dedup-twin path). Q1b: the
  current-per-key Parquet mart + the `PROVENANCE_ORPHAN` tripwire
  (under-coverage is a NOTE, not a flag — the pre-Q1 corpus is ∅ until Q3).
  Honest live state: 807 tracks, 0 provenance events (all pre-Q1) → empty
  mart, audit green; capture proven on the real DSP path by synthetic test.
  Found the app DOWN at wrap (on-demand, long session) → restarted,
  ALL-FALSE, public site restored. No journal entry (clean specced
  execution). **Left off: Q1 shipped, verified. NEXT = Q2 — expose
  provenance on /song + /library (escape the external strings). NEW SESSION:
  run `/resume`.**
- **2026-07-22 (session 53 — Phase 4.5 Q2, Fable + orchestrator; 501 tests):**
  Exposed D-51 provenance on /song (a "Source & provenance" card) + /library
  (a Src ✓/~/∅ glyph column + legend) in three slices, no consult (warm
  webapp context + the XSS fix is known: Jinja auto-escapes, so external
  strings are safe as long as nothing `|safe`s them). `cache.provenance_for`
  + a glyph folded into `library_rows`; the youtube_url is scheme-guarded to
  http(s) (no `javascript:` links) and the untrusted title/channel render
  auto-escaped — both regression-tested (a `<script>` title renders inert).
  Live ∅ tier validated on both surfaces through the edge (all 807 tracks are
  pre-Q1 — populated cards activate on Q3). No journal entry (clean specced
  execution; the auto-escape default made the flagged XSS risk a non-event).
  **Left off: Q2 shipped, verified. NEXT = Q3 — the D-52 re-extraction program
  (Fable signs the batch plan first). NEW SESSION: run `/resume`.**
- **2026-07-23 (session 54 — Phase 4.5 Q3, Fable + data-platform red-team;
  513 tests):** Signed the D-52 batch plan, red-teamed it, built the runner,
  proved it live. The red-team probed the live DB and found **3 verified
  ship-blockers in a plan the author had already self-checked** (journal
  #43): the shared `.tmp` mart-rebuild collision (F1 → per-pid tmp), the
  preserve-on-None merge that becomes cross-source contamination on
  re-acquisition (F2 → `upsert(replace_display=True)`), and the CLI's
  audio_dir violating the plan's own raw_audio rule (F3 → scratch dir +
  sentinel test). `src/store/re_extract.py` + `scripts/re_extract.py`
  (atomic-swap-on-success, provenance-verified resume marker, durable
  provenance-wins ledger, still-broken→flag-not-dead-letter, 796-canonical
  scope, 3-tier value-first order); 12 invariant tests incl. the F1/F2/F3
  catchers. **The dry-run (--limit 3, 57 s) HEALED the 2 permanently-broken
  extractions** — Q&A 0→129.2 bpm, Aftermath 0→143.6 bpm (official Muse
  video, Δ0.003 s), the provenance card live on the public edge, and
  FEATURE_DISTRIBUTION's breakage warnings gone (only the documented DJ-mix
  duration tail remains). Coverage note now 3/796 canonical (red-team #6).
  **Left off: Q3 READY — the full ~12-16 h `--all` run is the OWNER's to
  schedule (interrupt-safe, resumable); its completion checklist is printed
  by the runner. Next build slice = Q4 `review_provenance.py`. NEW SESSION:
  run `/resume`.**
- **2026-07-23 (session 55 — O3 duplicate consolidation, Fable +
  data-platform red-team; commits ce8fc9a/604fb3e/5d1d26b, 525 tests):**
  Owner un-parked dupe consolidation ("same track in multiple albums shows
  twice"), ratified 4 calls, and the journal-#43 discipline paid again: the
  red-team probe found guests DOUBLE-COUNTING 10 twins live since P3.5
  (four range_ids producers, the draft named one), the F-class
  compute-vs-TABLE divergence (merge-only persistence would keep serving
  twin rows to /explore+/recommend), a forward-reachable PROVENANCE_ORPHAN
  false-fire, and a missing authoritative twin set for the standalone
  audit (journal #44 — a flag nobody consumes is documentation, not
  protection). Shipped consolidation as a READ-TIME view: one filter
  (`cache.twin_ids`), one canonicalizer (`canonicalize_ids`) at all four
  producers, canonical-only marts/training/similar/populations, the
  duplicate_flags mart + TWIN_LEAKAGE tripwire, /library collapse w/
  chip + alt_names search + ?dupes=all, twin /song banners. Live: 796
  unique of 807; Unravelling 1 row; all audit flags false. O3b commit msg
  says 530 — truth 522 (miscount). **Left off: O3 COMPLETE and live. NEXT
  unchanged = (owner) the Q3 `--all` full run — its post-run retrain now
  materializes twin-free training too; (build) Q4. NEW SESSION: run
  `/resume`.**
- **2026-07-23 (session 56 — the full D-52 run + two mid-flight traps +
  D-56, Opus → Fable; commits 3d1c38a→2779a13, 542 tests):** Owner said go;
  launched detached w/ backup + a status script. **The spot-check found the
  run reproducing garbage 4 min in** (journal #45): the DJ-set trap (never-
  reject ranking → a 2-h set for a 3.5-min song, 19 queued; stopped, duration
  guard, relaunch) then at 71 swaps the wrong-SONG trap (duration +25 with
  no title requirement → 7 confirmed wrong songs; stopped, title-affinity
  gate w/ the live failures as test fixtures, relaunch — healthy, guards
  firing, ~24% at wrap, ledger 33 = the repair queue). **Mid-flight the
  owner specced D-56** (paste-a-link + upload-own-audio for unfindable
  tracks, e.g. Roots by WILDS; ratified owner-only + hard-reject + build
  now): engine (SSRF allowlist, magic bytes, streamed cap, ffprobe
  pre-decode, Q3 swap discipline, manual provenance) + surfaces
  (needs-source library tab, /song repair card), FAIL-CLOSED verified live
  (env unset — owner adds WEBAPP_OWNER_SPOTIFY_ID). Known follow-up: the
  live worker still lacks both guards (how the 19 got in). **Left off: run
  HEALTHY mid-flight (~4-5 h at observed pace); D-56 deployed fail-closed.
  NEXT = owner env var → run finishes → post-run checklist → drain the
  repair queue; build = Q4. NEW SESSION: run `/resume`.**
- **2026-07-23 (session 56 cont'd — verify-links, repair hardening, D-57 +
  the QA brief; Opus + Fable; 555 tests):** Made provenance clickable
  (library glyph → the exact recording), retained owner uploads with
  owner-only playback, and **found five live bugs by actually using the
  feature** — the Anaconda-ffmpeg shadow that killed every repair (my first
  fix only DETECTED it, journal #47), repairs leaving stale derived planes,
  the 20 MB cap blocking lossless masters, the D-57 gate hiding the repair
  tools it should expose, and a headline-vs-section tempo label collision the
  owner spotted (117 vs 112 on identical audio). **D-57 (owner call): no
  verified source → no features shown**, anywhere (46 tracks), with the
  repair path as the way to reveal them. Repaired 2 tracks live incl. a
  29.6 MB WAV master. Wrote **`docs/QA_PLAN.md`** — the full bug/QA brief for
  the next session (8 fixed bugs w/ regression checks, 7 ranked open items,
  a proposed 4-slice Q4). **Left off: corpus 770 analyzed / 724 validated /
  46 withheld / 72 needs-source; app healthy. NEXT = Epic QA per
  docs/QA_PLAN.md — start with QA1 (qa_audit.py), then B1 (the live worker
  still lacks BOTH acquisition guards — highest-value open bug). NEW SESSION:
  run `/resume`.**
- **2026-07-23 (session 56 cont'd — Q3 closed + verify-links + DQ quarantine,
  Opus + Fable; commits 871d000→228b7ad, 548 tests):** The full run finished
  (750 swapped, 96% clean). Built V1+V2 (verifiable provenance: clickable
  source links proven live, owner upload-retention + owner-only playback);
  hardened the D-56 gate (self-diagnosing + case-insensitive; owner id
  `jordan_vercillo` set). Then a data-quality pass: the run's pre-gate swaps
  had locked in 27 wrong-song acquisitions via the resume marker (journal
  #46) → `quarantine_wrong_songs.py` (detection reuses `title_affinity`,
  dry-run-first, backup) cleared all 27 into the needs-source queue, bridge
  key kept. Finish: retrain on 770 CLEAN tracks → archetype shifted once
  (Anchored→Drifting Loyalist, ratified D-55) → full audit clean (0 tempo-0,
  broken extractions stay healed). Needs-source queue = 73 for owner repair.
  **Left off: Q3 fully CLOSED and verified; corpus clean; the app serves
  clickable-verifiable provenance. NEXT = (owner) drain the 73-track repair
  queue at leisure; (build) Q4. Recommended: adopt the acquisition guards in
  the live worker. NEW SESSION: run `/resume`.**
- **2026-07-24 (session 57 — Epic QA: QA1/QA2/B1/B2 + drain + CI + docs, Opus
  + agile-coach consult; commits c7ad7ad→eb1ed37, 579 tests, CI green):**
  Owner ratified both open decisions (B1 adopt, B2 exclude). **Measured the
  guards before building: the Q3 gates still admitted 4 wrong songs in 11**
  (journal #48) → one shared `match_gate` (title containment, leading-artist,
  two-sided duration, reproduction markers), **filter-then-rank**, and
  `default_acquire` (the live worker — the path with NO guards) now delegates
  to it (QA2/B1). **Drain 72→65 converged** (channel-verified bar; 7 repaired,
  each hand-verified; 44 have no findable source — the honest floor); found the
  full-credit-vs-primary search divergence en route (journal #49). **B2:**
  `excluded_from_aggregates` = twins | unvalidated; corpus 771→731 aggregate,
  retrain silhouette 0.172→0.174, archetype UNCHANGED; fail-safe = no
  provenance rows → exclude nothing (journal #50). **QA1** `scripts/qa_audit.py`
  (9 checks, exit-1; live 0 failed/7 passed/2 notes; provenance coverage of the
  aggregate corpus = 100%). **CI had been RED 12 commits** on a cookie-jar
  duplicate that passed locally (journal #51). **The honesty pair:** /library
  "no source" vs "analyzing…" for dead-letters + D-54 dashboard→/artist links.
  **DoD ⑥:** README + case study refreshed (two-plane framing for the frozen
  gold plane; provenance spine as case-study §3). agile-coach consult corrected
  a stale fact: Phase 4.5 also holds Epic R (unbuilt, no deferral); D-55 DoD is
  4/7. **Left off: Epic Q is 9/10 (QA3 remains); app-verify ALL-FALSE, audit
  clean but for the 2 documented advisories, tree synced. NEXT build = QA3
  `review_provenance.py`. THREE owner decisions gate the Phase-4.5 exit: Epic R
  defer-or-build · DoD ④ fix-the-audit vs accept B4 · B5 exporter-vs-freeze.
  NEW SESSION: run `/resume`.**
- **2026-07-24 (session 58 — QA3 + the Phase-4.5 EXIT: Opus + data-platform
  consult; commits 12ae966/914f76b/cd9dfb9/601e0ac/c1c91f9, 597 tests, CI
  green, both audits clear):** Shipped QA3 (the provenance-health flywheel;
  journal #52 — a strict WRITE gate reused as a health VERDICT cried wolf, 69
  false-positive "review" rows → 7 real via `title_recall`). Owner ratified the
  three exit decisions; recorded them (D-58 Epic R deferral satisfies DoD ③).
  Then the two audit slices: **D-59** probed B4 and found the "6 legit DJ mixes"
  assumption was never verified and WRONG — one bad row (TTPD, a 2 h source that
  slipped the guard on Spotify duration=0); quarantined it + hardened
  `implausible_duration` (unknown-length cap) rather than loosen the audit
  (gate-masking violates ④) → FEATURE_DISTRIBUTION cleared. **D-60** built the
  cache→gold exporter (Design 2: unify the CATALOG to 730; leave the drift
  plane's per-user grain alone — reproducing it would fabricate ranks) →
  DUPLICATE_TRACKS cleared + `GOLD_PLANE_STALE` agreement check. **Left off:
  🏁 PHASE 4.5 EXITED — all 7 D-55 criteria met, warehouse ALL FLAGS FALSE,
  qa_audit 0-failed, 597 tests, tree synced. App on-demand (was down — data-only
  work, verified by audits). NEXT = Phase 5 (MPD/Spark); FIRST verify the AIcrowd
  MPD dataset + license (research-expert) before committing the phase. NEW
  SESSION: run `/resume`.**
- **2026-07-24 (session 59 — Epic O4 + QA-2, Opus + orchestrator):** owner asked
  for aggressive duplicate consolidation + a full feature-validation QA run.
  Consulted `data-platform-expert` and `webapp-expert` in parallel; both
  red-teamed their own plans and each found a ship-blocker. **O4 inverted the
  dedup doctrine** (versions split, releases merge) after measuring that the old
  rule was right only by ACCIDENT — see journal #54. Live: 730→728 canonical,
  exactly the pre-measured diff; the twin-un-stranding fix proved itself on real
  data. **QA-2 built the route matrix** (28×4 with a side-effects column),
  closing 17 blind gate cells and fixing two real bugs (`/guest` session hijack,
  `/openapi.json` exposure), plus the dedup golden set and a scripted public
  smoke (14/14 live). CI caught a machine-dependency in the matrix itself
  (journal #55). **Left off: 771 tests, ruff clean, warehouse 20 flags ALL FALSE,
  qa_audit 0-failed, live smoke 14/14, app UP and redeployed onto current code,
  browser-validated. NEXT is unchanged = Phase 5 (MPD/Spark), starting with the
  AIcrowd dataset + license check (research-expert) before committing the phase.
  Owner track, at leisure: the ~65 needs-source queue; the one O4d disagreement
  (Muse "Won't Stand Down") is a D-56 repair, not a dedup decision. NEW SESSION:
  run `/resume`.**
- **2026-07-25 (session 60 — DQ wrong-take, Epic I uncap, the perf pass; Opus +
  orchestrator):** owner ran the app hard and reported five bugs; consulted
  data-platform + webapp in parallel on performance, both red-teaming their own
  plans. Shipped: the 34-track wrong-TAKE quarantine (a class no existing check
  could see — journal #56's sibling finding), the dead-letter repair-queue gap
  (journal #57), whole-playlist import + /queue landing + honest queue counts +
  per-playlist coverage + Queue nav tab, the sticky-demo login fix, and the perf
  pass (journal #56): `/library` **120 ms → 16 ms and 757 KB → 64 KB (now
  constant in corpus size)**, `similar()` **176 ms → 7.7 ms**. **Left off: 803
  tests, ruff clean, CI green, both audits clear, live smoke 14/14, app-verify
  ALL-FALSE, deployed and browser-validated at 375px. Corpus is GROWING fast
  (1,258 known / 886 analyzed, imports draining). NEXT is unchanged = Phase 5
  (MPD/Spark) starting with the AIcrowd dataset + license check. Owner track:
  ~100 needs-source repairs, and the DMARC quarantine→reject DNS flip (verified
  still `p=quarantine`, due now). Deferred perf tails, both flagged and NOT
  bundled: origin gzip (1 line, ~9x on the tunnel leg, but verify /audio Range
  scrubbing after) and `/static` carrying a session cookie so Cloudflare reads
  CF-Cache-Status: BYPASS on every asset. NEW SESSION: run `/resume`.**
- **2026-07-27→28 (sessions 61–62 — Epic I under real use; Opus + orchestrator):**
  Jordan imported playlists in earnest and every report was a real defect.
  **Four instances of ONE lie** (journal #58): a Spotify 429 rendered as "No
  importable playlists found", a failed fetch as "Queued 0 new tracks", a
  rate-limited dashboard as **502** — which is in Cloudflare's ORIGIN_DOWN set,
  so the fallback Worker told every visitor the site was down while the app was
  healthy — and a failed-under-cap job as "analyzing…" over an empty queue.
  Fixed with distinct states, a session that SURVIVES an upstream hiccup, and a
  standing tripwire that no route may return an ORIGIN_DOWN status. **Epic I
  re-worked:** page-bounded resumable import (21 API calls per click → 1–2), the
  zero-fetch backlog, Analyze stays on /playlists with a scanned/already-done/
  queued confirmation, Queue nav tab, `queue_count`. **The accounting trilogy** —
  dead-lettered, dedup twins (130 counted as missing forever), and Spotify's
  unimportable local/market-locked items now each have a name. **Caught my own
  regression** (journal #59): the backlog fix made dormant bad data reachable and
  dead-lettered 214 tracks with no name to search for; cause fixed, invariant
  added (`searchable_ids`), damage repaired live — named 281/282, re-opened 213.
  **Left off: 838 tests green, ruff clean, deployed, smoke 14/14, tree synced
  (fae810a). Corpus 1,742 analyzed — 2.4× the 730 this era began with — with
  ~210 queued and draining. BOTH TRUE AUDIT FLAGS HAVE NAMED CAUSES:
  GOLD_PLANE_STALE (983 only in serving, exporter owed after the growth) and
  FEATURE_DISTRIBUTION (exactly ONE broken extraction — "Defector" by Muse,
  tempo 0 / −180 dBFS, the D-52 class). NEXT = let the queue drain, then
  build_feature_marts → export_gold_from_cache → fix Defector → re-run both
  audits → consider a cluster retrain (the corpus is 2.4× what model #9 trained
  on), THEN Phase 5. Owner track: ~394 needs-source repairs and the DMARC
  reject-flip. NEW SESSION: run `/resume`.**
- **2026-07-29 (session 63 — VISION F: the part-two re-envisioning; Fable +
  orchestrator, 5 expert consults + lead browser walk; commits
  980f56c→bd412b0):** owner called part two before Phase 5. Both audits were
  ALL-GREEN at pickup (the e0cef8d post-drain chain had self-closed the two
  predicted flags); corpus 1,946 analyzed / 1,894 canonical. **Vision F
  specced AND RATIFIED same-day (D-61…D-67 + pinned execution parameters +
  the S1–S6 Opus plan)** — the headline findings: the cluster plane silently
  regressed to 36.7% coverage in 7 days with NULL descriptions serving
  (journal #60, the audit's one-sided bound); **MPD is legally dead** and
  Phase 5 re-substrates to the AcousticBrainz CC0 dump (D-65 — 29.5M rows,
  2.8 GB, verified downloadable, doubles as independent DSP ground truth);
  the dsp consult falsified two premises (journal #61 — no worker sleep
  exists, ~14.8 s/track not ~50; tempo quantized to a 20-value lag grid,
  mode near coin-flip); `all_features()` still on 2 request paths (20×);
  no song→artist link anywhere with 15 of 892 artists browsable. Harness
  gap-fill shipped: **gitleaks in CI (first full-history pass GREEN)** +
  the **ui-ux-expert** agent (design lane, 3 dated late-caught defect
  instances) + CLAUDE.md roster fix. A mid-session platform usage limit
  killed the first dsp consult; respawned narrowed, report folded in.
  **Left off: Vision F ratified and pushed (bd412b0), CI green ×3 incl.
  gitleaks, both audits clean, tree synced. NEXT = S1 of the Opus execution
  plan. NEW SESSION: run `/resume`.**
- **2026-07-29 (session 64 — F1: Phase 5 designed in full; Fable-tier lead +
  orchestrator, 3 consults; commit e157a5b):** owner's directive — bank the
  Fable-grade designs now, execute on Opus later. **`docs/PHASE5_AB_SPEC.md`
  is the executable Phase-5 spec** (P5-S1…S7, every judgment pinned;
  D-68…D-73 PROPOSED, owner ratification pending). The consults corrected
  the brief three more times (the #61 class): the "~68% AB coverage"
  projection was over an ISRC attribute the corpus doesn't have (measured
  5.6% — D-70 captures it at zero API cost riding P4.6.6); `beat_times` is
  the SAME beat grid as tempo_bpm (0/1,946 octave disagreements — not a
  third opinion on metrical level, and median-IBI is itself 10ms-quantized
  → k-lag rate is the better v2 candidate); the mode failure is PARALLEL
  major/minor (25.1% runner-up share), not relative. Research verified the
  dump at its generating commit (submission grain: 29.46M rows over 7.56M
  recordings; all-TEXT values; no confidence column — the publisher's own
  disclaimer settles D-68's concordance-not-validation framing) and
  measured the MB batched-ISRC bridge (~50/req, whole corpus <1 min, the
  silent limit=25 trap). Pre-registered predictions on record: coverage
  50–62%, WE_DOUBLE ≥3× WE_HALF, DuckDB beats Spark single-node.
  **Left off: F1 spec pushed (e157a5b). PENDING OWNER: ratify D-68…D-73.
  Remaining Fable-design debt: F3 (the concurrent-pipeline invariants,
  P4.6.5 stage ③) — optional, skippable by design. NEXT unchanged = Vision
  F S1 on Opus. NEW SESSION: run `/resume`.**
- **2026-07-29 (session 65 — ratification + F2/F3: the design debt is
  CLEARED):** owner ratified **D-68…D-73** (marked in VISION_SPECS). **F2**
  → `docs/CORPUS_MIGRATION_PLAYBOOK.md` (the 8-invariant template for any
  corpus-scale mutating batch, distilled from the D-52/quarantine
  disciplines — journal #43/#45/#46/#48/#49 made mechanical). **F3** →
  `docs/PIPELINE_CONCURRENCY_SPEC.md` (P4.6.5 stage ③ as ten named
  invariants I1–I10 each bound to an executable failure drill, a mandatory
  pre-build data-platform red-team gate, and a first-class DON'T-BUILD
  exit — declining is a recorded outcome, the risk-free 2× stands).
  **Every design the project needs Fable for is now banked in specs Opus
  can execute:** Vision F S1–S6, Phase 5 P5-S1…S7, the migration playbook,
  and the optional stage-③ pipeline. **Left off: all specs pushed, tree
  synced. ➡️ NEXT = Vision F S1 (Opus): yt-dlp pin + search throttle +
  shape test · feature_columns() on /analytics + /artist · the GET-write
  fix · owner installs JDK 17 → parity_check green. NEW SESSION: run
  `/resume`.**
- **2026-07-29 (session 66 — VISION F S1 SHIPPED; Opus + orchestrator;
  commits 893346b→4be49c9, CI green on 4be49c9, 844 tests, ruff clean,
  deployed, smoke 14/14):** **P4.6.1+P4.6.2 done.** ① yt-dlp floor
  2026.2.21→**2026.7.4** (CVE-2026-55404) + `uv.lock` regenerated (CI
  installs `--frozen`); `search_ydl_opts()` is now the ONE search-option
  builder and carries **`sleep_requests`** — that path issued unmetered
  requests while downloads slept (F10); `FLAT_SEARCH_CONTRACT` + 4 tests
  lock our side of yt-dlp's churning flat-extraction, **with their honest
  limit written in the file** (offline tests can't see an upstream rename).
  ② **The projections:** `/analytics` (8 `_SIGNATURE_DIMS` cols) and
  `/artist/{id}` (13 `_SIMILARITY_COLS`) off `all_features()` —
  **measured live 1,946-track corpus: 280 ms/6.5 MB → 54 ms/0.6 MB (5.1× /
  10.3×), 0 value mismatches, identical key sets**, and Muse's
  "similar in your library" rendered **byte-identical through the public
  edge** vs the pre-change capture; new
  `test_analytics_population_never_reads_the_heavy_json_columns` guards
  both. ③ **F14 MOVED to P4.6.3** (its fix IS the promotion machinery —
  recorded, not half-built). Housekeeping: `git add -A` swept the
  projection into 893346b whose message describes only the yt-dlp work;
  f28d3b9's message is the truth. **JDK 17 INSTALLED** (Temurin 17.0.20+8,
  winget hash-verified, alongside the untouched JDK 11).
  ⚠️ **UNFINISHED — `spark/parity_check.py` is NOT yet proven locally:**
  the run was killed at 10 min with no visible output (my
  `Select-Object -Last 30` buffered it — re-run streaming, not buffered).
  **AND the reason it matters (journal #62): the Anaconda Spark shadow.**
  `SPARK_HOME=C:\spark\spark-3.5.6-bin-hadoop3` + `PYSPARK_PYTHON` and
  `PYSPARK_DRIVER_PYTHON` both `anaconda3\python.exe` — so Spark WORKERS
  would launch Anaconda's interpreter (pyspark 3.5.6, none of our deps)
  even under `uv run`; `spark-submit` on PATH is 3.5.6 too. Journal #47
  recurring on a second tool. The proven-working invocation is: `JAVA_HOME`
  = the Temurin **17** dir, **`SPARK_HOME` UNSET** (pyspark 4.1.2 bundles
  its own jars — confirmed present in `.venv`), `PYSPARK_PYTHON` =
  `PYSPARK_DRIVER_PYTHON` = `.venv\Scripts\python.exe`, `HADOOP_HOME`
  stays `C:\hadoop` (winutils.exe present; **`hadoop.dll` still absent —
  deliberately NOT downloaded until proven necessary**).
  **Left off: S1 code shipped + deployed + CI green. ➡️ NEXT = finish the
  parity proof (stream the output; pin the env INSIDE the repo so it can't
  be inherited — the #62 fix), then S2 (P4.6.3 freshness + THE RETRAIN).
  NEW SESSION: run `/resume`.**
- **2026-07-30 (session 67 — the local-Spark diagnosis; Opus + orchestrator;
  docs/SCALING.md §"Running Spark LOCALLY on this Windows box"):** ran the
  hang down to its cause. **Spark 4.1.2 + the new JDK 17 WORKS** for
  in-memory work (SparkSession 11 s; count + agg + a real shuffle; 20.5 s) —
  once the journal-#62 env is pinned (`JAVA_HOME`=Temurin 17, `SPARK_HOME`
  **unset**, both `PYSPARK_*_PYTHON`=`.venv` python). **But every local FILE
  read dies on `UnsatisfiedLinkError: NativeIO$Windows.access0`** —
  `winutils.exe` is present, `hadoop.dll` is NOT, and `access0` lives in the
  DLL. `FileUtil.canRead` catches IOException but not `Error`, so the
  globber's pool thread dies and the driver waits on a future forever: **the
  "10-minute slow run" was a deadlock, not slowness.** Searched the whole
  machine — no `hadoop.dll` anywhere; Apache ships no official Windows
  Hadoop binaries. **OWNER DECISION (2026-07-29): WSL2, NOT a third-party
  DLL** (every source is a community repo's unsigned binary loaded into the
  JVM — rejected for a public repo whose security posture is part of the
  portfolio). Done so far: `Microsoft-Windows-Subsystem-Linux` Disabled→
  **Enabled** + `VirtualMachinePlatform` Enabled via elevated DISM (exit
  3010). **⚠️ A REBOOT IS REQUIRED before WSL works** (`wsl --install` still
  reports REGDB_E_CLASSNOTREG until then). Also verified: JDK 11 untouched,
  JDK 17 = Temurin 17.0.20+8.
  **Left off: WSL features enabled, reboot pending. ➡️ NEXT (after Jordan
  reboots + `start_app.bat`): `wsl --install -d Ubuntu` → JDK+uv+deps inside
  WSL → run `spark/parity_check.py` there → THEN pin the env inside the repo
  so it can never be inherited again (#62 fix). S2 (P4.6.3 freshness + THE
  RETRAIN) is NOT blocked by any of this and is the higher-value next build.
  NEW SESSION: run `/resume`.**
- **2026-07-30 (session 68 — SPARK PROVEN LOCALLY + the cross-repo hardening;
  Opus + orchestrator; commits 22465e9→0963961, CI green):** ✅ **WSL2 Spark
  works and parity PASSES locally in 10.9 s** — the claim was CI-only for the
  project's whole life. Getting there: the WSL app package was registered but
  never deployed (`wsl.exe` resolved to the system32 stub) → elevated
  `winget --force`; the Subsystem-Linux feature was Disabled → elevated DISM
  (3010, reboot); Ubuntu installed `--no-launch` and driven by user to skip the
  interactive prompt. **`hadoop.dll` IS required** (my earlier "not needed" was
  wrong — the smoke test only exercised in-memory data): any local FILE read
  hits `NativeIO$Windows.access0`, and because `FileUtil.canRead` catches
  IOException but not `Error`, the globber's pool thread dies and the driver
  waits on a future FOREVER — **the "10-minute slow run" was a deadlock.**
  **OWNER DECISION: WSL2, never an unsigned community DLL**; the Windows
  Spark/Hadoop install was then **removed surgically** (3 env vars, PATH
  entries from BOTH User and Machine scope, `C:\spark` 424 MB, `C:\hadoop`,
  Anaconda's pyspark 340 MB) with a verification between every step.
  **Cross-repo handoff reconciled (journal #63):** 8f2d76b broke the sibling
  **vercilloanalytics** because env vars outlive their directories inside
  ALREADY-RUNNING processes — my verification read the registry, which was
  correct and insufficient. Hardening: runner moved `--user root`→**jordan**,
  versions derived from ONE place (`uv.lock` + `.venv/pyvenv.cfg`; the hosts
  were 3.12.13 vs **3.14.4**, now identical), deps from **`uv sync --frozen`**
  (the hand-picked list was a third encoding AND resolved an unbuildable
  numba), `UV_PROJECT_ENVIRONMENT` + an assertion that the Windows `.venv`
  survives, `.gitattributes`, and `spark/known_answer_check.py` (hand-computed
  constants + a Python UDF — the class parity structurally cannot catch).
  New key files: `scripts/spark_wsl.ps1`, `spark/known_answer_check.py`,
  `.gitattributes`; docs in `docs/SCALING.md`.
  **Left off: Spark proven + hardened, 844 tests, CI green.**
- **2026-07-30 (session 69 — 🏁 VISION F S2 / P4.6.3: THE RETRAIN + D-62
  freshness; Opus + orchestrator; commits aa77004→e3eff38, CI green on
  e3eff38, 857 tests, ruff clean, BOTH audits ALL-FALSE, deployed +
  browser-validated):** **THE F1 FIX IS DONE — cluster coverage 36.7% → 100%**
  (model 13 trained on all 1,894 aggregate tracks, promoted with identity
  remapping). The blank legend now renders both blurbs; **the archetype held
  at "The Drifting Loyalist"** because the remap kept slot 0 meaning the same
  sound. **The D-62 machinery:** `ClusterModel.n_trained`/`promoted_at`/
  `identity_map` (forward-only) · `latest_model()` reads PROMOTED rows only,
  with `_backfill_promoted_at()` blessing the already-serving model so the
  upgrade could not blank `/analytics` (verified live) · `match_identity()`
  (same k, cosine ≥0.90, label words byte-identical) · `promote_model()`
  remaps cluster_id + labels/label_dims/descriptions · bootstrap-promote for
  the first model of a kind · `freshness()` triggers · **4 new audit flags
  that went RED on first run** (CLUSTER_COVERAGE, CLUSTER_MODEL_STALE,
  CLUSTER_DESCRIPTION_MISSING, CLUSTER_PROMOTION_PENDING) · the post-drain
  chain now **trains automatically and self-promotes ONLY identity-stable
  retrains**, printing the diff otherwise. **TWO PRE-EXISTING BUGS EXPOSED:**
  ① **`track_clusters` was keyed on the bridge key ALONE**, so every training
  run overwrote the serving model's assignments — measured live, 700 → 4 rows
  (journal #64); fixed with a composite (track, model) key + a data-preserving
  SQLite rebuild. ② **my own `match_identity` un-scaled L2-normalized
  centroids**, yielding noise (−0.73/+0.71) where direct comparison reads
  −0.97/+0.97 — it would have refused a clean permutation forever (journal
  #65). **F14:** `/analytics` no longer WRITES from a GET (pure
  `nearest_cluster`). **Captions DERIVED** — "Every cached song" was wrong by
  64%; my first fix over-counted by 4 (in-memory assignments have no
  coordinates), caught by the live browser check and now asserted
  caption-count == rendered `<circle>` count. Silhouette is recorded and
  NEVER a staleness reason (it DROPPED 0.176→0.148 with growth — gating on it
  would freeze the model at its smallest population; encoded as a test).
  New key files: `scripts/promote_cluster_model.py`,
  `src/store/test_cluster_freshness.py` (11 tripwires).
  **Left off: S2 COMPLETE + live (coverage 1.0, growth 1.0, all flags FALSE).**
- **2026-07-30 (session 70 — VISION F S3 / P4.6.4 + P4.6.6 + D-70; Opus +
  orchestrator; commits 925900c/7b3288a, CI green on BOTH, 861 tests, ruff
  clean, warehouse ALL-FALSE, qa_audit 0-failed, smoke 14/14, deployed):**
  **① P4.6.4 — the post-drain chain stops being O(corpus) every poll.**
  Measured first: **5.31 s / 1,946 tracks = 2.73 ms/track**, outgrowing its own
  30 s poll at **~11k** — inside the import trajectory, and the worst case was
  a full O(N) rebuild for the 2 tracks that finished this poll.
  `persist_perceptual` now writes in ONE transaction (was a session+commit per
  row — the chain's biggest cost, and a crash now leaves the table wholly old
  or wholly new); `refresh_duplicate_flags` no longer runs TWICE per drain
  (`rebuild_marts` already does it first); **debounce** = after
  `--rebuild-after 50` tracks or `--rebuild-every 10` min, and ALWAYS the
  moment the queue empties; `silhouette_score` samples above
  `_SILHOUETTE_SAMPLE=5000` (the only O(N²) step, run once PER CANDIDATE k —
  ~7 s at 1.9k, ~3 min at 10k, hours at 100k; deterministic, and the value is
  REPORTED never gated per D-62). **After: 3.81 s (1.96 ms/track), 1.39×,
  headroom ~11k → ~15.3k** — and it no longer runs every poll at all.
  **② P4.6.6 + D-70 — ISRC 0% → 100%.** `fetchers._track_to_record` had ALWAYS
  built `isrc`/`album_id`/`album_type`/`album_release_date`; `remember_meta`
  discarded all four, so the SERVING CACHE had **0 of 2,357** (journal #66 —
  the consult's "109 / 5.6%" was availability in the old Parquet staging
  snapshots, NOT the cache; **stale fact corrected**). Four forward-only
  columns + preserve-if-absent + `cache.all_track_identity()` (kept OUT of the
  2-field hot-path `all_meta`) + `scripts/backfill_track_identity.py`; **ran
  live, 47 batched calls → 2,356/2,357 (100%)**, aggregate corpus 1,894/1,894.
  **A Phase 5 number measured WITHOUT touching AcousticBrainz: 1,528 of 1,894
  (80.7%) predate the dump's 2022-06-23 freeze**, so 366 are guaranteed
  misses — the ceiling D-65's pre-registered 50–62% prediction lives under,
  and it fits. **③ `GOLD_SCHEMA_SHRINK`** — the D-60 exporter had narrowed
  `dim_tracks` 10→6 columns and nothing noticed, because no check looks at the
  shape of what we PROMISE; now a checked-in `docs/gold_schema_manifest.json`
  (a FLOOR — adding columns is fine) + the flag, `dim_tracks` restored to 11
  columns carrying real album/ISRC data, and **the flag PROVEN to fire** by
  simulating the exact D-60 narrowing. New key files:
  `scripts/backfill_track_identity.py`, `docs/gold_schema_manifest.json`,
  `src/store/test_cache.py`; new readers `all_track_identity()`,
  `upsert_perceptual_many()`.
  **Left off: S3 COMPLETE + live. Vision F is 3/6 (S1–S3 = the whole platform
  half); what remains is user-facing surface. PHASE 5 IS UNBLOCKED — D-70 was
  its hard prerequisite and the ISRC bridge is at 100%, so P5-S1's only
  remaining piece is the MusicBrainz client.
  ➡️ NEXT = Vision F S4 (P4.7.0 + P4.7.1): lift `_BANDS`/`_SIGNATURE_DIMS`/
  archetype thresholds into ONE `scales.py` with caption-parity tests (do this
  BEFORE Epic R doubles their consumers), then `RAW_FEATURE_DOC` + the two raw
  marts + **`GET /song/{id}/features`** (all 83 numeric features, D-66) with
  the set-equality doc tripwire. NEW SESSION: run `/resume`.**