<#
app_control.ps1 - start / stop / status the local app processes (SELF_HOSTING section 4).

    powershell -ExecutionPolicy Bypass -File scripts\app_control.ps1 -Action <start|stop|status|restart>

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
logs\webapp.log / logs\worker.log (gitignored). 'stop' finds them by their
command line (the script filename), so it targets only this app's Python.

ASCII-only on purpose: Windows PowerShell 5.1 reads a BOM-less file as ANSI, so
non-ASCII punctuation would corrupt the parse.
#>

param(
    [ValidateSet('start', 'stop', 'status', 'restart')]
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
    [pscustomobject]@{ Name = 'Worker'; Match = 'run_extraction_worker.py';
        Script = (Join-Path $repo 'scripts\run_extraction_worker.py'); AppArgs = '--loop --interval 30'; Log = 'worker.log' }
)

function Get-ServiceProcs($match) {
    Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
        Where-Object { $_.CommandLine -and ($_.CommandLine -like "*$match*") }
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

function Start-App {
    if (-not (Test-Path $py)) {
        throw "venv python not found at $py - run 'uv sync' first."
    }
    # No-spaces assumption keeps the cmd redirection quoting-free and reliable.
    # (This repo path has none. If it ever moves under a spaced path, use
    #  register_autostart.ps1 instead - it quotes properly.)
    if ("$py$repo$logs" -match '\s') {
        throw "A path contains a space; use scripts\register_autostart.ps1 instead."
    }
    New-Item -ItemType Directory -Force -Path $logs | Out-Null

    Write-Host "Starting Vercillo Analytics..." -ForegroundColor Cyan
    foreach ($s in $services) {
        $existing = Get-ServiceProcs $s.Match
        if ($existing) {
            Write-Host ("  {0,-7} already running (PID {1}) - left as is" -f `
                $s.Name, ($existing.ProcessId -join ', ')) -ForegroundColor Yellow
            continue
        }
        $logPath = Join-Path $logs $s.Log
        # cmd /c ... 1>> log 2>&1  -> detached, merged, appended log.
        $inner = "/c $py $($s.Script) $($s.AppArgs) 1>> $logPath 2>&1"
        Start-Process -FilePath $env:ComSpec -ArgumentList $inner `
            -WorkingDirectory $repo -WindowStyle Hidden
        Write-Host ("  {0,-7} launched" -f $s.Name) -ForegroundColor Green
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
        $procs = Get-ServiceProcs $s.Match
        if (-not $procs) {
            Write-Host ("  {0,-7} not running" -f $s.Name) -ForegroundColor DarkGray
            continue
        }
        foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force }
        $any = $true
        Write-Host ("  {0,-7} stopped (PID {1})" -f $s.Name, ($procs.ProcessId -join ', ')) -ForegroundColor Green
    }
    if (-not $any) { Write-Host "  (nothing was running)" -ForegroundColor DarkGray }
    Write-Host "`nThe cloudflared tunnel SERVICE is left running (it auto-recovers" -ForegroundColor DarkGray
    Write-Host "on boot). While the app is stopped, $publicUrl returns a 502." -ForegroundColor DarkGray
    Show-Status
}

function Show-Status {
    Write-Host "`n---- status ----------------------------" -ForegroundColor Cyan
    foreach ($s in $services) {
        $procs = Get-ServiceProcs $s.Match
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
    Write-Host "----------------------------------------" -ForegroundColor Cyan
    Write-Host "Deep check any time: uv run .claude\skills\app-verify\verify_app.py" -ForegroundColor DarkGray
}

switch ($Action) {
    'start'   { Start-App }
    'stop'    { Stop-App }
    'restart' { Stop-App; Start-Sleep -Seconds 2; Start-App }
    'status'  { Show-Status }
}
