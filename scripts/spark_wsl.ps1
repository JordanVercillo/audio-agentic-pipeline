<#
.SYNOPSIS
    Run a project Python script under REAL Linux Spark, inside WSL2.

.WHY
    Two reasons this exists instead of just calling python on Windows:

    1. hadoop.dll. On Windows, any Spark read of the local filesystem reaches
       Hadoop's NativeIO$Windows.access0, which lives in hadoop.dll. Apache
       publishes no official Windows Hadoop binaries, and FileUtil.canRead
       catches IOException but not Error — so the missing DLL kills the
       globber's pool thread and the driver waits on a future FOREVER. It
       presents as a job that hangs with no output, not as a crash. The owner
       rejected an unsigned community DLL (2026-07-29); WSL2 has no such
       native path at all. See docs/SCALING.md.

    2. Journal #62 — the Anaconda shadow. This machine has a second toolchain:
       SPARK_HOME pointed at Spark 3.5.6 and both PYSPARK_*_PYTHON at
       anaconda3\python.exe, so Spark WORKERS would launch the wrong
       interpreter even under `uv run`. Inheriting the ambient environment is
       the bug; this script PINS every one of those variables explicitly.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\spark_wsl.ps1 -Setup
    powershell -ExecutionPolicy Bypass -File scripts\spark_wsl.ps1 spark/parity_check.py

.NOTES
    All bash is base64-encoded before crossing the shell boundary — it makes
    the call immune to PowerShell/bash quoting AND to CRLF line endings, which
    would otherwise break any .sh file living on the Windows filesystem.
#>
[CmdletBinding()]
param(
    # Repo-relative script to run under Spark (default: the parity check).
    [Parameter(Position = 0)]
    [string]$Script = "spark/parity_check.py",

    # Provision the WSL toolchain (idempotent — safe to re-run).
    [switch]$Setup,

    # WSL distro name.
    [string]$Distro = "Ubuntu"
)

$ErrorActionPreference = "Stop"
$env:WSL_UTF8 = "1"

# The repo as WSL sees it: C:\foo\bar -> /mnt/c/foo/bar
$repoWin = (Resolve-Path "$PSScriptRoot\..").Path
$repoWsl = "/mnt/" + $repoWin.Substring(0, 1).ToLower() + $repoWin.Substring(2).Replace("\", "/")

# NOTE: deliberately returns nothing. A PowerShell function returns EVERYTHING
# written to the output stream, so `return $LASTEXITCODE` would hand back the
# entire Spark log with the code appended — which silently reported a PASSING
# parity run as FAILED. $LASTEXITCODE is automatic and survives the call, so
# callers read it directly.
function Invoke-Wsl([string]$BashScript) {
    $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($BashScript))
    & wsl.exe -d $Distro --user root -- bash -c "echo $b64 | base64 -d | bash"
}

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw "wsl.exe not found. See docs/SCALING.md for the WSL2 setup."
}

if ($Setup) {
    Write-Host "Provisioning $Distro for Spark (JDK 17 + pyspark pinned to the project)..."
    $setup = @'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq openjdk-17-jdk-headless python3-venv python3-pip
python3 -m venv ~/.venv-spark
~/.venv-spark/bin/pip install -q --upgrade pip
# pyspark MUST match the project pin (pyproject.toml) or parity proves nothing.
~/.venv-spark/bin/pip install -q "pyspark==4.1.2" "pandas>=2" "pyarrow>=15" numpy \
                                 matplotlib scikit-learn umap-learn
java -version 2>&1
~/.venv-spark/bin/python -c "import pyspark; print('pyspark', pyspark.__version__)"
echo SETUP_OK
'@
    Invoke-Wsl $setup
    if ($LASTEXITCODE -ne 0) { throw "WSL setup failed (exit $LASTEXITCODE)" }
    Write-Host "Setup complete." -ForegroundColor Green
    exit 0
}

# ── run ──────────────────────────────────────────────────────────────────────
# Every Spark-relevant variable is SET here, never inherited (journal #62).
$run = @"
set -uo pipefail
cd '$repoWsl'
unset SPARK_HOME || true                 # pyspark bundles its own jars
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export PYSPARK_PYTHON=`$HOME/.venv-spark/bin/python
export PYSPARK_DRIVER_PYTHON=`$PYSPARK_PYTHON
export PYTHONPATH='$repoWsl'
export PYTHONIOENCODING=utf-8
if [ ! -x "`$PYSPARK_PYTHON" ]; then
  echo "WSL Spark env missing — run: scripts\spark_wsl.ps1 -Setup" >&2
  exit 127
fi
echo "java=`$(java -version 2>&1 | head -1)"
echo "SPARK_HOME=`${SPARK_HOME:-(unset)}  PYSPARK_PYTHON=`$PYSPARK_PYTHON"
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
