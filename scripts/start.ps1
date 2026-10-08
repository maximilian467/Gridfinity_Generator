# Produktiv-lokal: Frontend bauen, alles ueber einen Prozess ausliefern.
# Port wird automatisch frei gewaehlt (ab 8003) oder per -Port vorgegeben.
param([int]$Port = 0)
. "$PSScriptRoot\ports.ps1"
$root = Split-Path -Parent $PSScriptRoot
if ($Port -eq 0) { $Port = Get-FreePort 8003 }
Set-Location "$root\frontend"
npm run build
Write-Host "`nOeffnen: http://localhost:$Port"
Set-Location "$root\backend"
uv run uvicorn app.main:app --port $Port
