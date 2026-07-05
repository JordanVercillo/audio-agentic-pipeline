# P8 — Production-Pilot Webapp: Build Plan (SPEC P8, D-7)

**Status:** design approved 2026-07-05 (stack = FastAPI + Jinja2). No app code
yet — this is the plan the slices execute against.

**One-line thesis:** productize the P5 retrieval core behind a public URL where
*any* visitor authenticates their **own** Spotify (no owner secret — D-8), and
the app grounds LLM taste-answers on their listening history joined against our
local DSP feature store. Converts the portfolio from *artifacts* to *a running
product* — the JD's "AI agents on data infrastructure" differentiator.

---

## 1. Architecture — mostly reuse

| P8 capability | Reuses (unchanged) | New in `src/webapp/` |
|---|---|---|
| Per-visitor auth | `SpotifyPKCE` (client-id only) | **session-scoped** driver — token in session, not the shared file cache |
| Visitor's tracks | `ingestion/fetchers.fetch_top_tracks/artists` (already client-injectable) | call with the session's client |
| Acoustic insight | gold features + **bridge key** (`spotify_track_id`) | overlap-join + insight computation (feature-store pattern) |
| RAG retrieval | `WarehouseAgent(modeled_dir=…)` — **already injectable** | point it at a **per-session temp dir** of the visitor's own Parquet → same locked-down DuckDB sandbox (D-10), per visitor |
| Grounded answer | `analysis/insights` templates + `column_descriptions` | LLM call + deterministic fallback (D-5) |

The desktop pipeline's `ingestion/auth.py` (file-cache PKCE flow) stays
**untouched**; the webapp adds a *parallel* session flow. Two entry points, one
`SpotifyPKCE` primitive, zero secret.

## 2. Module layout

```
src/webapp/
  __init__.py
  config.py         # env: SPOTIPY_CLIENT_ID, WEBAPP_REDIRECT_URI,
                    #      SESSION_SECRET_KEY (infra, NOT the Spotify secret),
                    #      ANTHROPIC_API_KEY (optional). No secrets in repo.
  sessions.py       # SessionStore: in-memory dict, per-entry TTL + sweep;
                    #      signed session-id cookie helpers (itsdangerous)
  auth_web.py       # build_authorize_url(session) / exchange_code(session,code,state)
                    #      / client_from_session(session)  — session-scoped PKCE
  featurestore.py   # join visitor tracks × gold features on bridge key;
                    #      overlap → 77-dim acoustic; miss → metadata; insight()
  rag.py            # per-session WarehouseAgent over visitor Parquet;
                    #      retrieve() + answer()  (LLM w/ deterministic fallback)
  app.py            # FastAPI factory: middleware, routes, Jinja2, static
  templates/        # base, index, dashboard, ask, privacy
  static/           # minimal CSS (single sheet)
  test_webapp.py    # synthetic tests — auth logic, join, rag fallback, TTL
scripts/run_webapp.py   # uvicorn launcher
Dockerfile              # slice 3
docs/P8_PLAN.md         # this file
```

## 3. Session-scoped PKCE (the crux)

The stock flow assumes a desktop browser + shared file cache. The web flow must
persist the in-flight **code_verifier** across the redirect, per visitor:

- **`GET /login`** — mint a `SpotifyPKCE(client_id, WEBAPP_REDIRECT_URI, scope)`,
  call `get_authorize_url(state=<random>)`, stash `{code_verifier, state}` in the
  server-side session, 302 the browser to Spotify.
- **`GET /callback?code&state`** — verify `state` == session's state (**CSRF
  gate**); recreate `SpotifyPKCE`, restore `.code_verifier` from session, call
  `get_access_token(code, check_cache=False)`; store `token_info` in the session
  (a `SessionCacheHandler`, never a file); rotate the session id; clear the
  in-flight PKCE.
- **Using it** — `client_from_session()` → `spotipy.Spotify(auth=<access_token>)`.

**Scopes:** request only `user-top-read` (least privilege) — narrower than the
pipeline's broad `USER_SCOPES`.

**Session store:** signed cookie holds *only* a random session id; token +
verifier live server-side (in-memory dict for the pilot) with a TTL and a sweep
→ satisfies D-7 "session-scoped, ephemeral, sessions expire." `SESSION_SECRET_KEY`
signs the cookie — an **infra credential**, explicitly *not* the forbidden
Spotify client secret (SPEC deploy note: "infra creds only"). Multi-instance
later → swap the dict for Redis/Firestore (noted, not built).

## 4. Feature-store join + acoustic insight

- Load gold fact features once (process-wide, read-only) from
  `data/warehouse/modeled/`.
