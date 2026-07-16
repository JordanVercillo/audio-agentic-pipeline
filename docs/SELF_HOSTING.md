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

> ⚠️ **The domain's email records must survive the nameserver move** — verify
> MX + SPF at step 3 before switching. (At cutover the domain still used Google
> Workspace email; it has since moved to free **Cloudflare Email Routing** —
> §1a. Setting up fresh? Skip the Workspace records and go straight to §1a.)

1. Create a free account at cloudflare.com → **Add a site** →
   `vercilloanalytics.com` → **Free** plan.
2. Cloudflare scans and imports the domain's live DNS records.
3. **Verify the email records exist** in the imported list (add manually if
   missing):
   - `MX @ smtp.google.com` (priority 1)
   - `TXT @ "v=spf1 include:_spf.google.com ~all"`
4. Cloudflare shows **two nameservers** (e.g. `ada.ns.cloudflare.com`).
5. Squarespace → Domains → the domain → **Domain Nameservers** → *Use custom
   nameservers* → paste the two Cloudflare nameservers → Save.
6. Wait for the zone to show **Active** in Cloudflare (minutes; up to 48 h).
7. **Send yourself a test email** to confirm Workspace mail still flows.

### 1a. Email = Cloudflare Email Routing (free) — the $0 mailbox (2026-07-09)

**Decision:** dropped Google Workspace (paid, ~$17 CAD/mo) for **Cloudflare
Email Routing** (free). `jordan@vercilloanalytics.com` now *forwards* to a
personal inbox at $0 — you receive at the domain address and reply from your
personal one. Right for a receive-only invite contact; no reason to pay for a
full mailbox. (Keep Workspace only if you need to *send* as the domain.) A live
check also exposed that the domain never actually had DKIM/DMARC on Workspace —
Email Routing gives it both automatically.

> **The domain wears three hats, all $0:** ① website (Cloudflare tunnel →
> uvicorn), ② the *professional identity* `jordan@vercilloanalytics.com` is a
> free **Microsoft Entra/365** account (Power BI/Office login — no Exchange
> license, so it has no mailbox of its own; the OWA
> `OwaUserHasNoMailboxAndNoLicenseAssignedException` is expected), ③ *email* to
> that address is received via Cloudflare Email Routing (this section). Login
> (Entra) is independent of MX, so the email cutover doesn't touch Power BI —
> and cancelling Workspace touches none of the three. Keep the Microsoft
> account's **Security Info** recovery pointed at a reachable phone / personal
> inbox, not the domain mailbox.

Setup — Cloudflare dashboard → **Email → Email Routing**:
1. **Destination Addresses** → add your personal inbox → click the verification
   link Cloudflare emails you (must show **Verified**).
2. **Routing rules** → enable **Catch-all** → *Send to* → your verified address
   (forwards `jordan@`, `hello@`, anything `@the-domain`).
3. **Delete the old provider's MX + SPF** in DNS → Records — they conflict with
   Email Routing's. It then installs its own **locked** records:
   `MX route1/2/3.mx.cloudflare.net`, `TXT cf2024-1._domainkey …` (DKIM, auto),
   `TXT @ v=spf1 include:_spf.mx.cloudflare.net ~all`.
   > **Gotcha (hit live):** after a *manual* MX/SPF delete, Email Routing can
   > flip to **Disabled / Not configured** and refuse to auto-commit. Fix:
   > Email Routing → **Onboard Domain** re-runs the wizard and writes the
   > records cleanly — the verified destination + catch-all survive.
4. **DMARC** — the DNS page's "Add a DMARC record" recommendation → **Add**.
   Cloudflare **DMARC Management** installs `_dmarc → v=DMARC1; p=none;
   rua=mailto:<id>@dmarc-reports.cloudflare.net` and parses the reports for you
   (no XML in your inbox). Its dashboard lags — trust the DNS record over the
   "no RUA found" banner.

**Verify (authoritative — journal #14):**
```powershell
$d = "vercilloanalytics.com"
Resolve-DnsName -Type MX  $d -Server 1.1.1.1                       # route*.mx.cloudflare.net
Resolve-DnsName -Type TXT $d -Server 1.1.1.1                       # SPF _spf.mx.cloudflare.net
Resolve-DnsName -Type TXT "cf2024-1._domainkey.$d" -Server 1.1.1.1 # DKIM
Resolve-DnsName -Type TXT "_dmarc.$d" -Server 1.1.1.1              # DMARC
```
Then send a test email to the domain address and confirm it lands in the
personal inbox. **Only then cancel Workspace** (Google Admin → Billing →
Subscriptions → Cancel). Note the Cloudflare *login* is the domain address, so
forwarding must be working first (a reset email would route through it).

**Orphaned Google Cloud DNS zone** (deleted zone behind the old
`ns-cloud-*.googledomains.com` delegation, ~$0.20/mo): console.cloud.google.com
→ **Network services → Cloud DNS** (check each project) → delete its records
(all but the auto `NS`/`SOA`) → **Delete zone**. CLI: `gcloud dns managed-zones
list` then `gcloud dns managed-zones delete <zone>`. Safe now that Cloudflare is
authoritative.

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
cloudflared service install                # then install as a Windows service (elevated)
```

> ⚠️ **Windows service gotcha (learned live 2026-07-08):** `service install`
> registers the service with **no arguments**, so it looks for config in the
> LocalSystem profile and **crash-loops**. Fix once, elevated — point the
> service's `ImagePath` at the user config via the registry (exact string, no
> shell quote-mangling; `sc.exe config` from PowerShell mangles the inner
> quotes and fails *silently*):
>
> ```powershell
> Set-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Services\cloudflared" -Name ImagePath `
>   -Value '"C:\Program Files (x86)\cloudflared\cloudflared.exe" --config "C:\Users\jverc\.cloudflared\config.yml" tunnel run'
> Start-Service cloudflared
> ```

## 3. One-time: app configuration

1. **Spotify dashboard** → the app → Settings → Redirect URIs → **add**
   `https://vercilloanalytics.com/callback` (keep the existing 127.0.0.1 ones
   for local dev) → Save. Allowlist testers under User Management (Dev Mode
   caps **5 users** since the Feb-2026 policy — adds are manual-only in the
   dashboard's User Management tab, there is no API for it, and extended
   quota now requires a registered business with ≥250K MAU. The landing
   page tells visitors to email for a seat).
