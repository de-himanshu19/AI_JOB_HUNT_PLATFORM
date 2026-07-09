param(
    [string]$ConfigPath = "config\daily_searches.local.json"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$LogDir = Join-Path $ProjectRoot "data\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Timestamp = Get-Date -Format "yyyyMMddTHHmmss"
$LogPath = Join-Path $LogDir "daily_run_$Timestamp.log"
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Virtual environment Python not found at $Python. Create .venv and install dependencies first."
}

& $Python -m app.cli daily run-config --config $ConfigPath *> $LogPath
$ExitCode = $LASTEXITCODE

Get-Content $LogPath
exit $ExitCode
