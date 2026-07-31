<#
app_control.ps1 - start / stop / status the local app processes (SELF_HOSTING section 4).

    powershell -ExecutionPolicy Bypass -File scripts\app_control.ps1 -Action <start|stop|status|restart|deploy>

The double-clickable start_app.bat / stop_app.bat / status_app.bat at the repo
root wrap this. It manages the two processes the app needs at runtime:
    - Webapp   uvicorn on http://127.0.0.1:8000  (scripts/run_webapp.py)
    - Worker   the extraction-queue drain --loop  (scripts/run_extraction_worker.py)
The cloudflared tunnel is a Windows SERVICE (auto-starts on boot); this script
only reports its status and, on start, nudges it if it is stopped.

Idempotent: 'start' never launches a second copy of a service that is already
running (a second webapp can't bind :8000), so double-clicking twice - or using
this ALONGSIDE the register_autostart.ps1 scheduled tasks - is safe.

Processes are launched detached (their own hidden console), so they keep running
after this script - and the launching terminal - exits. Output is appended to
logs\webapp.log / logs\worker.log (gitignored, rotated at 5 MB on start).
'stop' matches processes by THIS repo's absolute script path (or the
space-anchored relative form) - a bare filename substring could catch another
checkout's processes or an editor with the filename in its argv.

'deploy' is the seamless one: pull, sync deps if the lock moved, restart, verify.
run_webapp.py runs uvicorn with reload=False (correct for a served process), so
a running app NEVER picks up a code change on its own. On 2026-07-31 that meant
a full day of fixes sitting in the repo while the live site served the morning's
code, and nothing on the status line said so. Now 'start' stamps the commit it
launched into logs\running_commit.txt and 'status' compares it to HEAD, so
"is the site up to date" is answerable at a glance instead of by inference.

ASCII-only on purpose: Windows PowerShell 5.1 reads a BOM-less file as ANSI, so
non-ASCII punctuation would corrupt the parse.
#>