2. `.env` (gitignored) — production values:
   ```
   WEBAPP_REDIRECT_URI=https://vercilloanalytics.com/callback
   SESSION_SECRET_KEY=<fresh 48-byte urlsafe secret — do NOT reuse the dev one>
   # optional: ANTHROPIC_API_KEY=…  (LLM answers; deterministic fallback without)
   ```
   The `https://` redirect automatically turns on Secure cookies. **No Spotify
   client secret exists anywhere — PKCE only (D-8).**

## 4. Run procedure (two processes + the tunnel service)

**The easy way — double-click** (in the repo root):

| File | What it does |
|---|---|
| `start_app.bat` | Starts the webapp + worker (skips any already running), nudges the tunnel, waits for `:8000`, prints status. |
| `stop_app.bat` | Stops the webapp + worker, then **backs up the cache** (WAL-safe, prunes to 10); leaves the tunnel service up. |
| `status_app.bat` | Shows whether each process + the tunnel + `:8000` are up. |

All three wrap `scripts/app_control.ps1` (`-Action start|stop|status|restart`).
Each process runs detached with its output appended to `logs\*.log`
(gitignored); the console window stays open on `pause` so you can read the
result. `start` is idempotent — a second click won't launch a second webapp
(which couldn't bind `:8000` anyway).

**The manual way** (two terminals, live logs in the foreground):

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

> **Pick one runtime model.** The double-click scripts (manual control) and the
> Scheduled Tasks below (hands-off at logon) both launch the *same* two
> processes. They coexist safely — `start` won't double-launch — but if you want
> logon autostart, use the tasks; if you'd rather open/close the app yourself,
> use the `.bat` files and skip registering the tasks.

**Autostart (one command):**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_autostart.ps1
```

Registers three current-user Scheduled Tasks (no elevation): webapp + worker
at logon, nightly cache backup at 03:00. Output appends to `logs\*.log`
(gitignored). The cloudflared service starts itself, so a reboot + logon
brings the whole stack back with no operator. Gotchas baked into the script:
`ExecutionTimeLimit` is zeroed (the Scheduler default silently kills tasks
after 72 h) and failures restart ×3. Don't run the same process in a manual
terminal AND as the scheduled task. Remove them all:
`Get-ScheduledTask "VercilloAnalytics*" | Unregister-ScheduledTask -Confirm:$false`.

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

### 6a. H5 fallback — the shared link is never dead (owner deploy, ~2 min)

When the app is off, the edge shows a bare Cloudflare error (530/1033 tunnel
down, 502 app down). The Worker at
[`infra/cloudflare/origin-fallback-worker.js`](../infra/cloudflare/origin-fallback-worker.js)
replaces that with an honest "runs on-demand" page (503 + Retry-After so
crawlers don't index the fallback as the site; `/healthz` and non-GET keep the
raw error for machine callers; a healthy origin passes through untouched).

Deploy (Cloudflare dashboard, free plan — 100k req/day):
1. **Workers & Pages → Create → Worker** (name: `origin-fallback`), paste the
   file, **Deploy**.
2. Worker → **Settings → Domains & Routes → Add route**:
   `vercilloanalytics.com/*` on zone `vercilloanalytics.com` (add
   `www.vercilloanalytics.com/*` too — the www→apex redirect lives in the app,
   which is down in exactly the case this covers).
3. Verify: `stop_app.bat`, then browse the domain — the fallback card renders
   (not error 1033); `curl -s -o NUL -w "%{http_code}" https://vercilloanalytics.com/healthz`
   → `530`-family JSON, not HTML. `start_app.bat` → the real app returns.

## 7. Tailscale (the private plane)

Keep it for remote admin: RDP/SSH to the PC, private testing of :8000 via
`tailscale serve`. After a network/wifi change it normally reconnects on its
own — open the app, re-auth if it's logged out. Never expose the public app
through it (Funnel can't carry the custom domain anyway).

## 8. Troubleshooting

| Symptom | Cause → fix |
|---|---|
| **Registrar's DNS page shows records but nothing resolves (SERVFAIL/REFUSED)** | the page is an inactive copy — the delegated nameservers' zone no longer exists (this domain's Google Cloud DNS zone had been deleted while Squarespace still delegated to it). Verify with `Resolve-DnsName <domain> -Server <the delegated NS>`; the fix IS the Cloudflare cutover |
| cloudflared service crash-loops ("terminated unexpectedly") | registered with no arguments → set the registry `ImagePath` per §2's gotcha box |
| Cloudflare 502/530 on the domain | webapp not running / tunnel down → start `run_webapp.py`; `cloudflared tunnel info vercillo` |
| Zone stuck "Pending" | nameservers not switched or still propagating → recheck Squarespace, wait |
| Email stopped | MX/SPF/DKIM/DMARC missing in Cloudflare → re-add from §1 / §1a |
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
