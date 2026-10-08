from __future__ import annotations

from pathlib import Path

import cadquery as cq


def export_step(shape: cq.Workplane | cq.Assembly, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(shape, cq.Assembly):
        shape.save(str(path), "STEP")
    else:
        cq.exporters.export(shape, str(path), "STEP")
    return path
