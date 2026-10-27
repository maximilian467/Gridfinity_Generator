"""Baseplate-Generator für Schubladen (Plan J).

Die Schublade bekommt ein Raster aus 42-mm-Zellen; einzelne Zellen lassen sich abwählen (z. B. eine
Ecke mit Hindernis). Der Rest bis zur Schubladenwand wird als massiver Rand an den Außenzellen
angesetzt. Aufteilung in Kacheln, die aufs Druckbett passen; Kacheln haben scharfe Außenkanten
(keine Lücken an den Stößen) und werden aus einer Zellen-Grundfläche minus Gridfinity-Taschen gebaut.

Koordinaten: Schubladen-Innenecke links unten = (0, 0), x nach rechts (Breite), y nach hinten (Tiefe).
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import cadquery as cq
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.ops import unary_union

from ..export.step import export_step
from ..export.stl import export_stl
from ..export.threemf_bambu import write_objects_3mf
from ..schemas import BaseplateSpec
from .gridfinity import PITCH

PLATE_H = 4.75           # Höhe der Baseplate (Gridfinity-Profil)
POCKET_R = 4.0           # Eckradius der Taschen oben (cq-gridfinity GR_RAD)


@dataclass
class Tile:
    n: int
    ix: int                                   # Kachel-Index (Spalte/Zeile)
    iy: int
    cells: list[tuple[int, int]]              # aktive Zellen (Raster-Index)
    poly: Polygon | MultiPolygon              # Grundfläche in Schubladen-mm (inkl. Rand)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return self.poly.bounds

    @property
    def w(self) -> float:
        b = self.bounds
        return b[2] - b[0]

    @property
    def h(self) -> float:
        b = self.bounds
        return b[3] - b[1]


@dataclass
class PlatePlan:
    nx: int
    ny: int
    ox: float                                 # Rasterursprung in der Schublade (linke untere Zellecke)
    oy: float
    rim: tuple[float, float, float, float]    # links, rechts, unten, oben
    active: set[tuple[int, int]]
    tiles: list[Tile] = field(default_factory=list)
    col_sizes: list[int] = field(default_factory=list)
    row_sizes: list[int] = field(default_factory=list)

    def cell_rect(self, ix: int, iy: int) -> tuple[float, float, float, float]:
        x0, y0 = self.ox + ix * PITCH, self.oy + iy * PITCH
        return x0, y0, x0 + PITCH, y0 + PITCH

    def footprint(self, ix: int, iy: int) -> Polygon:
        """Zelle plus anliegender Rand (an der Außenseite der Schublade)."""
        x0, y0, x1, y1 = self.cell_rect(ix, iy)
        rl, rr, rb, rt = self.rim
        if ix == 0:
            x0 -= rl
        if ix == self.nx - 1:
            x1 += rr
        if iy == 0:
            y0 -= rb
        if iy == self.ny - 1:
            y1 += rt
        return box(x0, y0, x1, y1)


def _split(n: int, rim_a: float, rim_b: float, bed: float) -> list[int]:
    """n Zellen gleichmäßig auf k Kacheln verteilen; kleinstes k, bei dem jede Kachel aufs Bett passt."""
    for k in range(1, n + 1):
        sizes = [n // k + (1 if i < n % k else 0) for i in range(k)]
        widths = [s * PITCH + (rim_a if i == 0 else 0) + (rim_b if i == k - 1 else 0) for i, s in enumerate(sizes)]
        if max(widths) <= bed + 1e-6:
            return sizes
    raise ValueError(f"Druckbett {bed:.0f} mm ist kleiner als eine Zelle")


def plan_plate(spec: BaseplateSpec) -> PlatePlan:
    c = spec.clearance
    nx = int((spec.drawer_x - 2 * c) // PITCH)
    ny = int((spec.drawer_y - 2 * c) // PITCH)
    if nx < 1 or ny < 1:
        raise ValueError("Schublade kleiner als eine Gridfinity-Zelle (42 mm)")
    rest_x = spec.drawer_x - 2 * c - nx * PITCH
    rest_y = spec.drawer_y - 2 * c - ny * PITCH
    if spec.one_sided:            # Rand nur rechts/hinten (Raster bündig in der linken vorderen Ecke)
        rl, rr, rb, rt = 0.0, rest_x, 0.0, rest_y
    else:
        rl = rr = rest_x / 2
        rb = rt = rest_y / 2
    off = {(int(a), int(b)) for a, b in spec.disabled}
    active = {(i, j) for i in range(nx) for j in range(ny)} - off
    if not active:
        raise ValueError("Alle Zellen sind abgewählt")
    plan = PlatePlan(nx, ny, c + rl, c + rb, (rl, rr, rb, rt), active)
    plan.col_sizes = _split(nx, rl, rr, spec.bed_x)
    plan.row_sizes = _split(ny, rb, rt, spec.bed_y)
    n = 0
    i0 = 0
    for tx, sx in enumerate(plan.col_sizes):
        j0 = 0
        for ty, sy in enumerate(plan.row_sizes):
            cells = sorted((i, j) for i in range(i0, i0 + sx) for j in range(j0, j0 + sy) if (i, j) in active)
            if cells:
                poly = unary_union([plan.footprint(i, j) for i, j in cells])
                parts = [poly] if isinstance(poly, Polygon) else list(poly.geoms)
                for part in parts:            # zerfällt die Kachel (abgewählte Zellen), wird jedes Stück eine Kachel
                    own = [c for c in cells if part.buffer(-1).intersects(plan.footprint(*c).buffer(-1))]
                    n += 1
                    plan.tiles.append(Tile(n, tx, ty, own, part))
            j0 += sy
        i0 += sx
    return plan


def plan_info(spec: BaseplateSpec, plan: PlatePlan) -> dict:
    """Für die Vorschau im Browser: Zellen, Rand, Kacheln (alle Maße in Schubladen-mm)."""
    def rings(p):
        geoms = [p] if isinstance(p, Polygon) else list(p.geoms)
        return [{"exterior": [list(map(lambda v: round(v, 2), q)) for q in g.exterior.coords],
                 "holes": [[list(map(lambda v: round(v, 2), q)) for q in h.coords] for h in g.interiors]} for g in geoms]
    rl, rr, rb, rt = plan.rim
    return {
        "cells_x": plan.nx, "cells_y": plan.ny, "origin": [round(plan.ox, 2), round(plan.oy, 2)],
        "rim": [round(v, 2) for v in plan.rim], "rest_x": round(rl + rr, 2), "rest_y": round(rb + rt, 2),
        "tiles_x": len(plan.col_sizes), "tiles_y": len(plan.row_sizes),
        "active": sorted([list(c) for c in plan.active]),
        "tiles": [{"n": t.n, "cells": [list(c) for c in t.cells], "w": round(t.w, 1), "h": round(t.h, 1),
                   "x0": round(t.bounds[0], 1), "y0": round(t.bounds[1], 1), "polygons": rings(t.poly)} for t in plan.tiles],
        "plate_h": PLATE_H,
    }


# Taschenprofil (wie cq-gridfinity, nachgemessen): Einzug der Taschenwand gegenüber der Zellkante
# je Höhe. Oben 0,01 mm über die Zellkante hinaus, damit keine Fläche genau auf der Kachelkante liegt
# (sonst entstehen beim Schneiden Splitter und das Netz ist nicht dicht).
POCKET_PROFILE = ((-1.0, 2.85), (0.0, 2.85), (0.7, 2.15), (2.5, 2.15), (4.65, -0.01), (PLATE_H + 1.0, -0.01))


@lru_cache(maxsize=1)
def _pocket() -> cq.Shape:
    """Eine Gridfinity-Tasche (Hohlform einer Zelle), zentriert um (0, 0)."""
    wires = []
    for z, inset in POCKET_PROFILE:
        size = PITCH - 2 * inset
        r = max(POCKET_R - inset, 0.5)
        wp = cq.Workplane("XY").workplane(offset=z).rect(size, size).val()
        f = cq.Face.makeFromWires(wp).fillet2D(r, cq.Face.makeFromWires(wp).Vertices())
        wires.append(f.outerWire())
    return cq.Solid.makeLoft(wires, ruled=True)


def _prism(poly, h: float) -> cq.Workplane:
    out = None
    for g in ([poly] if isinstance(poly, Polygon) else list(poly.geoms)):
        s = cq.Workplane("XY").polyline(list(g.exterior.coords)[:-1]).close().extrude(h)
        for hole in g.interiors:
            s = s.cut(cq.Workplane("XY").polyline(list(hole.coords)[:-1]).close().extrude(h + 2).translate((0, 0, -1)))
        out = s if out is None else out.union(s)
    return out


def make_tile(plan: PlatePlan, t: Tile) -> cq.Workplane:
    """Kachel in eigenen Koordinaten (linke untere Ecke der Grundfläche = 0, 0)."""
    x0, y0 = t.bounds[0], t.bounds[1]
    poly = t.poly.simplify(0.001)
    from shapely import affinity
    body = _prism(affinity.translate(poly, -x0, -y0), PLATE_H)
    pk = _pocket()
    tools = []
    for i, j in t.cells:
        cx0, cy0, cx1, cy1 = plan.cell_rect(i, j)
        tools.append(pk.translate(cq.Vector((cx0 + cx1) / 2 - x0, (cy0 + cy1) / 2 - y0, 0)))
    # einzelne Werkzeuge an einen Boolean (überlappen oben um 0,02 mm; als Compound wäre das ungültig)
    return cq.Workplane("XY").add(body.val().cut(*tools).clean())


def tile_plan_svg(spec: BaseplateSpec, plan: PlatePlan) -> str:
    s = 2.0
    W, H = spec.drawer_x * s, spec.drawer_y * s
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-10 -10 {W + 20} {H + 20}" width="{W + 20}" height="{H + 20}">',
           f'<rect x="0" y="0" width="{W}" height="{H}" fill="#f4f4f2" stroke="#222" stroke-width="2"/>']
    for t in plan.tiles:
        for g in ([t.poly] if isinstance(t.poly, Polygon) else list(t.poly.geoms)):
            pts = " ".join(f"{x * s:.1f},{(spec.drawer_y - y) * s:.1f}" for x, y in g.exterior.coords)
            out.append(f'<polygon points="{pts}" fill="#fbe3d6" stroke="#d9480f" stroke-width="2"/>')
        cx, cy = t.poly.representative_point().coords[0]
        out.append(f'<text x="{cx * s}" y="{(spec.drawer_y - cy) * s}" font-size="28" text-anchor="middle" '
                   f'font-family="monospace">{t.n}</text>')
    out.append("</svg>")
    return "".join(out)


TILE_GAP = 5.0            # mm zwischen den Kacheln im 3MF


def build_baseplate_files(spec: BaseplateSpec, out: Path) -> tuple[dict[str, Path], dict]:
    plan = plan_plate(spec)
    warnings = []
    if spec.magnets:
        warnings.append("Magnetlöcher werden für Baseplates noch nicht erzeugt")
    zpath = out / "baseplate_kacheln.zip"
    tiles = [(t, make_tile(plan, t)) for t in plan.tiles]
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for t, shape in tiles:
            f = export_stl(shape, out / f"kachel_{t.n}.stl")
            z.write(f, f"kachel_{t.n}_{len(t.cells)}_zellen.stl")
    # STEP: ganze Baseplate, jede Kachel an ihrer Stelle in der Schublade (für CAD)
    asm = cq.Assembly(name="Baseplate")
    for t, shape in tiles:
        asm.add(shape, name=f"Kachel {t.n}", loc=cq.Location(cq.Vector(t.bounds[0], t.bounds[1], 0)),
                color=cq.Color(0.8, 0.8, 0.82))
    step = export_step(asm, out / "baseplate.step")
    # 3MF: alle Kacheln als eigene Objekte, wie in der Schublade mit 5 mm Abstand (zum Drucken)
    tmf = write_objects_3mf([(f"Kachel {t.n}", shape, (t.bounds[0] + TILE_GAP * t.ix, t.bounds[1] + TILE_GAP * t.iy))
                             for t, shape in tiles], out / "baseplate.3mf")
    svg = out / "kachelplan.svg"
    svg.write_text(tile_plan_svg(spec, plan), encoding="utf-8")
    info = plan_info(spec, plan)
    info.update(warnings=warnings)
    return {"zip": zpath, "step": step, "3mf": tmf, "plan": svg}, info
