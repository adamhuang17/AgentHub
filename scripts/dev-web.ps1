$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Web = Join-Path $Root "apps/web"
if (-not (Test-Path (Join-Path $Web "packages/app/src/pages/agenthub.tsx"))) { Write-Error "agenthub_page_missing"; exit 1 }
if (-not (Get-Command bun -ErrorAction SilentlyContinue)) { Write-Error "bun_not_installed"; exit 1 }
if (Test-Path (Join-Path $Root ".env")) {
  Get-Content (Join-Path $Root ".env") | ForEach-Object {
    if ($_ -match '^\s*#' -or $_ -notmatch '=') { return }
    $pair = $_ -split '=', 2
    if ($pair[0].Trim()) { [Environment]::SetEnvironmentVariable($pair[0].Trim(), $pair[1].Trim(), 'Process') }
  }
}
if (-not $env:VITE_AGENTHUB_API_BASE) {
  if ($env:AGENTHUB_API_BASE_URL) { $env:VITE_AGENTHUB_API_BASE = $env:AGENTHUB_API_BASE_URL }
  else { $env:VITE_AGENTHUB_API_BASE = "http://127.0.0.1:8000" }
}
Set-Location $Web
Write-Host "starting_agenthub_web /agenthub"
Write-Host "VITE_AGENTHUB_API_BASE=$env:VITE_AGENTHUB_API_BASE"
bun --cwd packages/app dev
