/**
 * origin-fallback-worker.js — the $0 always-up fallback (H5 / P3.6).
 *
 * The app runs ON-DEMAND on the owner's PC (owner decision, 2026-07-09) behind
 * a Cloudflare Tunnel. When it's off, the edge returns a bare Cloudflare error
 * (530/1033 tunnel-down, or 502 when the tunnel is up but the app isn't). This
 * Worker sits on the zone route and turns that dead end into an honest,
 * self-contained "runs on-demand" page — the shared link is never dead.
 *
 * Behavior:
 *   - Origin healthy → pass the response through UNTOUCHED (streaming intact).
 *   - Origin down (fetch throws, or 5xx in the origin-down family) → serve the
 *     static fallback with HTTP 503 + Retry-After (honest to crawlers: the
 *     content is temporarily unavailable, don't index the fallback as the site).
 *   - Non-GET requests and /healthz keep the raw error (machine callers should
 *     see the truth, not HTML).
 *
 * Deploy (owner, ~2 min — see docs/SELF_HOSTING.md §"H5 fallback"):
 *   Cloudflare dashboard → Workers & Pages → Create worker → paste this file →
 *   Deploy → Settings → Domains & Routes → add route `vercilloanalytics.com/*`
 *   (zone: vercilloanalytics.com). $0: free plan allows 100k requests/day.
 */

// Cloudflare's origin-down family: 502/504 (bad gateway via tunnel),
// 521-523 (origin down/unreachable), 530 (tunnel error 1033).
const ORIGIN_DOWN = new Set([502, 504, 521, 522, 523, 530]);

const FALLBACK_HTML = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Vercillo Analytics — waking up</title>
  <link rel="icon" href='data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">🎧</text></svg>'>
  <style>
    :root { --bg:#0f1115; --panel:#171a21; --ink:#e8eaed; --muted:#9aa0ac;
            --line:#2a2f3a; --spotify:#1db954; }
    * { box-sizing: border-box; }
    body { margin:0; background:var(--bg); color:var(--ink); min-height:100vh;
           display:grid; place-items:center;
           font: 16px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif; }
    main { max-width: 34rem; padding: 2rem 1.5rem; text-align: center; }
    h1 { font-size: 1.5rem; margin: 0 0 .75rem; }
    p { color: var(--muted); margin: .5rem 0; }
    .card { background: var(--panel); border: 1px solid var(--line);
            border-radius: 10px; padding: 1.5rem; }
    a { color: var(--spotify); }
    .badge { display:inline-block; font-size:.75rem; letter-spacing:.05em;
             text-transform:uppercase; color:var(--spotify); border:1px solid
             var(--line); border-radius:999px; padding:.25rem .7rem;
             margin-bottom:1rem; }
  </style>
</head>
<body>
  <main>
    <div class="card">
      <span class="badge">Demo offline — by design</span>
      <h1>Vercillo Analytics runs on-demand</h1>
      <p>This is a personal data-engineering pilot: a Spotify taste-analytics
        app whose acoustic features are extracted locally (the audio analysis
        Spotify's API retired), served from the developer's own machine at $0.
        It isn't running right now — that's the on-demand design, not an outage.</p>
      <p>Want a live tour or a pilot seat? Email
        <a href="mailto:jordan@vercilloanalytics.com">jordan@vercilloanalytics.com</a>
        — or just try again later.</p>
    </div>
  </main>
</body>
</html>`;

export default {
  async fetch(request) {
    let response;
    try {
      response = await fetch(request);
    } catch (err) {
      response = null; // tunnel/origin unreachable at the fetch layer
    }
    if (response !== null && !ORIGIN_DOWN.has(response.status)) {
      return response; // healthy (or an app-level error the app chose) — untouched
    }
    // Machine callers get the truth, not HTML. Two live-learned constraints:
    // the tunnel's origin-down answer is a REAL 502/530 response with an HTML
    // body (it doesn't throw), and Cloudflare REPLACES a Worker response
    // carrying 502/504 with its standard error page (body and all) — so the
    // JSON must ride a 503, which passes through untouched (proven: the card).
    const url = new URL(request.url);
    if (request.method !== "GET" || url.pathname === "/healthz") {
      return new Response('{"ok":false,"origin":"unreachable"}', {
        status: 503,
        headers: { "content-type": "application/json", "retry-after": "3600" },
      });
    }
    return new Response(FALLBACK_HTML, {
      status: 503,
      headers: {
        "content-type": "text/html; charset=utf-8",
        "retry-after": "3600",
        "cache-control": "no-store",
      },
    });
  },
};
