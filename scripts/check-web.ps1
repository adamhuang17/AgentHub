if (-not (Get-Command bun -ErrorAction SilentlyContinue)) { Write-Error "bun_not_installed"; exit 1 }
$Root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $Root "apps/web")
bun --cwd packages/app typecheck
