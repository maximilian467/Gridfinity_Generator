"""Einlage aufbauen: Grundkörper minus Cutter, plus Farbteile."""
from __future__ import annotations

from dataclasses import dataclass, field

import cadquery as cq

from ..schemas import InsertSpec, ObjectSpec
from .checks import Checks, check_shape
from .color_parts import split_color_parts
from .cutters import cut_all, fuse_all, grip_cutter, prism
from .gridfinity import make_bin
from .layout import Layout, Shelf, compute_layout

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
    g: dict[str, list[cq.Shape]] = {"pocket": [], "grip": [], "compartment": [], "text": []}
    for p in lay.pieces:
        g["pocket"] += prism(p.poly, p.z0, top)
    for gr in lay.grips:
        g["grip"] += grip_cutter(gr, top)
    for c in lay.comps:
        g["compartment"] += prism(c.poly, c.z0, top)
    for t in lay.texts:
        if t.spec.style == "engraved":
            g["text"] += prism(t.poly, t.z0, top)
    return g


RAISED_SEAT = 0.2      # erhabene Schrift reicht so weit in die Oberfläche (sichere Verbindung)


def raised_text(lay: Layout) -> list[cq.Shape]:
    out: list[cq.Shape] = []
    for t in lay.texts:
        if t.spec.style == "raised":
            out += prism(t.poly, t.z0 - RAISED_SEAT, t.z1)
    return out


def shelf_solid(sh: Shelf) -> list[cq.Shape]:
    """Vordach als Prisma über die ganze Wandlänge (Profil: oben eben, Vorderkante SHELF_T stark,
    darunter 45° zur Wand), auf das Fach zugeschnitten (abgerundete Ecken)."""
    from .layout import SHELF_T

    x0, y0, x1, y1 = sh.comp_poly.bounds
    d, zt, zb = sh.depth, sh.z_top, sh.z_bottom
    if sh.side in ("back", "front"):
        w = y1 if sh.side == "back" else y0
        s = -1 if sh.side == "back" else 1
        prof = [(w, zt), (w + s * d, zt), (w + s * d, zt - SHELF_T), (w, zb)]
        solid = cq.Workplane("YZ").polyline(prof).close().extrude(x1 - x0 + 2).val()
        bb = solid.BoundingBox()
        solid = solid.translate(cq.Vector(x0 - 1 - bb.xmin, 0, 0))
    else:
        w = x0 if sh.side == "left" else x1
        s = 1 if sh.side == "left" else -1
        prof = [(w, zt), (w + s * d, zt), (w + s * d, zt - SHELF_T), (w, zb)]
        solid = cq.Workplane("XZ").polyline(prof).close().extrude(y1 - y0 + 2).val()
        bb = solid.BoundingBox()
        solid = solid.translate(cq.Vector(0, y0 - 1 - bb.ymin, 0))
    clip = fuse_all(prism(sh.comp_poly.buffer(0.01), zb - 0.5, zt + 0.01))
    if clip is None:
        return []
    return cq.Workplane("XY").add(solid).intersect(clip).solids().vals()


def build_insert(spec: InsertSpec, objects: dict[str, ObjectSpec]) -> InsertResult:
    lay = compute_layout(spec, objects)
    base = make_bin(lay.grid_x, lay.grid_y, lay.height_u, stacking_lip=lay.lip,
                    magnets=spec.magnets)
    groups = cutter_groups(lay)
    body = cut_all(base, sum(groups.values(), []))
    adds = raised_text(lay)
    for sh in lay.shelves:
        adds += shelf_solid(sh)
    for t in lay.comp_labels:
        adds += prism(t.poly, t.z0 - RAISED_SEAT, t.z1)
    add = fuse_all(adds)
    if add is not None:
        body = body.union(add).clean()
    parts = split_color_parts(body, lay, spec)
    checks = check_shape(body)
    pc = {p.name: bool(p.shape.val().isValid()) for p in parts}
    total = sum(p.shape.val().Volume() for p in parts)
    vol_ok = abs(total - body.val().Volume()) <= 1e-3 * body.val().Volume()
    res = InsertResult(lay, body, parts, checks, pc, vol_ok, list(lay.warnings))
    if not vol_ok:
        res.warnings.append("Teilvolumen-Summe weicht vom Gesamtvolumen ab")
    return res
