from __future__ import annotations

from pathlib import Path

import cadquery as cq

from ..geometry.checks import tessellate


def export_stl(shape: cq.Workplane, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tessellate(shape).export(path)
    return path
