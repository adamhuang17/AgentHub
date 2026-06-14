$Url = if ($env:AGENTHUB_API_BASE_URL) { $env:AGENTHUB_API_BASE_URL } else { "http://127.0.0.1:8000" }
try { Invoke-WebRequest "$Url/health" -UseBasicParsing | Select-Object -ExpandProperty Content } catch { Write-Error "api_unreachable: $Url"; exit 1 }
