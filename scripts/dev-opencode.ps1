$ErrorActionPreference = "Stop"
Write-Host "Compatibility alias. Prefer .\scripts\dev-agent-runtime.ps1."
& (Join-Path $PSScriptRoot "dev-agent-runtime.ps1")
