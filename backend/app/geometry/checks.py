"""Geometrie-Checks: Gültigkeit, Körperanzahl, Wasserdichtheit, Volumen."""
from __future__ import annotations

from dataclasses import dataclass, field

import cadquery as cq
import trimesh


@dataclass
class Checks:
    valid: bool
    solid_count: int
    volume_mm3: float
    bbox: tuple[float, float, float]
    watertight: bool | None = None
    messages: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.valid and self.solid_count == 1 and self.watertight is not False


def tessellate(shape: cq.Workplane | cq.Shape, tol: float = 0.02, ang: float = 0.2) -> trimesh.Trimesh:
    shp = shape.val() if isinstance(shape, cq.Workplane) else shape
    verts, tris = shp.tessellate(tol, ang)
    mesh = trimesh.Trimesh([(v.x, v.y, v.z) for v in verts], tris, process=True)
    mesh.merge_vertices()
    return mesh


def check_shape(shape: cq.Workplane, *, mesh_check: bool = True) -> Checks:
    shp = shape.val() if isinstance(shape, cq.Workplane) else shape
    solids = shape.solids().vals() if isinstance(shape, cq.Workplane) else shp.Solids()
    bb = shp.BoundingBox()
    c = Checks(valid=bool(shp.isValid()), solid_count=len(solids), volume_mm3=float(shp.Volume()),
               bbox=(bb.xlen, bb.ylen, bb.zlen))
    if mesh_check:
        c.watertight = bool(tessellate(shape).is_watertight)
    if not c.valid:
        c.messages.append("Geometrie ungültig")
    if c.solid_count != 1:
        c.messages.append(f"{c.solid_count} Körper statt 1")
    if c.watertight is False:
        c.messages.append("Netz nicht wasserdicht")
    return c
