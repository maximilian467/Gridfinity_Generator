import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("GRIDFINITY_DATA") or ROOT / "data")
FRONTEND_DIST = ROOT / "frontend" / "dist"
