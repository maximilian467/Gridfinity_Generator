from __future__ import annotations

import zipfile
from pathlib import Path

from .glb import part_mesh


def write_parts_zip(parts, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for i, p in enumerate(parts):
            z.writestr(f"{i + 1}_{p.name}.stl", part_mesh(p.shape).export(file_type="stl"))
    return path
