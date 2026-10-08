# Entwicklung: Backend (uvicorn --reload) + Frontend (vite). Ports werden automatisch frei gewaehlt
# (Backend ab 8003, Frontend ab 5183), oder per -ApiPort / -WebPort vorgeben.
param([int]$ApiPort = 0, [int]$WebPort = 0)
. "$PSScriptRoot\ports.ps1"
$root = Split-Path -Parent $PSScriptRoot
if ($ApiPort -eq 0) { $ApiPort = Get-FreePort 8003 }
if ($WebPort -eq 0) { $WebPort = Get-FreePort 5183 }
Write-Host "Backend  http://127.0.0.1:$ApiPort"
Write-Host "Frontend http://localhost:$WebPort   <- hier oeffnen"
$backend = Start-Process -PassThru -NoNewWindow -WorkingDirectory "$root\backend" uv -ArgumentList "run uvicorn app.main:app --reload --reload-dir app --port $ApiPort"
try {
    Set-Location "$root\frontend"
    $env:API_TARGET = "http://127.0.0.1:$ApiPort"
    npm run dev -- --port $WebPort --strictPort
} finally {
    Stop-Process -Id $backend.Id -ErrorAction SilentlyContinue
}
