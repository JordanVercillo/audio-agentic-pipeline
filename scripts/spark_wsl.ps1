<#
.SYNOPSIS
    Run a project Python script under REAL Linux Spark, inside WSL2.

.WHY
    1. hadoop.dll / winutils.exe. Hadoop's RawLocalFileSystem shells out to
       winutils.exe on Windows for any local-file WRITE, and NativeIO$Windows
       .access0 (in hadoop.dll) for globbing on READ. Apache publishes no
       official Windows Hadoop binaries; the owner rejected an unsigned
       community DLL (2026-07-29) and the Windows install was removed
       (8f2d76b). Our transforms DO write parquet (feature_transform.py,
       temporal_aggregate.py), so the Spark path here is WSL-only by design,
       not by preference. Note the read failure mode is a SILENT HANG, not an
       error: FileUtil.canRead catches IOException but not Error, so the
       globber's pool thread dies and the driver waits on a future forever.

    2. Journal #62 — the Anaconda shadow. This machine had SPARK_HOME pointing
       at a second Spark and both PYSPARK_*_PYTHON at anaconda3\python.exe, so
       workers launched the wrong interpreter even under `uv run`. Inheriting
       the ambient environment is the bug. This script OVERRIDES every
       Spark-relevant variable rather than inheriting or defaulting them.

.VERSION SOURCES (deliberately single, after a cross-repo review 2026-07-30)
    pyspark version : read from uv.lock  (was hardcoded here = a second
                      encoding that would silently drift from the project)
    python minor    : read from .venv/pyvenv.cfg, so WSL matches the Windows
                      interpreter. Without this the two hosts ran 3.14 vs
                      3.12 and "works in WSL, not Windows" was uninterpretable.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\spark_wsl.ps1 -Setup
    powershell -ExecutionPolicy Bypass -File scripts\spark_wsl.ps1 spark/parity_check.py
    powershell -ExecutionPolicy Bypass -File scripts\spark_wsl.ps1 spark/known_answer_check.py

.NOTES
    All bash is base64-encoded across the shell boundary. .gitattributes now
    fixes line endings for committed .sh files, but the base64 hop ALSO
    defends against PowerShell/bash quoting, which broke this script twice
    while it was being written. Kept deliberately.

    Runs as the WSL default user (jordan), NOT root. Root has a separate
    toolchain, rc files and venv from everything else on the machine, which is
    the two-toolchains trap this repo already paid for once.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Script = "spark/parity_check.py",
    [switch]$Setup,
    [string]$Distro = "Ubuntu",
    [string]$WslUser = "jordan"
)

$ErrorActionPreference = "Stop"
$env:WSL_UTF8 = "1"

$repoWin = (Resolve-Path "$PSScriptRoot\..").Path
$repoWsl  = "/mnt/" + $repoWin.Substring(0, 1).ToLower() + $repoWin.Substring(2).Replace("\", "/")
$venvName = "audio-agentic-pipeline"   # lives under ~/.venvs in the WSL user's home

# ── the single sources of truth ─────────────────────────────────────────────
$lock = Join-Path $repoWin "uv.lock"
$pysparkVersion = $null
$lines = Get-Content $lock
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^name = "pyspark"$') {
        for ($j = $i; $j -lt [Math]::Min($i + 5, $lines.Count); $j++) {
            if ($lines[$j] -match '^version = "(.+)"$') { $pysparkVersion = $Matches[1]; break }
        }
        break
    }
}
if (-not $pysparkVersion) { throw "could not read the pyspark version from uv.lock" }

$pyMinor = $null
$cfg = Join-Path $repoWin ".venv\pyvenv.cfg"
if (Test-Path $cfg) {
    $vi = (Get-Content $cfg | Where-Object { $_ -match '^version_info\s*=' })
    if ($vi -match '(\d+)\.(\d+)\.') { $pyMinor = "$($Matches[1]).$($Matches[2])" }
}
if (-not $pyMinor) { $pyMinor = "3.12" }   # fall back to the CI interpreter

function Invoke-Wsl([string]$BashScript) {
    # Deliberately returns NOTHING. A PowerShell function returns everything
    # written to its output stream, so `return $LASTEXITCODE` hands back the
    # entire Spark log with the code appended — which once reported a PASSING
    # parity run as FAILED. $LASTEXITCODE is automatic and survives the call.
    $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($BashScript))
    # PowerShell 5.1 wraps a native command's STDERR in an ErrorRecord, so with
    # $ErrorActionPreference='Stop' any tool that logs progress to stderr (uv's
    # installer, java, spark) kills the script even on exit 0. We gate on
    # $LASTEXITCODE instead, so relax the preference just for this call.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & wsl.exe -d $Distro --user $WslUser -- bash -c "echo $b64 | base64 -d | bash"
    } finally {
        $ErrorActionPreference = $prev
    }
}

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw "wsl.exe not found. See docs/SCALING.md for the WSL2 setup."
}

