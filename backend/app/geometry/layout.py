"""2D-Layout der Einlage (nur shapely): Taschenstücke je Zone, Mulden, Fächer, Warnungen."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from ..schemas import GripRecess, InsertSpec, ObjectSpec
from .gridfinity import FOOT_H, LIP_MARGIN, PITCH, bin_outer, surface_z
from .zones import Zone, compute_zones


@dataclass
class Piece:
    poly: object        # shapely (Multi)Polygon im Einlagen-Koordinatensystem
    z0: float           # Cutter-Boden (absolut)
    placement: int
    zone: int


@dataclass
class Layout:
    grid_x: int
    grid_y: int
    height_u: int
    z_surface: float
    pieces: list[Piece] = field(default_factory=list)
    grips: list[tuple[object, float]] = field(default_factory=list)
    comps: list[tuple[object, float, float]] = field(default_factory=list)  # poly, z0, radius
    zones: list[list[Zone]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def outer(self) -> tuple[float, float]:
        return bin_outer(self.grid_x, self.grid_y)

    @property
    def inner(self):
        ox, oy = self.outer
        return box(LIP_MARGIN, LIP_MARGIN, ox - LIP_MARGIN, oy - LIP_MARGIN)

    def pocket_union(self):
        return unary_union([p.poly for p in self.pieces])


def pocket_outline(contour: list[list[float]], cxy: float, cend: float):
    poly = Polygon(contour).buffer(0)
    b = poly.buffer(cxy, join_style=1)
    n = 9 if cend > 0 else 1
    shifts = [-cend + 2 * cend * i / (n - 1) for i in range(n)] if n > 1 else [0.0]
    o = unary_union([affinity.translate(b, dx, 0) for dx in shifts])
    return o.simplify(0.05)


def grip_polygon(g: GripRecess):
    if g.shape == "circle":
        p = Point(0, 0).buffer(g.w / 2, 32)
    elif g.shape == "rect":
        p = box(-g.w / 2, -g.l / 2, g.w / 2, g.l / 2)
    else:  # stadium: Länge l entlang y, Breite w
        half = max(g.l - g.w, 0) / 2
        p = LineString([(0, -half), (0, half)]).buffer(g.w / 2, 24)
    p = affinity.rotate(p, g.rot_deg, origin=(0, 0))
    return affinity.translate(p, g.x, g.y)


def comp_polygon(c):
    r = max(min(c.radius, c.w / 2, c.l / 2), 0.01)
    return box(c.x + r, c.y + r, c.x + c.w - r, c.y + c.l - r).buffer(r, 16)


def _assemble(spec: InsertSpec, objects: dict[str, ObjectSpec], gx: int, gy: int, u: int) -> Layout:
    zs = surface_z(u)
    lay = Layout(gx, gy, u, zs)
    margin = spec.clearance_xy + spec.clearance_end
    for pi, pl in enumerate(spec.placements):
        obj = objects[pl.object_id]
        prof = obj.profile
        zones = compute_zones(prof.s, prof.bottom, obj.length_mm, margin, spec.step_tol,
                              spec.min_zone_len, spec.max_zones, prof.ds)
        lay.zones.append(zones)
        outline = pocket_outline(obj.contour_mm, spec.clearance_xy, spec.clearance_end)
        T = max(prof.top)
        z_rest = zs - T + spec.overhang
        for zi, z in enumerate(zones):
            piece = outline.intersection(box(z.a - 0.05, -1e4, z.b + 0.05, 1e4))
            if piece.is_empty:
                continue
            piece = affinity.translate(affinity.rotate(piece, pl.rot_deg, origin=(0, 0)), pl.x, pl.y)
            lay.pieces.append(Piece(piece, z_rest + z.floor - spec.clearance_z, pi, zi))
        if spec.overhang > 0:
            lay.warnings.append("Überstand > 0: Einlage ist nicht stapelbar")
    zmin_all = min((p.z0 for p in lay.pieces), default=zs - 10)
    for g in spec.grip_recesses:
        gp = grip_polygon(g)
        touched = [p.z0 for p in lay.pieces if p.poly.intersects(gp)]
        lay.grips.append((gp, (min(touched) if touched else zmin_all) - g.depth_below))
    for c in spec.compartments:
        lay.comps.append((comp_polygon(c), zs - c.depth, c.radius))
    return lay


def _min_floor(lay: Layout) -> float:
    zs = [p.z0 for p in lay.pieces] + [z for _, z in lay.grips] + [z for _, z, _ in lay.comps]
    return min(zs, default=1e9)


def compute_layout(spec: InsertSpec, objects: dict[str, ObjectSpec]) -> Layout:
    # Rastergröße
    gx, gy = spec.grid_x, spec.grid_y
    if gx is None or gy is None:
        probe = _assemble(spec, objects, 1, 1, 1)
        polys = [p.poly for p in probe.pieces] + [g for g, _ in probe.grips] + [c for c, _, _ in probe.comps]
        if polys:
            x0, y0, x1, y1 = unary_union(polys).bounds
            ax = math.ceil((x1 + LIP_MARGIN + 0.5) / PITCH)
            ay = math.ceil((y1 + LIP_MARGIN + 0.5) / PITCH)
        else:
            ax = ay = 1
        gx = gx or max(ax, 1)
        gy = gy or max(ay, 1)
    # Höhe
    need = FOOT_H + spec.floor_min
    if spec.height_u is None:
        for u in range(1, 31):
            lay = _assemble(spec, objects, gx, gy, u)
            if _min_floor(lay) >= need:
                break
    else:
        lay = _assemble(spec, objects, gx, gy, spec.height_u)
    if _min_floor(lay) < need - 1e-6:
        lay.warnings.append(f"Tiefster Boden {_min_floor(lay):.1f} mm < Mindest {need:.2f} mm: Einlage höher wählen")
    _check(lay, spec)
    return lay


def _check(lay: Layout, spec: InsertSpec) -> None:
    inner = lay.inner
    items = [("Tasche", p.poly) for p in lay.pieces] + [("Mulde", g) for g, _ in lay.grips] \
        + [("Fach", c) for c, _, _ in lay.comps]
    for name, poly in items:
        if not inner.buffer(1e-6).contains(poly):
            lay.warnings.append(f"{name} ragt über den Innenbereich (Rand {LIP_MARGIN} mm) hinaus")
            break
    groups: list[tuple[str, object]] = []
    for pi in sorted({p.placement for p in lay.pieces}):
        groups.append((f"Tasche {pi + 1}", unary_union([p.poly for p in lay.pieces if p.placement == pi])))
    groups += [(f"Fach {i + 1}", c) for i, (c, _, _) in enumerate(lay.comps)]
    for i in range(len(groups)):
        for j in range(i + 1, len(groups)):
            a, b = groups[i], groups[j]
            if a[1].intersects(b[1]):
                lay.warnings.append(f"{a[0]} und {b[0]} überlappen")
            elif a[1].distance(b[1]) < spec.min_wall:
                lay.warnings.append(f"Wand zwischen {a[0]} und {b[0]} < {spec.min_wall} mm")
