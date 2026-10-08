"""Erzeugt synthetische Testfotos (Draufsicht + Seitenansicht eines Quaders) nach docs/samples/."""
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from tests.synth import camera, render, rot_rect  # noqa: E402

L, W, T = 150.0, 38.0, 14.0
out = ROOT / "docs" / "samples"
out.mkdir(parents=True, exist_ok=True)
top = render(rot_rect(140, 110, L, W, 25), T, camera(offset=(-10, 5)), seed=1)
side = render(rot_rect(160, 100, L, T, -15), W, camera(offset=(5, -10)), seed=2)
cv2.imwrite(str(out / "synthetic_top.jpg"), top, [cv2.IMWRITE_JPEG_QUALITY, 92])
cv2.imwrite(str(out / "synthetic_side.jpg"), side, [cv2.IMWRITE_JPEG_QUALITY, 92])
print("ok", out)
