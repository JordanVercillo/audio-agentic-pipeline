"""
smoke_public.py — QA-2 layer 5: the standing browser-validation practice, scripted.

    uv run python scripts/smoke_public.py [--base-url URL] [--json] [--require-up]

GET-only, credential-free, production-safe. It never logs in, never reads .env,
and never POSTs; the only session it holds is the credential-free guest session
the app itself mints (H7/D-30). Guests neither fetch Spotify nor enqueue — an
app-level guarantee the route matrix proves — so a run costs the corpus nothing.

Exit codes:
    0  green
    1  BROKEN — the app answered, and answered wrong
    2  ORIGIN DOWN — the H5 fallback Worker answered. That is the expected
       on-demand state (the app runs on the owner's PC), not a failure.
       --require-up promotes 2 to 1 for post-deploy gating.

NOT run in CI: there is no tunnel and no corpus there. `testpaths = ["src"]` in
pyproject means scripts/ is never collected by pytest, so the exclusion is
structural rather than a naming convention someone can break.

Deliberately does NOT touch /chat: a guest GET generates the opening story
through the local LLM, ~90 s of the owner's GPU per run.
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import re
import sys
import time
import urllib.error
import urllib.request

BASE = "https://vercilloanalytics.com"
TIMEOUT = 15

# The H5 Worker's signature (infra/cloudflare/origin-fallback-worker.js). It
# rides a 503 because Cloudflare REPLACES a Worker 502/504 with its own error
# page (journal #33), which would erase authorship.
DOWN_JSON = '"origin":"unreachable"'
DOWN_CARD = "Demo offline"
# base.html:8. The fallback card is self-contained with inline CSS and requests
# no /static asset, so this tag is positive proof the ORIGIN APP rendered the
# page — not the edge, not a cached shell. That is what separates "down" from
# "broken" when a 200 comes back looking plausible.
ORIGIN_TAG = '<link rel="stylesheet" href="/static/style.css">'


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Follow nothing: a 303 gate must never silently read as a 200."""

    def redirect_request(self, *a, **k):
        return None


_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(_jar), _NoRedirect())
# Shared across checks: /library discovers a real track id so nothing here
# hard-codes one and the smoke keeps working as the corpus changes.
_STATE: dict = {}


class Resp:
    def __init__(self, status, body, headers, elapsed):
        self.status, self.body, self.headers, self.elapsed = status, body, headers, elapsed

    @property
    def location(self):
        return self.headers.get("Location", "")


def get(path, base=BASE) -> Resp:
    t0 = time.monotonic()
    req = urllib.request.Request(base + path, headers={"User-Agent": "va-smoke/1"})
    try:
        with _opener.open(req, timeout=TIMEOUT) as r:
            body = r.read().decode("utf-8", "replace")
            return Resp(r.status, body, dict(r.headers), time.monotonic() - t0)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        return Resp(e.code, body, dict(e.headers), time.monotonic() - t0)


def _is_down(r: Resp) -> bool:
    return r.status == 503 and (DOWN_JSON in r.body or DOWN_CARD in r.body)


def _origin_rendered(r: Resp) -> tuple[bool, str]:
    if ORIGIN_TAG not in r.body:
        return False, "200 without the origin's stylesheet tag — something " \
                      "between us and the app answered"
    return True, ""


# ── checks: each returns (ok, detail) and may raise to fail ──────────────────
def check_healthz(_):
    r = get("/healthz")
    if _is_down(r):
        return None, "origin down (the H5 fallback answered /healthz)"
    if r.status != 200:
        return False, f"expected 200, got {r.status}"
    if json.loads(r.body).get("ok") is not True:
        return False, f"unexpected body {r.body[:80]!r}"
    return True, f"200 in {r.elapsed:.2f}s"


def check_www_to_apex(_):
    r = get("/", base="https://www.vercilloanalytics.com")
    if r.status != 301:
        return False, f"expected 301, got {r.status}"
    if "www." in r.location:
        return False, f"redirect keeps www: {r.location}"
    return True, f"301 -> {r.location}"


def check_landing(_):
    r = get("/")
    if r.status != 200:
        return False, f"expected 200, got {r.status}"
    ok, why = _origin_rendered(r)
    if not ok:
        return False, why
    if 'href="/login"' not in r.body:
        return False, "no login CTA on the landing page"
    return True, f"200 in {r.elapsed:.2f}s"


def check_cookie_flags(_):
    """Production-only: _SECURE_COOKIE is computed at import from the DEPLOYED
    redirect URI, so a repo test can never observe the real value."""
    r = get("/")
    raw = r.headers.get("Set-Cookie", "")
    if "va_sid" not in raw:
        return None, "no session cookie set on this response (skipped)"
    missing = [f for f in ("HttpOnly", "Secure", "SameSite")
               if f.lower() not in raw.lower()]
    if missing:
        return False, f"session cookie missing {missing}: {raw[:120]}"
    return True, "HttpOnly + Secure + SameSite"


def check_anon_gate(path):
    def _fn(_):
        r = get(path)
        if r.status != 303 or r.location != "/":
            return False, f"expected 303 -> /, got {r.status} -> {r.location!r}"
        return True, "gated"
    return _fn


