$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Test-Path "services/api/app/main.py")) { Write-Error "backend_missing: services/api/app/main.py"; exit 1 }
if (Test-Path ".env") {
  Get-Content ".env" | ForEach-Object {
    if ($_ -match '^\s*#' -or $_ -notmatch '=') { return }
    $pair = $_ -split '=', 2
    if ($pair[0].Trim()) { [Environment]::SetEnvironmentVariable($pair[0].Trim(), $pair[1].Trim(), 'Process') }
  }
}
if (-not $env:PORT) { $env:PORT = "8000" }
if (-not $env:AGENTHUB_DB_PATH) { $env:AGENTHUB_DB_PATH = "var/agenthub.sqlite3" }
if (-not $env:AGENTHUB_ARTIFACT_STORE_DIR) { $env:AGENTHUB_ARTIFACT_STORE_DIR = "var/artifacts" }
if (-not $env:AGENTHUB_STATIC_DEPLOY_DIR) { $env:AGENTHUB_STATIC_DEPLOY_DIR = "var/static-deployments" }
Write-Host "starting_agenthub_api http://127.0.0.1:$env:PORT"
python -B -m services.api.app.main
