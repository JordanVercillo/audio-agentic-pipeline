<#
register_autostart.ps1 — register the app's processes as Scheduled Tasks
(SELF_HOSTING §4): webapp + extraction worker at logon, cache backup nightly
at 03:00. The cloudflared tunnel is already a Windows service — with these
three tasks the whole stack survives a reboot with no operator.

Run from anywhere (no elevation needed — current-user, at-logon tasks):
    powershell -ExecutionPolicy Bypass -File scripts\register_autostart.ps1

Idempotent: re-running replaces the tasks. Remove everything with:
    Get-ScheduledTask "VercilloAnalytics*" | Unregister-ScheduledTask -Confirm:$false

Notes:
- Task output appends to logs\*.log (gitignored) — the ops trail for yt-dlp
  errors etc. PowerShell hides the console after a brief flash.
- If you ALSO start the processes manually in terminals, skip the scheduled
  ones (or stop the consoles before next logon): a second webapp fails to
  bind :8000; a second worker is safe but wasteful.
- ExecutionTimeLimit is explicitly ZERO — the Task Scheduler default silently
  kills tasks after 72 hours, which would take the app down every 3 days.
#>

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "venv python not found at $py - run 'uv sync' first" }
$logs = Join-Path $repo "logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null

# Long-running services: never expire, restart on failure, survive battery.
$serviceSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
# The nightly backup: short job; catch up after wake if 03:00 was missed.
$backupSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)

$logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$nightly = New-ScheduledTaskTrigger -Daily -At 3am

function Register-AppTask {
    param([string]$Name, [string]$Script, [string]$Flags, [string]$Log,
          $Trigger, $Settings)
    $scriptPath = Join-Path $repo $Script
    $logPath = Join-Path $logs $Log
    $psCommand = "& '$py' '$scriptPath' $Flags *>> '$logPath'"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -WindowStyle Hidden -Command `"$psCommand`"" `
        -WorkingDirectory $repo
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $Trigger `
        -Settings $Settings -Force | Out-Null
    Write-Host "registered: $Name"
}

Register-AppTask -Name "VercilloAnalytics Webapp" -Script "scripts\run_webapp.py" `
    -Flags "" -Log "webapp.log" -Trigger $logon -Settings $serviceSettings
Register-AppTask -Name "VercilloAnalytics Worker" -Script "scripts\run_extraction_worker.py" `
    -Flags "--loop --takeover" -Log "worker.log" -Trigger $logon -Settings $serviceSettings
Register-AppTask -Name "VercilloAnalytics Backup" -Script "scripts\backup_cache.py" `
    -Flags "" -Log "backup.log" -Trigger $nightly -Settings $backupSettings

Write-Host "`nAll three tasks registered (start at next logon / 03:00)."
Write-Host "Start the services NOW without waiting for a logon:"
Write-Host '    Start-ScheduledTask "VercilloAnalytics Webapp"'
Write-Host '    Start-ScheduledTask "VercilloAnalytics Worker"'
