"""Einlage aufbauen: Grundkörper minus Cutter, plus Farbteile."""
from __future__ import annotations

from dataclasses import dataclass, field

import cadquery as cq

from ..schemas import InsertSpec, ObjectSpec
from .checks import Checks, check_shape
from .color_parts import split_color_parts
from .cutters import cut_all, grip_cutter, prism
from .gridfinity import make_bin
from .layout import Layout, compute_layout

TOP_EXTRA = 5.0


@dataclass
class Part:
    name: str
    shape: cq.Workplane
    slot: int
    group: str


@dataclass
class InsertResult:
    layout: Layout
    body: cq.Workplane           # vereinigter Körper
    parts: list[Part]
    checks: Checks
    part_checks: dict[str, bool] = field(default_factory=dict)
    volume_sum_ok: bool = True
    warnings: list[str] = field(default_factory=list)


def cutter_groups(lay: Layout) -> dict[str, list[cq.Shape]]:
    top = lay.z_surface + TOP_EXTRA
    g: dict[str, list[cq.Shape]] = {"pocket": [], "grip": [], "compartment": []}
    for p in lay.pieces:
        g["pocket"] += prism(p.poly, p.z0, top)
    for gr in lay.grips:
        g["grip"] += grip_cutter(gr, top)
    for c in lay.comps:
        g["compartment"] += prism(c.poly, c.z0, top)
    return g


def build_insert(spec: InsertSpec, objects: dict[str, ObjectSpec]) -> InsertResult:
    lay = compute_layout(spec, objects)
    base = make_bin(lay.grid_x, lay.grid_y, lay.height_u, stacking_lip=spec.stacking_lip,
                    magnets=spec.magnets)
    groups = cutter_groups(lay)
    body = cut_all(base, sum(groups.values(), []))
    parts = split_color_parts(body, lay, spec)
    checks = check_shape(body)
    pc = {p.name: bool(p.shape.val().isValid()) for p in parts}
    total = sum(p.shape.val().Volume() for p in parts)
    vol_ok = abs(total - body.val().Volume()) <= 1e-3 * body.val().Volume()
    res = InsertResult(lay, body, parts, checks, pc, vol_ok, list(lay.warnings))
    if not vol_ok:
        res.warnings.append("Teilvolumen-Summe weicht vom Gesamtvolumen ab")
    return res
