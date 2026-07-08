# Self-Hosting Runbook — vercilloanalytics.com from the owner's PC (Epic E, D-16)

**The template.** This documents hosting a web app from a home PC at **$0/month**
with a real domain and real HTTPS — written for this project, structured to be
reused for every future one (§9 is the generic checklist).

```
 Visitor ──HTTPS──> Cloudflare edge ──(outbound-only tunnel)──> this PC
                    vercilloanalytics.com          cloudflared (service)
                                                        │ http://localhost:8000
                                       ┌────────────────┴───────────────┐
                                       │ uvicorn webapp    worker --loop │
                                       │        └── SQLite+WAL ──┘       │
                                       │   data/feature_cache.db         │
                                       │   data/spectrograms/*.png       │
                                       └────────────────────────────────┘
 Owner ──Tailscale (private admin: RDP/SSH/testing — NOT public traffic)──> this PC
```

**Why this shape**
- **Cloudflare Tunnel**, not port-forwarding: the PC makes an *outbound*
  connection to Cloudflare; nothing inbound is opened, the home IP is never
  published, HTTPS is automatic on the free plan.
- **Not Tailscale Funnel** for the public URL: Funnel cannot serve custom
  domains (only `*.ts.net`). Tailscale stays as the *private admin plane*.
- **Residential IP bonus:** yt-dlp acquisition works *better* from a home IP
  than from cloud ranges (YouTube throttles datacenter IPs) — the extraction
  worker actively prefers this machine (D-16).
- Registration stays at Squarespace; **only nameservers move** to Cloudflare.
  A nameserver change is not a domain transfer — domain lock stays ON.

---

## 1. One-time: move DNS to Cloudflare (~20 min, owner)

> ⚠️ **The domain carries Google Workspace email.** The MX/SPF/DKIM records must
> survive the move — verify them at step 3 before switching nameservers.

1. Create a free account at cloudflare.com → **Add a site** →
   `vercilloanalytics.com` → **Free** plan.
2. Cloudflare scans and imports the domain's live DNS records.
3. **Verify the email records exist** in the imported list (add manually if
   missing — exact values are in the Squarespace DNS page):
   - `MX @ smtp.google.com` (priority 1)
   - `TXT @ "v=spf1 include:_spf.google.com ~all"`
   - `TXT google._domainkey "v=DKIM1; k=rsa; p=MIIBIj…"` (the long DKIM key)
4. Cloudflare shows **two nameservers** (e.g. `ada.ns.cloudflare.com`).
5. Squarespace → Domains → the domain → **Domain Nameservers** → *Use custom
   nameservers* → paste the two Cloudflare nameservers → Save.
6. Wait for the zone to show **Active** in Cloudflare (minutes; up to 48 h).
7. **Send yourself a test email** to confirm Workspace mail still flows.

*Old DNS host cleanup (optional): if the previous nameservers were
`ns-cloud-*.googledomains.com`, a Google **Cloud DNS zone** still exists in some
GCP project (~$0.20/month). Find it at console.cloud.google.com → Network
services → Cloud DNS (check each project) and delete the zone once Cloudflare
is Active.*

## 2. One-time: the tunnel on this PC

```powershell
winget install --id Cloudflare.cloudflared
cloudflared tunnel login          # opens a browser: pick vercilloanalytics.com
cloudflared tunnel create vercillo
```

Config at `%USERPROFILE%\.cloudflared\config.yml`:

```yaml
tunnel: <TUNNEL-UUID from create>
credentials-file: C:\Users\jverc\.cloudflared\<TUNNEL-UUID>.json

ingress:
  - hostname: vercilloanalytics.com
    service: http://localhost:8000
  - hostname: www.vercilloanalytics.com
    service: http://localhost:8000
  - service: http_status:404
```

```powershell
cloudflared tunnel route dns vercillo vercilloanalytics.com
cloudflared tunnel route dns vercillo www.vercilloanalytics.com
cloudflared tunnel run vercillo            # foreground test first
cloudflared service install                # then install as a Windows service
```

## 3. One-time: app configuration

1. **Spotify dashboard** → the app → Settings → Redirect URIs → **add**
   `https://vercilloanalytics.com/callback` (keep the existing 127.0.0.1 ones
   for local dev) → Save. Allowlist testers under User Management (Dev Mode
   caps ~25 users; submit the extended-quota request and note the date).