def check_library(state):
    r = get("/library")
    if r.status != 200:
        return False, f"expected 200, got {r.status}"
    ok, why = _origin_rendered(r)
    if not ok:
        return False, why
    # The A7 marker, asserted against the DEPLOYED build: the owner-only repair
    # queue must not be reachable from an anonymous page.
    if 'href="/library?filter=needs-source"' in r.body:
        return False, "the owner-only needs-source tab rendered for an anon visitor"
    ids = re.findall(r'href="/song/([0-9A-Za-z]{1,64})"', r.body)
    if not ids:
        return False, "no song links on /library — the catalog rendered empty"
    state["track_id"] = ids[0]
    return True, f"200, {len(ids)} song links"


def check_song(state):
    tid = state.get("track_id")
    if not tid:
        return False, "no track id discovered from /library"
    r = get(f"/song/{tid}")
    if r.status != 200:
        return False, f"expected 200, got {r.status}"
    ok, why = _origin_rendered(r)
    if not ok:
        return False, why
    for marker in ('action="/song/', 'href="/library?filter=needs-source"'):
        if marker in r.body:
            return False, f"owner-only affordance {marker!r} rendered for anon"
    return True, f"/song/{tid} 200 in {r.elapsed:.2f}s"


def check_spectrogram(state):
    tid = state.get("track_id")
    r = get(f"/spectrogram/{tid}")
    if r.status == 404:
        return True, "404 (honest — this track has no spectrogram)"
    if r.status != 200:
        return False, f"expected 200 or 404, got {r.status}"
    ctype = r.headers.get("Content-Type", "")
    if "image" not in ctype:
        return False, f"200 but content-type {ctype!r} is not an image"
    return True, f"200 {ctype}"


def check_queue(_):
    r = get("/queue")
    if r.status != 200:
        return False, f"expected 200, got {r.status}"
    ok, why = _origin_rendered(r)
    return (True, "200") if ok else (False, why)


def check_privacy(_):
    r = get("/privacy")
    if r.status != 200:
        return False, f"expected 200, got {r.status}"
    # config.SCOPES is the single source for this copy — catches a prod drift.
    if "user-top-read" not in r.body:
        return False, "the disclosed scopes do not mention user-top-read"
    return True, "200, scopes disclosed"


def check_guest_path(_):
    r = get("/guest")
    if r.status != 303 or r.location != "/dashboard":
        return False, f"expected 303 -> /dashboard, got {r.status} -> {r.location!r}"
    d = get("/dashboard")          # the jar carries the guest session
    if d.status != 200:
        return False, f"/dashboard as guest: expected 200, got {d.status}"
    ok, why = _origin_rendered(d)
    if not ok:
        return False, why
    if 'class="demo-banner"' not in d.body:
        return False, "guest dashboard rendered without the demo banner"
    if 'action="/ask"' in d.body:
        return False, "a guest was shown the authed ask box — live gate failure"
    return True, "guest dashboard rendered read-only"


def check_no_secrets(_):
    for path in ("/", "/library", "/privacy"):
        body = get(path).body.lower()
        for needle in ("access_token", "client_secret", "sessionsecret"):
            if needle in body:
                return False, f"{path} leaks {needle!r}"
    return True, "no token/secret strings in any public body"


CHECKS = [
    ("healthz", check_healthz),
    ("www_to_apex", check_www_to_apex),
    ("landing", check_landing),
    ("cookie_flags", check_cookie_flags),
    ("library_public", check_library),
    ("song_deepdive", check_song),
    ("spectrogram", check_spectrogram),
    ("queue_public", check_queue),
    ("privacy", check_privacy),
    ("gate_explore", check_anon_gate("/explore")),
    ("gate_recommend", check_anon_gate("/recommend")),
    ("gate_playlists", check_anon_gate("/playlists")),
    ("guest_path", check_guest_path),
    ("no_secrets", check_no_secrets),
]


def main() -> int:
    global BASE
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default=BASE)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--require-up", action="store_true",
                    help="treat ORIGIN DOWN as a failure (post-deploy gating)")
    args = ap.parse_args()
    BASE = args.base_url.rstrip("/")

    results, down = [], False
    for name, fn in CHECKS:
        t0 = time.monotonic()
        try:
            ok, detail = fn(_STATE)
        except Exception as exc:  # noqa: BLE001 — a check must never crash the run
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        results.append({"check": name, "ok": ok, "detail": detail,
                        "seconds": round(time.monotonic() - t0, 3)})
        if ok is None and name == "healthz":
            down = True
            break                     # every later check would be noise

    if args.json:
        print(json.dumps({"base_url": BASE, "origin_down": down,
                          "results": results}, indent=2))
    else:
        print(f"public smoke — {BASE}")
        print("─" * 78)
        for r in results:
            glyph = "·" if r["ok"] is None else ("✓" if r["ok"] else "✗")
            print(f" {glyph} {r['check']:16s} {r['detail']}  ({r['seconds']}s)")
        print("─" * 78)

    if down:
        print("ORIGIN DOWN — the app runs on demand; this is the expected "
              "state when it is stopped.")
        return 1 if args.require_up else 2
    failed = [r for r in results if r["ok"] is False]
    print(f"{len(failed)} failed · {sum(1 for r in results if r['ok'])} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
