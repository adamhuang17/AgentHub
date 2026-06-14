$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Web = Join-Path $Root "apps/web"
if (-not (Test-Path (Join-Path $Web "packages/opencode/package.json"))) { Write-Error "agenthub_coding_runtime_missing"; exit 1 }
if (-not (Get-Command bun -ErrorAction SilentlyContinue)) { Write-Error "bun_not_installed"; exit 1 }
Set-Location $Web
Write-Host "starting_agenthub_coding_runtime http://127.0.0.1:4096"
bun run --cwd packages/opencode --conditions=browser src/index.ts serve --hostname 127.0.0.1 --port 4096 --cors http://127.0.0.1:3000 --cors http://localhost:3000
