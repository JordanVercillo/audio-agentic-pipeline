# Spotify Web API Research Brief — Phase 3 (artist pages · genre analysis · playlist ingestion)

**Prepared by:** research-expert agent (first outing, via `/orchestrator`) — advisory
**Date / access date for all live checks:** 2026-07-14
**App posture:** Development mode · PKCE-only (no client secret exists, D-8) · 5-seat allowlist · scopes today: `user-top-read` (`src/webapp/config.py:43`)
**Method:** every external claim carries a URL + access date; conflicts with the repo's dated live verifications are FLAGGED per the research-expert charter (repo's dated live checks outrank undated docs for "what answers today"; the changelog outranks everything for "what's guaranteed tomorrow").

---

## 0. Executive summary — there were TWO waves, and the second is the one that bites Phase 3

1. **Nov 27, 2024 wave** — removed for new apps and dev-mode apps without a pending extension request: Related Artists, Recommendations, Audio Features, Audio Analysis, Featured Playlists, Category's Playlists, 30-second preview URLs in multi-get responses, and algorithmic/Spotify-owned editorial playlists. Extended-quota apps grandfathered. ([blog, 2024-11-27](https://developer.spotify.com/blog/2024-11-27-changes-to-the-web-api), accessed 2026-07-14)
2. **Feb 2026 wave** (the one our guardrails file calls "the post-February 2026 structural transformation") — a much larger dev-mode restructuring: **all batch "Get Several …" endpoints removed** (including `GET /artists` and `GET /tracks`), **`GET /artists/{id}/top-tracks` removed with no replacement**, browse categories removed, `/playlists/{id}/tracks` renamed to `/items`, search limit cut to 10, and a long list of field removals (`artist.followers`, `artist.popularity`, `track.popularity`, `user.email/country/product`…). Effective **2026-02-11 for new apps, 2026-03-09 for existing dev-mode apps**. Extended-quota apps: "not affected by any of the changes." ([changelog](https://developer.spotify.com/documentation/web-api/references/changes/february-2026); [migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide), both accessed 2026-07-14)
3. **Enforcement reality (the key nuance):** this repo's **dated live checks post-date the enforcement deadline and still succeeded on PKCE user tokens** — batch `GET /artists` on 2026-07-03 (28 artists, 1 call; `notes/PROJECT_CONTEXT.md` session 5) and batch `GET /tracks` on 2026-07-09/10 (**119/119 in 3 calls**, journal #20 / PROJECT_CONTEXT §"backfill_popularity"). Meanwhile the rspotify maintainer documented real failures on 2026-03-15 — **using a client-credentials token** ([rspotify issue #550](https://github.com/ramsayleung/rspotify/issues/550), accessed 2026-07-14). Working inference (UNVERIFIED as stated policy): **enforcement is landing on client-credentials/app-only tokens first; user-authorized PKCE tokens from existing dev apps still answer** the "removed" surfaces. Our app is PKCE-only by design, so we are on the still-answering path — but everything on the removed list must be treated as **borrowed time, absent-safe, never load-bearing** (the journal #20 doctrine, now applied in the other direction).
4. **Grandfathering is permanently out of reach:** extended-quota extension now requires a legally registered business with **≥250k MAU** ([quota-modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes), accessed 2026-07-14). Local derivation is therefore not a stopgap for this project — **it is the permanent architecture**, which is the project's founding thesis anyway.

---

## 1. Artist endpoints

| Endpoint | Docs status (2026-07-14) | Dev-mode reality for THIS app | Source |
|---|---|---|---|
| `GET /artists?ids=` (batch, ≤50 ids) | **Endpoint marked Deprecated** (header-level); listed **Removed** in Feb-2026 changelog | **Still answers on our PKCE tokens** — repo live check 2026-07-03 (1 call, 28 artists). Borrowed time. | [ref](https://developer.spotify.com/documentation/web-api/reference/get-multiple-artists) · [changelog](https://developer.spotify.com/documentation/web-api/references/changes/february-2026), accessed 2026-07-14; repo: PROJECT_CONTEXT session 5 |
| `GET /artists/{id}` | **Not deprecated** — the surviving artist read | Safe to build on. Fields `followers`, `genres`, `popularity` individually marked **Deprecated** (genres: "If not yet classified, the array is empty") | [ref](https://developer.spotify.com/documentation/web-api/reference/get-an-artist), accessed 2026-07-14 |
| `GET /artists/{id}/top-tracks` | **Deprecated** label under the title; Feb-2026 changelog: **Removed — "no replacement available"** | Do NOT build artist top-10 on this. Never live-tested by this repo (UNVERIFIED whether it still answers on PKCE) — attempt absent-safe only; see derivation map | [ref](https://developer.spotify.com/documentation/web-api/reference/get-an-artists-top-tracks) · [migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide), accessed 2026-07-14 |
| `GET /artists/{id}/albums` | **Not deprecated** — but `limit` now **"Default: 5. Minimum: 1. Maximum: 10."** (verbatim; was 20/50 historically). `include_groups`: `album,single,appears_on,compilation` | Usable for discography headline stats; deep pagination is now 10/page. `market` optional — user-token country takes priority | [ref](https://developer.spotify.com/documentation/web-api/reference/get-an-artists-albums), accessed 2026-07-14 (limit quote re-verified word-for-word) |
| `GET /artists/{id}/related-artists` | **Deprecated** (page still exists) | **Gone for us since before this app existed** — Nov-2024 wave removed it for dev-mode/new apps; grandfathered only for apps that already held extended quota before 2024-11-27. Our client_id is a 2026 registration | [ref](https://developer.spotify.com/documentation/web-api/reference/get-an-artists-related-artists) · [blog 2024-11-27](https://developer.spotify.com/blog/2024-11-27-changes-to-the-web-api), accessed 2026-07-14 |

**Market parameter behavior** (top-tracks and albums, same doc language): optional; if omitted and a valid **user** access token is present, **the user's account country takes priority**; with neither, "the content is considered unavailable for the client." For our per-visitor PKCE sessions, omitting `market` is correct — each seat gets their own country automatically. ([top-tracks ref](https://developer.spotify.com/documentation/web-api/reference/get-an-artists-top-tracks), accessed 2026-07-14)

**⚠ FLAG (docs vs repo code):** `fetch_artists_by_ids` (`src/ingestion/fetchers.py:190-245`) is built on the batch endpoint that the changelog removed. It demonstrably still works on our tokens (2026-07-03), and `safe_api_call` already degrades 403/404 gracefully (`src/ingestion/guardrails.py:100-109`) — but Phase 3 should add the migration guide's own fallback ("fetch items individually" — singular `GET /artists/{id}` is un-deprecated) behind the batch attempt. ~100 artists as singles at the current `throttle(0.2)` ≈ 150 req/30s, which brushes the community-reported ceiling (§5) — use ≥0.5s throttle on the fallback path.

---

## 2. Playlist endpoints

| Endpoint | Docs status (2026-07-14) | Notes for Phase 3 | Source |
|---|---|---|---|
| `GET /me/playlists` | Current, not deprecated | `limit` default 20 / **max 50**, `offset` max 100,000. Response playlist objects: **`tracks` field Deprecated → use `items`** (`items.total` = track count) | [ref](https://developer.spotify.com/documentation/web-api/reference/get-a-list-of-current-users-playlists), accessed 2026-07-14 |
| `GET /playlists/{id}` | Current, not deprecated | `fields` filter supported; `tracks` → `items` rename applies here too. **`items` is "only available for playlists owned by the current user or playlists the user is a collaborator of"** — other playlists return metadata only | [ref](https://developer.spotify.com/documentation/web-api/reference/get-playlist), accessed 2026-07-14 |
| `GET /playlists/{id}/tracks` | **Endpoint itself Deprecated: "Use Get Playlist Items instead"** | The path our `fetch_playlist_tracks` (via spotipy `playlist_items`) may still be hitting — verify which URL our spotipy version calls | [ref](https://developer.spotify.com/documentation/web-api/reference/get-playlists-tracks), accessed 2026-07-14 |
| `GET /playlists/{id}/items` | **The successor** — current | `limit` default 20 / **max 50** (the old /tracks 100/page is gone). Item shape: `added_at`, `added_by`, `is_local`, entity under **`item`** (`track` kept as a deprecated alias with the same content). Pagination: `next`/`total`/`offset` as before | [ref](https://developer.spotify.com/documentation/web-api/reference/get-playlists-items), accessed 2026-07-14 |
| `GET /users/{id}/playlists` | **Removed** (Feb-2026) | Other users' playlists are gone; only `/me/playlists` survives | [changelog](https://developer.spotify.com/documentation/web-api/references/changes/february-2026), accessed 2026-07-14 |
| Featured playlists / category playlists | **Deprecated** (Nov-2024 wave) | Never available to this app; algorithmic/editorial (Spotify-owned) playlists also inaccessible | [ref](https://developer.spotify.com/documentation/web-api/reference/get-featured-playlists) · [blog 2024-11-27](https://developer.spotify.com/blog/2024-11-27-changes-to-the-web-api), accessed 2026-07-14 |

**Scopes** (all three verified current on the scopes page, accessed 2026-07-14 — [concepts/scopes](https://developer.spotify.com/documentation/web-api/concepts/scopes)):
- `playlist-read-private` — "Read access to user's private playlists." (listed as the required scope on both /me/playlists and /playlists/{id}/items)
- `playlist-read-collaborative` — "Include collaborative playlists when requesting a user's playlists."
- `user-top-read` — unchanged, still current.

Phase 3 scope string: `"user-top-read playlist-read-private playlist-read-collaborative"` in `src/webapp/config.py` — one-line change, but **all 5 seats re-consent** on next login (new authorize prompt).

**Dev-mode constraints that shape the feature:** playlist ingestion in dev mode is effectively **"the authed user's own + collaborated playlists."** Arbitrary public playlists yield metadata without items; editorial/algorithmic playlists are inaccessible outright. Design the UI around "import from *your* playlists," not a paste-any-playlist-URL box.

**⚠ FLAG (repo code vs current docs):** three drift points in `src/ingestion/fetchers.py` —
1. `fetch_user_playlists` reads `pl["tracks"]["total"]` (line 420); the live docs now mark `tracks` Deprecated → read `items.total` with `tracks.total` fallback (deprecated-but-present, the popularity pattern).
2. `fetch_playlist_tracks` passes `limit=min(limit, 100)` (line 452) — the successor endpoint's max is **50**; over-asking may error or silently clamp depending on path. Set 50.
3. `search_tracks` default `limit=20` — Feb-2026 cut `/search` to **"maximum 10, default 5"** (changelog, verbatim). Same over-ask risk.

---

## 3. Genres

- **Track-level genre does not exist.** The Track object has no genre field — confirmed on the current reference ([get-track](https://developer.spotify.com/documentation/web-api/reference/get-track), accessed 2026-07-14). It never has; nothing changed here.
- **`artist.genres` is the only live genre signal — and it is now marked Deprecated** on the artist object ("If not yet classified, the array is empty") ([get-an-artist](https://developer.spotify.com/documentation/web-api/reference/get-an-artist), accessed 2026-07-14). Notably it was **not** on the Feb-2026 *removed-fields* list (that list took `followers` and `popularity`) — so today it's deprecated-not-removed, exactly the popularity posture. **This is a NEW watch item not yet in the repo's guardrails file.**
- **Sparsity reality (repo ground truth beats any doc):** journal #9 (2026-07-03) — 36/117 tracks had no genre at all via artist arrays; PROJECT_CONTEXT records track-level genre coverage **81/118 — "the honest ceiling."** Genre metadata also degenerates under a dominant artist — cluster naming already had to fall back to acoustic z-scores.
- **`/recommendations/available-genre-seeds`: Deprecated** ([ref](https://developer.spotify.com/documentation/web-api/reference/get-recommendation-genres), accessed 2026-07-14) — and pointless anyway, since its only consumer (`/recommendations`) is also Deprecated.
- **Browse categories as a genre proxy: dead end.** `GET /browse/categories` and `/browse/categories/{id}` are **Deprecated on the reference pages and Removed in the Feb-2026 changelog** ([ref](https://developer.spotify.com/documentation/web-api/reference/get-categories) · [changelog](https://developer.spotify.com/documentation/web-api/references/changes/february-2026), accessed 2026-07-14). Do not build genre UX on categories.

**Phase 3 genre posture:** keep fetching `artist.genres` absent-safe and **treat the warehouse/cache as the system of record** — genres already persisted survive any upstream removal (cached values can't be un-shipped). Layer the coarse-genre rules and the acoustic cluster names (journal #9's own fix) on top, and put the coverage number in the UI.

---

## 4. The deprecation waves — what is gone for THIS app today vs deprecated-but-answering

| Capability | Wave | For our dev-mode PKCE app, TODAY (2026-07-14) |
|---|---|---|
| `/audio-features`, `/audio-analysis` | Nov-2024 | **Gone** (never available to this 2026-registered app). Blocked at the Python level too (`guardrails._BLOCKED_METHODS`) |
| `/recommendations` (+ genre seeds) | Nov-2024 | **Gone** for us; ref pages carry Deprecated labels |
| `/artists/{id}/related-artists` | Nov-2024 | **Gone** for us; grandfathered only for pre-2024-11-27 extended-quota apps |
| Featured / category playlists; editorial+algorithmic playlists | Nov-2024 (+categories re-removed Feb-2026) | **Gone** |
| **`preview_url` (30s)** | Nov-2024 | Field still documented, marked **Deprecated**, nullable. Expect null (UNVERIFIED — never needed). **Irrelevant by D-22:** full-track audio via yt-dlp, never 30s previews |
| Batch gets: `GET /tracks`, `GET /artists`, `GET /albums` | Feb-2026 ("removed" for dev mode from 2026-03-09) | **Deprecated-but-ANSWERING on our PKCE user tokens** — repo live checks 2026-07-03 (artists) and 2026-07-09/10 (tracks, 119/119). Client-credentials tokens fail ([rspotify #550](https://github.com/ramsayleung/rspotify/issues/550)). Borrowed time; keep absent-safe with singles fallback |
| `GET /artists/{id}/top-tracks` | Feb-2026, "no replacement" | **Deprecated; assume unusable.** Untested on our tokens; attempt absent-safe only, never load-bearing |
| `/search` | Feb-2026 change | Alive, but limit **max 10 / default 5** |
| `track.popularity`, `artist.popularity/followers`, `user.email/country/product/followers`, `track.available_markets`, `album.label` | Feb-2026 removed-fields list | **`track.popularity` verifiably still returned on our tokens (journal #20, post-enforcement).** Treat the whole list as deprecated-not-removed on PKCE, absent-safe everywhere |
| `external_ids` (ISRC) | Feb-2026 removed → **March-2026 REVERTED** | **Stays available** — "will continue to be available" ([March changelog](https://developer.spotify.com/documentation/web-api/references/changes/march-2026), accessed 2026-07-14) |
| `GET /me/top/{type}` | untouched by both waves | **Not deprecated, no callouts** — limit 20/50, three time_ranges, scope `user-top-read`. The lifeline holds |

**⚠ FLAGGED CONFLICTS, and which side to trust:**
1. **Feb-2026 changelog ("removed as of 2026-03-09") vs repo live checks (working 2026-07-03/09/10).** Trust the repo's dated live checks for *today's behavior*; trust the changelog for *intent*. The rspotify client-credentials failure reconciles them: enforcement appears token-type-staged. The token-type theory is an inference from three data points — UNVERIFIED as policy; keep the fallbacks.
2. **Guardrails file (`.agent_prompts/01`) vs current docs:** its allowed-surface list omits the Feb-2026 refinements (`/tracks`→`/items` rename, items-only-for-own-playlists, search limit 10, artist-albums limit 10, batch-get removals) and mis-dates the audio-features removal (actually Nov-2024 for new/dev apps). **Recommend a guardrails-file refresh as a Phase 3 side task** (the journal #20 "audit your own guardrails" lesson, wave 2).
3. **Docs pages are JS-heavy and easy to misread** — the research process itself initially missed a Deprecated label and caught it on a targeted re-fetch. Quote-targeted re-verification is the standard.

---

## 5. Rate limits + dev-mode quotas (for a 5-user app)

- **Model:** rolling **30-second window**; no numeric limit published; dev mode < extended mode; 429 + `Retry-After` (seconds) ([rate-limits](https://developer.spotify.com/documentation/web-api/concepts/rate-limits), accessed 2026-07-14).
- **Community-reported number (UNVERIFIED):** ~180 requests/minute ≈ 90/30s ([community thread](https://community.spotify.com/t5/Spotify-for-Developers/Web-API-ratelimit/td-p/5330410), accessed 2026-07-14). Post-Feb-2026 threads report 429s at lower volumes — budget conservatively.
- **Dev-mode facts** ([quota-modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes), accessed 2026-07-14): **"Up to 5 authenticated Spotify users" — the 5-seat allowlist is the PLATFORM ceiling, not a self-imposed choice**; non-allowlisted users 403; 1 client ID per developer; **app owner must hold Spotify Premium**; extension requires a registered business ≥250k MAU (→ permanently dev-mode).
- **Phase 3 budget math** (per user session, worst case): top items 6 calls + artist backfill 2 batch calls (or ~100 singles on the fallback — the only burst risk; throttle ≥0.5s) + `/me/playlists` 1-2 calls + one 500-track playlist = 1 + ⌈500/50⌉ = **11 calls**. Even ×5 users, trivial against ~90/30s.
- **Code note:** `safe_api_call` catches 403/404 only; a 429 propagates after spotipy's internal retries (spotipy honors `Retry-After`, default 3 retries). If Phase 3 adds a playlist-ingest loop, catch 429 → sleep(`Retry-After`) explicitly rather than dying mid-pagination.

---

## 6. DERIVATION MAP — deprecated capability → our replacement

| Deprecated capability | Our replacement | Status | Fully replaces, for OUR app? | Phase 3: live vs derive |
|---|---|---|---|---|
| `/audio-features` | Local 77-dim DSP + `perceptual-v1` (honest tiers) | **BUILT** | **Yes, and better** — versioned, reproducible, not ToS-limited for ML | Derive; no live option exists |
| `/audio-analysis` | Mel-spectrogram, loudness curve, beat grid, section ribbon | **BUILT** | **Yes for the consumed subset** (per-segment pitch/timbre matrices not replicated; nothing consumed them) | Derive |
| `/recommendations` | Epic G explorer (tunables, z-distance, 77-dim space) | **BUILT** | **Yes within our corpus** (cannot surface unheard catalog — a disclosure, not a gap) | Derive |
| `/artists/{id}/related-artists` | **artist_profiles acoustic centroids** (Epic C) | **BUILT** | **Adequate as "acoustically nearest artists in your library"** — ours answers "who sounds alike here," theirs answered "who is listened-to alike globally." Label the UI accordingly. Behavioral half arrives via MPD co-occurrence (Phase 5) | Derive ("similar in your library" panel; 0 calls) |
| Genre seeds | Coarse-genre rules + cached `artist.genres` + acoustic cluster names | **BUILT** | **Yes** — 81/118 coverage is the honest ceiling; acoustic labels fill the rest. `artist.genres` now docs-Deprecated → cache/warehouse copy is durable | Live-fetch absent-safe on new artists; derive analysis from the stored copy |
| `preview_url` (30s) | n/a — full-track via yt-dlp (D-22) | **BUILT** | **Yes, strictly better** | Neither |
| **NEW:** `/artists/{id}/top-tracks` | **"YOUR top tracks by this artist"**: ranges/ranks we already store, per artist | **DERIVABLE today** | **Yes for a taste app** — arguably more honest ("your top-N" vs market-global top-10, which is simply no longer available to dev-mode apps) | Derive as the core; attempt the live call absent-safe as garnish while it answers |
| **NEW:** batch `GET /artists` | Keep batch-while-it-answers + singular `GET /artists/{id}` fallback (un-deprecated) | Fallback: **NOT BUILT** (small) | Yes — same data, more calls | Live, guarded, with fallback |

---

## 7. What this unblocks / what to watch

**Unblocked for Phase 3:**
- **Artist pages** — zero-API-call core: identity/genres/images from the stored copy, "your top tracks by artist" from existing marts, "similar in your library" from `artist_profiles` centroids. Optional live garnish: `GET /artists/{id}` refresh (safe) and one `GET /artists/{id}/albums?limit=10` page for discography breadth.
- **Playlist ingestion** — `/me/playlists` + `/playlists/{id}/items` with the two new read scopes; each imported track flows into the existing intake path (the O1 dedup guard already protects the cache). A 500-track playlist = **11 calls, ~2-3 s throttled**. The real constraint is scope of access: **own + collaborative playlists only** — design the picker around the user's library, not arbitrary URLs.
- **Genre analysis** — proceed on the stored copy with coarse-genre rules + acoustic-cluster fallback; live fetches top it up absent-safely.

**Watch list:**
1. **Artist top-10 volume — moot by design** (derived core costs 0 calls; the absent-safe live attempt is 1 call per artist-page view, authed only).
2. **Playlist pagination** — 50/page is the new fixed reality (`min(limit,100)` must become 50); verify which URL spotipy hits (`/tracks` deprecated vs `/items` current); read `item` with `track` fallback and `items.total` with `tracks.total` fallback; use `snapshot_id` to skip unchanged playlists.
3. **Genre coverage honesty in the UI** — surface the number ("genres known for N of M — Spotify's genre arrays are sparse and now deprecated; unlabeled tracks are classified acoustically"). Never render "Unknown" without the acoustic label beside it.
4. **Standing risk:** everything removed-but-still-answering (batch gets, `popularity`, `genres`, `followers`) can go dark without notice — absent-safe capture + `safe_api_call` + stored-copy-as-system-of-record are the guards. Periodic re-verification (journal #20 discipline) is the cheap insurance. **The guardrails file needs its second correction wave.**

**Primary sources:** [Nov-2024 announcement](https://developer.spotify.com/blog/2024-11-27-changes-to-the-web-api) · [Feb-2026 changelog](https://developer.spotify.com/documentation/web-api/references/changes/february-2026) · [Feb-2026 migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide) · [Mar-2026 changelog](https://developer.spotify.com/documentation/web-api/references/changes/march-2026) · [quota-modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes) · [rate-limits](https://developer.spotify.com/documentation/web-api/concepts/rate-limits) · [scopes](https://developer.spotify.com/documentation/web-api/concepts/scopes) · endpoint reference pages as cited inline (all accessed 2026-07-14). **Repo ground truth:** `.agent_prompts/01_spotify_api_guardrails.md` · `notes/engineering_journal.md` #9/#20 · `notes/PROJECT_CONTEXT.md` · `src/ingestion/fetchers.py` · `src/ingestion/guardrails.py` · `src/webapp/config.py`.
