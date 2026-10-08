# Startet Backend und Frontend (Proxy /api -> Backend)
param([int]$ApiPort = 8000, [int]$WebPort = 5173)
$root = Split-Path -Parent $PSScriptRoot
$backend = Start-Process -PassThru -NoNewWindow -WorkingDirectory "$root\backend" uv -ArgumentList "run uvicorn app.main:app --reload --port $ApiPort"
try {
    Set-Location "$root\frontend"
    $env:API_TARGET = "http://127.0.0.1:$ApiPort"
    npm run dev -- --port $WebPort --strictPort
} finally {
    Stop-Process -Id $backend.Id -ErrorAction SilentlyContinue
}
