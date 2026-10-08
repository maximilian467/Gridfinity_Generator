# Laedt die SAM-2.1-Gewichte (ca. 160 MB, offizielle ultralytics-Release) nach data/models/
$root = Split-Path -Parent $PSScriptRoot
$dir = Join-Path $root "data\models"
New-Item -ItemType Directory -Force $dir | Out-Null
$f = Join-Path $dir "sam2.1_b.pt"
if (-not (Test-Path $f)) {
    Invoke-WebRequest "https://github.com/ultralytics/assets/releases/download/v8.3.0/sam2.1_b.pt" -OutFile $f
}
Write-Host "SAM-Gewichte: $f"
