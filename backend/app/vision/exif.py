"""Bild laden (EXIF-Orientierung), Brennweite (35mm-äquivalent)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

FOCAL_35MM_TAG = 0xA405
EXIF_IFD = 0x8769


def load_image(path: str | Path) -> tuple[np.ndarray, float | None]:
    """Gibt (BGR-Bild in Originalauflösung, 35mm-äquivalente Brennweite oder None) zurück."""
    img = Image.open(path)
    f35 = None
    try:
        exif = img.getexif()
        v = exif.get_ifd(EXIF_IFD).get(FOCAL_35MM_TAG) or exif.get(FOCAL_35MM_TAG)
        if v:
            f35 = float(v)
    except Exception:
        f35 = None
    img = ImageOps.exif_transpose(img).convert("RGB")
    return np.asarray(img)[:, :, ::-1].copy(), f35