2. `.env` (gitignored) — production values:
   ```
   WEBAPP_REDIRECT_URI=https://vercilloanalytics.com/callback
   SESSION_SECRET_KEY=<fresh 48-byte urlsafe secret — do NOT reuse the dev one>
   # optional: ANTHROPIC_API_KEY=…  (LLM answers; deterministic fallback without)
   ```
   The `https://` redirect automatically turns on Secure cookies. **No Spotify
   client secret exists anywhere — PKCE only (D-8).**

## 4. Run procedure (two processes + the tunnel service)

```powershell
# terminal 1 — the webapp
uv run python scripts/run_webapp.py
# terminal 2 — the extraction worker (drains the queue forever)
uv run python scripts/run_extraction_worker.py --loop
# the tunnel runs as a Windows service already
```

First-time data prep: `uv run python scripts/seed_cache.py --spectrograms`
then `uv run python scripts/train_clusters.py`. Retrain clusters occasionally
as the cache grows.

**Autostart (optional):** Task Scheduler → two "At log on" tasks running the
commands above (Start in: the repo directory). The cloudflared service starts
itself.

## 5. Backups — the cache is an asset (D-17)

```powershell
uv run python scripts/backup_cache.py              # snapshot → backups/*.zip (keeps 10)
uv run python scripts/backup_cache.py --verify backups\<zip>
uv run python scripts/backup_cache.py --restore backups\<zip>   # STOP the app first
```

- Nightly: Task Scheduler → daily 03:00 → the bare backup command.
- WAL-safe: snapshots use the SQLite backup API, never a raw file copy.
- Restore keeps the current db as `feature_cache.db.pre-restore`.
- **Run the drill once** (Epic E acceptance): backup → verify → restore →
  reload the dashboard.

## 6. Operations honesty

- **The app is up when the PC is up** (stated in the pilot's framing; fine for
  allowlisted testers). Sleep/hibernate = down; disable sleep or schedule
  demo hours.
- Sessions are in-memory: an app restart logs everyone out (they log in again).
- Update flow: `git pull` → `uv sync --frozen` → restart the two processes.

## 7. Tailscale (the private plane)

Keep it for remote admin: RDP/SSH to the PC, private testing of :8000 via
`tailscale serve`. After a network/wifi change it normally reconnects on its
own — open the app, re-auth if it's logged out. Never expose the public app
through it (Funnel can't carry the custom domain anyway).

## 8. Troubleshooting

| Symptom | Cause → fix |
|---|---|
| Cloudflare 502/530 on the domain | webapp not running / tunnel down → start `run_webapp.py`; `cloudflared tunnel info vercillo` |
| Zone stuck "Pending" | nameservers not switched or still propagating → recheck Squarespace, wait |
| Email stopped | MX/SPF/DKIM missing in Cloudflare → re-add from §1.3 |
| Spotify `INVALID_CLIENT: Invalid redirect URI` | prod URI not added in the dashboard, or `.env` doesn't match it exactly |
| Login loops / cookie never sticks | `WEBAPP_REDIRECT_URI` not https → Secure cookie sent over http |
| "analyzing…" never completes | worker not running → start it with `--loop`; check `extraction_jobs.last_error` |
| Restore fails (file in use, WinError 32) | stop the webapp + worker first (Windows locks open db files) |

## 9. The template — any future project on this PC

1. Buy/own the domain anywhere; **move its DNS to Cloudflare** (free) —
   registration stays put; verify email records before switching NS.
2. App listens on `localhost:<port>`; **never port-forward**.
3. `cloudflared tunnel create <name>` → ingress `hostname → localhost:<port>`
   → `tunnel route dns` → install as a service.
4. OAuth/webhooks get `https://<domain>/…` callbacks; secrets live in a
   gitignored `.env`; Secure cookies keyed off the https URL.
5. State lives in one data directory; **scheduled zip backups + one restore
   drill** before calling it live.
6. Autostart via Task Scheduler; Tailscale for private admin only.
7. Write the ops honesty down (uptime = PC uptime) and publish a privacy page
   before sharing the URL.
