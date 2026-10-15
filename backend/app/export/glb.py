from __future__ import annotations

from pathlib import Path

import cadquery as cq
import trimesh

from ..geometry.checks import tessellate

# Filament-Slot -> Vorschaufarbe (RGBA)
SLOT_COLORS = {1: (200, 200, 205, 255), 2: (230, 120, 30, 255), 3: (60, 130, 220, 255),
               4: (90, 170, 90, 255), 5: (190, 70, 70, 255)}


def part_mesh(shape: cq.Workplane) -> trimesh.Trimesh:
    comp = cq.Compound.makeCompound(shape.solids().vals())
    return tessellate(comp)


def hex_rgba(h: str) -> tuple[int, int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255


def export_glb(parts, path: Path, slot_colors: dict[int, str] | None = None) -> Path:
    scene = trimesh.Scene()
    for p in parts:
        m = part_mesh(p.shape)
        m.visual.face_colors = (hex_rgba(slot_colors[p.slot]) if slot_colors and p.slot in slot_colors
                                else SLOT_COLORS.get(p.slot, (180, 180, 180, 255)))
        scene.add_geometry(m, node_name=p.name, geom_name=p.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    scene.export(path)
    return path