- Join the visitor's `spotify_track_id`s against them on the **bridge key**.
- **Overlap** → attach real acoustic vectors; compute the insight (e.g. the
  overlap subset's tempo/energy/valence profile vs the corpus centroid, and the
  nearest acoustic-cluster label from `analysis/clustering.py`).
- **Miss** → metadata/genre treatment only. **Visitors never trigger YouTube
  acquisition** (non-goal preserved).

> **Honest limitation (call it out in the demo):** a stranger's top tracks may
> have *low or zero* overlap with the 117-track corpus. Mitigations: (a) the
> corpus is Jordan's taste — demos best for similar listeners; (b) allowlisted
> pilot testers (friends/recruiters) likely share some; (c) graceful copy when
> overlap = 0 ("0 of your top tracks are in our acoustic corpus yet — here's the
> metadata view + how the feature store works"). Optionally seed the corpus with
> popular tracks later. The insight is framed as *acoustic profiling on the
> overlap subset*, never overclaimed.

## 5. RAG

Per session: write the visitor's joined table + a copy of `column_descriptions`
to a session temp dir as Parquet, construct `WarehouseAgent(modeled_dir=…)` — the
**identical** two-layer sandbox (statement guard + `enable_external_access=false`
+ `lock_configuration=true`), now scoped to the visitor's own ephemeral tables.

- **Retrieve:** `get_schema()` + app-composed *parameterized* queries (their top
  tracks, their acoustic summary) + insight templates. The visitor never writes
  SQL — lower surface than the MCP tool, but the guard/sandbox still apply as
  defense-in-depth.
- **Answer:** if `ANTHROPIC_API_KEY` is set, call Claude (default
  `claude-haiku-4-5` for cost; `claude-sonnet-5` for quality) with the retrieved
  context → grounded answer that cites their data. **No key → deterministic
  template answer** from the retrieved rows (D-5 holds). Grounding is mandatory:
  the model only sees retrieved rows, never free-associates.

## 6. Slice sequence (local before cloud) + acceptance evidence

| Slice | Deliverable | Evidence |
|---|---|---|
| **1** | FastAPI app + session PKCE + `/`, `/login`, `/callback`, `/dashboard` (top tracks + overlap insight) | `pytest src/webapp` green (synthetic: CSRF reject, join, TTL); real localhost login shows top items + insight |
| **2** | `/ask` grounded RAG answer (+ deterministic fallback) | test: fallback answer from synthetic rows w/o key; live: answer cites their tracks |
| **3** | `Dockerfile`; `docker run` parity | container serves the same flow locally |
| **4** | Cloud Run + `vercilloanalytics.com` + allowlist + `/privacy` + demo recording | allowlisted tester logs in on the public URL; deploy env has **no Spotify secret**; sessions expire; README pilot link |

## 7. Dependencies (added to `pyproject.toml`, lockfile refreshed)

`fastapi`, `uvicorn[standard]`, `jinja2`, `itsdangerous`, `python-multipart`;
`anthropic` (optional, RAG). Everything else already present (spotipy, duckdb,
pandas, pyarrow).

## 8. Testing — synthetic, CI-runnable, no secrets

FastAPI `TestClient` at route level; monkeypatch `get_access_token` so **no real
Spotify** is needed. Cover: `/login` stashes verifier+state; `/callback` rejects
state mismatch (CSRF) and stores token on match; feature-store overlap detection
+ insight; RAG deterministic fallback; `SessionStore` TTL expiry. All green in
the existing `lint-and-test` CI job (ground-rule: synthetic data only).

## 9. Ground-rule & risk compliance

- **No secret (D-8):** client-id + redirect-uri + infra cookie key only; verified
  by a test asserting no `client_secret` reaches any Spotify call.
- **Bridge key / Parquet-only:** the join is on `spotify_track_id`; session
  tables are Parquet.
- **Privacy (D-7):** ephemeral by default, TTL, opt-in persistence only, `/privacy`
  published, no third-party sharing.
- **Honest gate:** Dev Mode ~25-user allowlist; extended-quota request submitted +
  documented; never claims "public at scale."

## 10. Dependencies on Jordan (outside code)

1. **Spotify dashboard:** add `http://127.0.0.1:8000/callback` (dev) and later
   `https://vercilloanalytics.com/callback` (prod) to the app's redirect-URI
   allowlist; keep app in Dev Mode; allowlist pilot testers; submit extended-quota
   request.
2. **`SESSION_SECRET_KEY`:** generate + set in `.env` (gitignored) / Cloud Run env.
3. **`ANTHROPIC_API_KEY`** (optional): enables LLM answers; absent → deterministic
   fallback still passes acceptance.
4. **Domain + Cloud Run project** (slice 4).