param(
    [ValidateSet('start', 'stop', 'status', 'restart', 'deploy')]
    [string]$Action = 'status'
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot          # scripts\ -> repo root
$py = Join-Path $repo '.venv\Scripts\python.exe'
$logs = Join-Path $repo 'logs'
$healthUrl = 'http://127.0.0.1:8000/healthz'
$publicUrl = 'https://vercilloanalytics.com'

$services = @(
    [pscustomobject]@{ Name = 'Webapp'; Match = 'run_webapp.py';
        Script = (Join-Path $repo 'scripts\run_webapp.py'); AppArgs = ''; Log = 'webapp.log' }
    # --takeover: this script OWNS the lifecycle (start only runs after its own
    # already-running check; restart just stopped the predecessor, whose
    # heartbeat may still look fresh for ~5 min). The DB single-instance lock
    # stays armed against MANUAL second starts.
    [pscustomobject]@{ Name = 'Worker'; Match = 'run_extraction_worker.py';
        Script = (Join-Path $repo 'scripts\run_extraction_worker.py'); AppArgs = '--loop --interval 30 --takeover'; Log = 'worker.log' }
)

function Get-ServiceProcs($svc) {
    # Anchored matching: this repo's ABSOLUTE script path, or the space-anchored
    # relative form (a manual `python scripts\run_x.py` from the repo). A bare
    # filename substring would also catch another checkout's processes or an
    # editor/linter with the filename in its argv - and Stop-Process -Force them.
    $abs = $svc.Script
    $rel = "scripts\$($svc.Match)"
    $relFwd = "scripts/$($svc.Match)"
    Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
        Where-Object { $_.CommandLine -and (
            ($_.CommandLine -like "*$abs*") -or
            ($_.CommandLine -like "* $rel*") -or
            ($_.CommandLine -like "* $relFwd*")) }
}

function Test-Health {
    try {
        $r = Invoke-WebRequest -Uri $healthUrl -TimeoutSec 3 -UseBasicParsing
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

function Get-TunnelStatus {
    try { return (Get-Service cloudflared -ErrorAction Stop).Status.ToString() }
    catch { return 'not installed' }
}

$stampFile = Join-Path $logs 'running_commit.txt'

function Get-HeadCommit {
    # Short sha of what is CHECKED OUT right now, or '' if git is unavailable.
    try {
        $sha = (& git -C $repo rev-parse --short HEAD 2>$null)
        if ($LASTEXITCODE -ne 0) { return '' }
        return "$sha".Trim()
    } catch { return '' }
}

function Get-RunningCommit {
    # Short sha the CURRENT processes were launched from, or '' if unknown
    # (app started before this stamping existed, or by some other route).
    if (-not (Test-Path $stampFile)) { return '' }
    try { return (Get-Content $stampFile -First 1).Trim() } catch { return '' }
}

function Test-WorkingTreeDirty {
    try {
        $out = (& git -C $repo status --porcelain 2>$null)
        if ($LASTEXITCODE -ne 0) { return $false }
        return [bool]("$out".Trim())
    } catch { return $false }
}

function Start-App {
    if (-not (Test-Path $py)) {
        throw "venv python not found at $py - run 'uv sync' first."
    }
    # No-spaces assumption keeps the cmd redirection quoting-free and reliable.
    # (This repo path has none. If it ever moves under a spaced path, use
    #  register_autostart.ps1 instead - it quotes properly.)
    if ("$py$repo$logs" -match '[\s&|()^%!;]') {
        throw "A path contains a space or cmd metacharacter; use scripts\register_autostart.ps1 instead."
    }
    New-Item -ItemType Directory -Force -Path $logs | Out-Null
    # Cap runaway logs: a persistent worker error prints every poll; rotate at 5 MB.
    foreach ($s in $services) {
        $logPath = Join-Path $logs $s.Log
        if ((Test-Path $logPath) -and ((Get-Item $logPath).Length -gt 5MB)) {
            Move-Item -Force $logPath "$logPath.old"
        }
    }

    Write-Host "Starting Vercillo Analytics..." -ForegroundColor Cyan
    $skipped = $false
    foreach ($s in $services) {
        $existing = Get-ServiceProcs $s
        if ($existing) {
            Write-Host ("  {0,-7} already running (PID {1}) - left as is" -f `
                $s.Name, ($existing.ProcessId -join ', ')) -ForegroundColor Yellow
            $skipped = $true
            continue
        }
        $logPath = Join-Path $logs $s.Log
        # cmd /c ... 1>> log 2>&1  -> detached, merged, appended log.
        $inner = "/c $py $($s.Script) $($s.AppArgs) 1>> $logPath 2>&1"
        Start-Process -FilePath $env:ComSpec -ArgumentList $inner `
            -WorkingDirectory $repo -WindowStyle Hidden
        Write-Host ("  {0,-7} launched" -f $s.Name) -ForegroundColor Green
    }

    # Stamp what these processes loaded - but ONLY if every one of them was
    # actually launched just now. A 'start' that left a running webapp alone
    # would otherwise stamp HEAD onto a process still serving older code, which
    # is precisely the false all-clear this stamp exists to prevent. Leaving the
    # old stamp makes 'status' say STALE, which is the conservative answer.
    $head = Get-HeadCommit
    if ($head -and -not $skipped) {
        Set-Content -Path $stampFile -Value $head -Encoding ascii
    }

    # Nudge the tunnel service only if it is down (needs elevation - report if so).
    $tunnel = Get-TunnelStatus
    if ($tunnel -eq 'Stopped') {
        try {
            Start-Service cloudflared -ErrorAction Stop
            Write-Host "  Tunnel  started" -ForegroundColor Green
        } catch {
            Write-Host "  Tunnel  is stopped - start it elevated:" -ForegroundColor Yellow
            Write-Host "          Start-Service cloudflared   (Run as administrator)" -ForegroundColor Yellow
        }
    }

    Write-Host "`nWaiting for the webapp to answer on :8000..." -NoNewline
    $up = $false
    foreach ($i in 1..15) {
        if (Test-Health) { $up = $true; break }
        Start-Sleep -Seconds 1
        Write-Host '.' -NoNewline
    }
    Write-Host ''
    Show-Status
    if ($up) {
        Write-Host "`nApp is UP - local http://127.0.0.1:8000  |  public $publicUrl" -ForegroundColor Green
    } else {
        Write-Host "`nWebapp did not answer in 15s - check logs\webapp.log" -ForegroundColor Red
    }
}

function Stop-App {
    Write-Host "Stopping Vercillo Analytics..." -ForegroundColor Cyan
    $any = $false
    foreach ($s in $services) {
        $procs = Get-ServiceProcs $s
        if (-not $procs) {
            Write-Host ("  {0,-7} not running" -f $s.Name) -ForegroundColor DarkGray
            continue
        }
        foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force }
        $any = $true
        Write-Host ("  {0,-7} stopped (PID {1})" -f $s.Name, ($procs.ProcessId -join ', ')) -ForegroundColor Green
    }
    if (-not $any) { Write-Host "  (nothing was running)" -ForegroundColor DarkGray }

    # Back up the cache on every stop - it is the one asset that isn't instantly
    # rebuildable (hours of extraction). WAL-safe backup API; prunes to newest 10.
    # Runs now that writers are stopped; non-fatal so a backup hiccup never
    # blocks shutdown. This is why on-demand running (no nightly task) is safe.
    $backupScript = Join-Path $repo 'scripts\backup_cache.py'
    $db = Join-Path $repo 'data\feature_cache.db'
    if ((Test-Path $py) -and (Test-Path $backupScript) -and (Test-Path $db)) {
        Write-Host "`nBacking up the cache..." -ForegroundColor Cyan
        try {
            & $py $backupScript
            if ($LASTEXITCODE -ne 0) { throw "backup_cache.py exited $LASTEXITCODE" }
        } catch {
            Write-Host "  backup failed (non-fatal): $_" -ForegroundColor Yellow
        }
    }

    Write-Host "`nThe cloudflared tunnel SERVICE is left running (it auto-recovers" -ForegroundColor DarkGray
    Write-Host "on boot). While the app is stopped, $publicUrl returns a 502." -ForegroundColor DarkGray
    Show-Status
}

function Show-Status {
    Write-Host "`n---- status ----------------------------" -ForegroundColor Cyan
    foreach ($s in $services) {
        $procs = Get-ServiceProcs $s
        if ($procs) {
            Write-Host ("  {0,-7} RUNNING  (PID {1})" -f $s.Name, ($procs.ProcessId -join ', ')) -ForegroundColor Green
        } else {
            Write-Host ("  {0,-7} stopped" -f $s.Name) -ForegroundColor Red
        }
    }
    $tunnel = Get-TunnelStatus
    $tunnelColor = 'Green'; if ($tunnel -ne 'Running') { $tunnelColor = 'Red' }
    Write-Host ("  Tunnel  {0}" -f $tunnel) -ForegroundColor $tunnelColor
    if (Test-Health) {
        Write-Host "  Health  :8000/healthz OK" -ForegroundColor Green
    } else {
        Write-Host "  Health  :8000/healthz no response" -ForegroundColor Red
    }

    # Is the RUNNING app the code in the repo? uvicorn runs with reload=False,
    # so this can drift silently for as long as the app stays up.
    $head = Get-HeadCommit
    $running = Get-RunningCommit
    $anyUp = @($services | ForEach-Object { Get-ServiceProcs $_ }) | Where-Object { $_ }
    if (-not $head) {
        Write-Host "  Code    (git unavailable - cannot compare)" -ForegroundColor DarkGray
    } elseif (-not $anyUp) {
        Write-Host ("  Code    repo at {0} (nothing running)" -f $head) -ForegroundColor DarkGray
    } elseif (-not $running) {
        Write-Host ("  Code    UNKNOWN - started outside deploy; repo is at {0}" -f $head) -ForegroundColor Yellow
        Write-Host "          restart to be sure:  deploy_app.bat" -ForegroundColor Yellow
    } elseif ($running -eq $head) {
        Write-Host ("  Code    up to date ({0})" -f $head) -ForegroundColor Green
    } else {
        Write-Host ("  Code    STALE - serving {0}, repo is at {1}" -f $running, $head) -ForegroundColor Red
        Write-Host "          the app does NOT hot-reload; run:  deploy_app.bat" -ForegroundColor Red
    }
    Write-Host "----------------------------------------" -ForegroundColor Cyan
    Write-Host "Deep check any time: uv run .claude\skills\app-verify\verify_app.py" -ForegroundColor DarkGray
}

function Deploy-App {
    <#
      One click from "I committed a fix" to "the public site serves it":
      pull, sync deps if the lock moved, restart, verify.

      Deliberately NOT folded into 'start': pulling is a network action with an
      opinion about which code should run, and 'start' must stay the dumb,
      idempotent, offline-safe verb it is today.
    #>
    Write-Host "Deploying Vercillo Analytics..." -ForegroundColor Cyan
    $before = Get-HeadCommit

    if (Test-WorkingTreeDirty) {
        # Uncommitted work is a normal state here, and a pull would either fail
        # or quietly rebase around it. Deploy what is checked out and say so.
        Write-Host "  Pull    SKIPPED - working tree has uncommitted changes" -ForegroundColor Yellow
        Write-Host "          deploying what is checked out locally" -ForegroundColor Yellow
    } else {
        Write-Host "  Pull    git pull --ff-only ..." -ForegroundColor Gray
        try {
            & git -C $repo pull --ff-only 2>&1 | ForEach-Object { Write-Host "          $_" -ForegroundColor DarkGray }
            if ($LASTEXITCODE -ne 0) { throw "git pull exited $LASTEXITCODE" }
        } catch {
            # Offline, or the branch diverged. Local commits are still worth
            # deploying, so this warns instead of aborting.
            Write-Host "  Pull    FAILED ($_)" -ForegroundColor Yellow
            Write-Host "          continuing with the local checkout" -ForegroundColor Yellow
        }
    }

    $after = Get-HeadCommit
    if ($before -and $after -and ($before -ne $after)) {
        Write-Host ("  Pull    {0} -> {1}" -f $before, $after) -ForegroundColor Green
        # Dependencies can move with the code; a restart into a stale venv fails
        # in ways that look like application bugs.
        $changed = (& git -C $repo diff --name-only "$before..$after" 2>$null)
        if ("$changed" -match 'uv\.lock|pyproject\.toml') {
            Write-Host "  Deps    lockfile moved - uv sync ..." -ForegroundColor Gray
            try {
                & uv sync 2>&1 | Select-Object -Last 3 | ForEach-Object { Write-Host "          $_" -ForegroundColor DarkGray }
            } catch {
                Write-Host "  Deps    uv sync failed: $_" -ForegroundColor Red
                Write-Host "          fix this before the restart, or the app starts into a stale venv." -ForegroundColor Red
                return
            }
        }
    }

    # Skip the downtime when there is genuinely nothing to deploy.
    $running = Get-RunningCommit
    $anyUp = @($services | ForEach-Object { Get-ServiceProcs $_ }) | Where-Object { $_ }
    if ($anyUp -and $running -and $after -and ($running -eq $after) -and (Test-Health)) {
        Write-Host "`nAlready serving $after and healthy - no restart needed." -ForegroundColor Green
        Show-Status
        return
    }

    Stop-App
    Start-Sleep -Seconds 2
    Start-App
}

switch ($Action) {
    'start'   { Start-App }
    'stop'    { Stop-App }
    'restart' { Stop-App; Start-Sleep -Seconds 2; Start-App }
    'status'  { Show-Status }
    'deploy'  { Deploy-App }
}
