"""Gridfinity-Grundkörper (Bin, Baseplate) als CadQuery-Wrapper um cq-gridfinity.

Koordinaten: Ursprung = linke untere Außenecke, x rechts, y oben, z = 0 Unterkante Füße.
"""
from __future__ import annotations

import cadquery as cq
from cqgridfinity import GridfinityBaseplate, GridfinityBox

PITCH = 42.0
BIN_TOL = 0.5          # Bin-Außenmaß = n*42 - 0.5
UNIT_H = 7.0
FOOT_H = 4.75
LIP_MARGIN = 2.6       # Randbreite des Stapelrands (Cutter-Abstand zur Außenkante)
LIP_H = 3.8            # Höhe des Stapelrands über der Oberfläche (gemessen)
BIN_RADIUS = 3.75


def bin_outer(grid_x: int, grid_y: int) -> tuple[float, float]:
    return grid_x * PITCH - BIN_TOL, grid_y * PITCH - BIN_TOL


def surface_z(height_u: float) -> float:
    return UNIT_H * height_u


def make_bin(grid_x: int, grid_y: int, height_u: float, *, stacking_lip: bool = True,
             magnets: bool = False) -> cq.Workplane:
    """Massiver Bin. Mit Stapelrand: Rand-Ring über z = 7*height_u (Innenraum offen).
    Ohne Stapelrand: bei z = 7*height_u plan abgeschnitten, auch unter 1 U (Blindstopfen: Fuß
    plus dünne Deckplatte; mit Stapelrand gibt es das nicht)."""
    if height_u < 1:
        stacking_lip = False
    # ohne Rand wird ohnehin abgeschnitten: höher rechnen (cq-gridfinity scheitert bei 1 U am Innenraum)
    box = GridfinityBox(grid_x, grid_y, height_u if stacking_lip else max(height_u, 2), solid=True, holes=magnets)
    body = box.render()
    ox, oy = bin_outer(grid_x, grid_y)
    body = body.translate((ox / 2, oy / 2, 0))
    if not stacking_lip:
        keep = (cq.Workplane("XY").box(ox + 10, oy + 10, surface_z(height_u),
                                       centered=(False, False, False)).translate((-5, -5, 0)))
        body = body.intersect(keep)
    return body


def make_baseplate(grid_x: int, grid_y: int, *, magnets: bool = False) -> cq.Workplane:
    plate = GridfinityBaseplate(grid_x, grid_y, corner_screws=False)
    r = plate.render()
    bb = r.val().BoundingBox()
    return r.translate((-bb.xmin, -bb.ymin, -bb.zmin))