if ($Setup) {
    Write-Host "Provisioning $Distro/$WslUser : python $pyMinor + pyspark $pysparkVersion (from uv.lock)"
    # NOT $setup: PowerShell variables are CASE-INSENSITIVE, so `$setup` and the
    # `[switch]$Setup` parameter are the same variable — assigning this string
    # to it throws "Cannot convert ... to SwitchParameter" before anything runs.
    $setupScript = @"
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
if ! dpkg -s openjdk-17-jdk-headless >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq openjdk-17-jdk-headless curl
fi
# uv gives us a managed CPython, so the WSL interpreter can MATCH Windows.
# Ubuntu's apt python is whatever the distro ships (3.14 here) and there is no
# apt path back to an older minor.
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="`$HOME/.local/bin:`$PATH"
# Absolute path, built in bash. A literal '~' inside a shell VARIABLE is not
# expanded, which is why the earlier `eval echo` dance existed; this removes
# the need for it entirely.
VENV="`$HOME/.venvs/$venvName"
mkdir -p "`$HOME/.venvs"
# --clear makes -Setup genuinely re-runnable; without it uv refuses on an
# existing venv and the whole provisioning step fails on the second run.
uv venv --clear --python $pyMinor "`$VENV"
# Install the PROJECT'S OWN locked dependency set, never a hand-picked list.
# A curated list here was a third encoding of the dependencies and it broke:
# it resolved numba 0.53.1 / llvmlite 0.36.0, which refuse to build on 3.12.
# `uv sync --frozen` uses uv.lock, so WSL gets byte-for-byte what Windows and
# CI get.
#
# UV_PROJECT_ENVIRONMENT is LOAD-BEARING: without it, `uv` run from inside a
# /mnt/c checkout targets ./.venv — the WINDOWS venv — sees a foreign platform
# and rebuilds it as Linux, breaking every Windows `uv run` afterwards.
cd '$repoWsl'
UV_PROJECT_ENVIRONMENT="`$VENV" uv sync --frozen
"`$VENV/bin/python" -c "import sys,pyspark; print('python', sys.version.split()[0], '| pyspark', pyspark.__version__)"
# Guard the trap above rather than trusting it: the Windows venv must still
# declare a Windows interpreter after we are done.
if ! grep -q 'windows' .venv/pyvenv.cfg 2>/dev/null; then
  echo "FATAL: .venv no longer looks like a Windows venv - uv clobbered it" >&2
  exit 1
fi
echo "windows .venv intact"
java -version 2>&1 | head -1
echo SETUP_OK
"@
    Invoke-Wsl $setupScript
    if ($LASTEXITCODE -ne 0) { throw "WSL setup failed (exit $LASTEXITCODE)" }
    Write-Host "Setup complete." -ForegroundColor Green
    exit 0
}

# ── run ─────────────────────────────────────────────────────────────────────
$run = @"
set -uo pipefail
cd '$repoWsl'
# OVERRIDE, never inherit or setdefault (journal #62).
unset SPARK_HOME || true          # pyspark's wheel bundles a complete Spark
unset HADOOP_HOME || true         # a variable that outlives its directory is
                                  # worse than an unset one: pyspark falls back
                                  # to something that works when it is unset.
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export PYSPARK_PYTHON="`$HOME/.venvs/$venvName/bin/python"
export PYSPARK_DRIVER_PYTHON="`$PYSPARK_PYTHON"
export PYTHONPATH='$repoWsl'
export PYTHONIOENCODING=utf-8
if [ ! -x "`$PYSPARK_PYTHON" ]; then
  echo "WSL Spark env missing - run: scripts\spark_wsl.ps1 -Setup" >&2
  exit 127
fi
echo "user=`$(whoami)  java=`$(java -version 2>&1 | head -1)"
echo "python=`$(`$PYSPARK_PYTHON -c 'import sys;print(sys.version.split()[0])')  pyspark=`$(`$PYSPARK_PYTHON -c 'import pyspark;print(pyspark.__version__)')"
echo "SPARK_HOME=`${SPARK_HOME:-(unset)}  HADOOP_HOME=`${HADOOP_HOME:-(unset)}"
echo '--- $Script ---'
`$PYSPARK_PYTHON -u '$Script'
"@

Invoke-Wsl $run
$code = $LASTEXITCODE
if ($code -eq 0) {
    Write-Host "`n$Script PASSED under Linux Spark." -ForegroundColor Green
} else {
    Write-Host "`n$Script FAILED (exit $code)." -ForegroundColor Red
}
exit $code
