"""Passform-Test: 3 mm Platte (Bin-Außenmaß, ohne Füße) mit durchgehenden Taschenkonturen."""
from __future__ import annotations

import cadquery as cq

from ..geometry.cutters import cut_all, prism
from ..geometry.gridfinity import BIN_RADIUS, bin_outer
from ..geometry.layout import Layout

THICKNESS = 3.0


def make_fit_test(lay: Layout) -> cq.Workplane:
    ox, oy = bin_outer(lay.grid_x, lay.grid_y)
    plate = (cq.Workplane("XY").box(ox, oy, THICKNESS, centered=False)
             .edges("|Z").fillet(BIN_RADIUS))
    shapes = []
    for p in lay.pieces:
        shapes += prism(p.poly, -1, THICKNESS + 1)
    return cut_all(plate, shapes)
