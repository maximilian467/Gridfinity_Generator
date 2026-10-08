"""Baseplate-Generator für Schubladen (Plan J): Kacheln <= Druckbett, Rand nur an Außenkanten."""
from __future__ import annotations

import math
import zipfile
from dataclasses import dataclass
from pathlib import Path

import cadquery as cq
from cqgridfinity import GridfinityBaseplate

from ..export.stl import export_stl
from ..schemas import BaseplateSpec
from .gridfinity import PITCH


@dataclass
class Tile:
    ix: int
    iy: int
    cx: int           # Zellen in x
    cy: int
    rim_l: float
    rim_r: float
    rim_b: float
    rim_t: float
    x0: float         # Position in der Schublade (links unten)
    y0: float

    @property
    def w(self) -> float:
        return self.cx * PITCH + self.rim_l + self.rim_r

    @property
    def h(self) -> float:
        return self.cy * PITCH + self.rim_b + self.rim_t


def _split(n: int, rim_total: float, bed: float, one_sided: bool):
    """Verteilt n Zellen gleichmäßig auf k Kacheln; kleinstes k mit passenden Maßen."""
    rim_a = 0.0 if one_sided else rim_total / 2
    rim_b = rim_total if one_sided else rim_total / 2
    for k in range(1, n + 1):
        sizes = [n // k + (1 if i < n % k else 0) for i in range(k)]
        widths = [s * PITCH + (rim_a if i == 0 else 0) + (rim_b if i == k - 1 else 0) for i, s in enumerate(sizes)]
        if max(widths) <= bed + 1e-6:
            return sizes, rim_a, rim_b
    raise ValueError(f"Druckbett {bed:.0f} mm ist kleiner als eine Zelle")


def plan_tiles(spec: BaseplateSpec) -> tuple[list[Tile], dict]:
    c = spec.clearance
    nx = int((spec.drawer_x - 2 * c) // PITCH)
    ny = int((spec.drawer_y - 2 * c) // PITCH)
    if nx < 1 or ny < 1:
        raise ValueError("Schublade kleiner als eine Gridfinity-Zelle (42 mm)")
    rest_x = spec.drawer_x - 2 * c - nx * PITCH
    rest_y = spec.drawer_y - 2 * c - ny * PITCH
    sx, rl, rr = _split(nx, rest_x, spec.bed_x, spec.one_sided)
    sy, rb, rt = _split(ny, rest_y, spec.bed_y, spec.one_sided)
    tiles: list[Tile] = []
    x = c
    for ix, cx in enumerate(sx):
        y = c
        for iy, cy in enumerate(sy):
            tiles.append(Tile(ix, iy, cx, cy, rl if ix == 0 else 0, rr if ix == len(sx) - 1 else 0,
                              rb if iy == 0 else 0, rt if iy == len(sy) - 1 else 0, x, y))
            y += cy * PITCH + (rb if iy == 0 else 0) + (rt if iy == len(sy) - 1 else 0)
        x += cx * PITCH + (rl if ix == 0 else 0) + (rr if ix == len(sx) - 1 else 0)
    info = {"cells_x": nx, "cells_y": ny, "rest_x": round(rest_x, 2), "rest_y": round(rest_y, 2),
            "tiles_x": len(sx), "tiles_y": len(sy)}
    return tiles, info


def make_tile(t: Tile) -> cq.Workplane:
    plate = GridfinityBaseplate(t.cx, t.cy).render()
    bb = plate.val().BoundingBox()
    plate = plate.translate((-bb.xmin + t.rim_l, -bb.ymin + t.rim_b, -bb.zmin))
    h = bb.zlen
    pw, ph = t.cx * PITCH, t.cy * PITCH
    for (x0, y0, w, hh) in [
        (0, 0, t.rim_l, t.h), (t.rim_l + pw, 0, t.rim_r, t.h),
        (0, 0, t.w, t.rim_b), (0, t.rim_b + ph, t.w, t.rim_t),
    ]:
        if w > 1e-6 and hh > 1e-6:
            plate = plate.union(cq.Workplane("XY").box(w, hh, h, centered=False).translate((x0, y0, 0)))
    return plate.clean()


def tile_plan_svg(spec: BaseplateSpec, tiles: list[Tile]) -> str:
    s = 2.0
    W, H = spec.drawer_x * s, spec.drawer_y * s
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-10 -10 {W + 20} {H + 20}" width="{W + 20}" height="{H + 20}">',
           f'<rect x="0" y="0" width="{W}" height="{H}" fill="#f4f4f2" stroke="#222" stroke-width="2"/>']
    for i, t in enumerate(tiles, 1):
        x, y = t.x0 * s, (spec.drawer_y - t.y0 - t.h) * s
        out.append(f'<rect x="{x}" y="{y}" width="{t.w * s}" height="{t.h * s}" fill="#fbe3d6" stroke="#d9480f" stroke-width="2"/>')
        out.append(f'<text x="{x + t.w * s / 2}" y="{y + t.h * s / 2}" font-size="28" text-anchor="middle" '
                   f'font-family="monospace">{i}</text>')
    out.append("</svg>")
    return "".join(out)


def build_baseplate_files(spec: BaseplateSpec, out: Path) -> tuple[dict[str, Path], dict]:
    tiles, info = plan_tiles(spec)
    warnings = []
    if spec.magnets:
        warnings.append("Magnetlöcher werden für Baseplates noch nicht erzeugt")
    zpath = out / "baseplate_kacheln.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for i, t in enumerate(tiles, 1):
            f = export_stl(make_tile(t), out / f"kachel_{i}.stl")
            z.write(f, f"kachel_{i}_{t.cx}x{t.cy}.stl")
    svg = out / "kachelplan.svg"
    svg.write_text(tile_plan_svg(spec, tiles), encoding="utf-8")
    info.update(warnings=warnings, tiles=[
        {"n": i, "cx": t.cx, "cy": t.cy, "w": round(t.w, 1), "h": round(t.h, 1), "x0": round(t.x0, 1), "y0": round(t.y0, 1)}
        for i, t in enumerate(tiles, 1)])
    return {"zip": zpath, "plan": svg}, info
