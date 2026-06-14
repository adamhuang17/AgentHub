$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$required = @(
  "services/api/app/main.py",
  "apps/web/package.json",
  "apps/web/packages/app/src/pages/agenthub.tsx",
  "apps/web/packages/app/src/agenthub/api/agenthub-client.ts",
  "apps/web/packages/opencode/package.json",
  "docs/no-fake-success-policy.md"
)
$failed = $false
foreach ($path in $required) {
  $full = Join-Path $Root $path
  if (Test-Path $full) { Write-Host "ok $path" } else { Write-Host "missing $path"; $failed = $true }
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { Write-Host "missing python"; $failed = $true }
if (-not (Get-Command bun -ErrorAction SilentlyContinue)) { Write-Host "bun_not_installed" }
if ($failed) { exit 1 }
Write-Host "layout_ready"
