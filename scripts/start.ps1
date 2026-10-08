# Produktiv-lokal: Frontend bauen und alles ueber einen Prozess ausliefern (http://localhost:8000)
param([int]$Port = 8000)
$root = Split-Path -Parent $PSScriptRoot
Set-Location "$root\frontend"
npm run build
Set-Location "$root\backend"
uv run uvicorn app.main:app --port $Port
