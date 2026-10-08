"""Shapely-Polygone -> CadQuery-Prismen."""
from __future__ import annotations

import cadquery as cq
from shapely.geometry import MultiPolygon, Polygon


def _polys(g):
    if g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    if isinstance(g, MultiPolygon):
        return list(g.geoms)
    return [p for p in getattr(g, "geoms", []) if isinstance(p, Polygon)]


def _ring_prism(coords, z0: float, z1: float) -> cq.Workplane:
    pts = [(float(x), float(y)) for x, y in list(coords)[:-1]]
    return cq.Workplane("XY").workplane(offset=z0).polyline(pts).close().extrude(z1 - z0)


def prism(geom, z0: float, z1: float) -> list[cq.Shape]:
    out = []
    for p in _polys(geom):
        if p.area < 1e-4:
            continue
        s = _ring_prism(p.exterior.coords, z0, z1)
        for hole in p.interiors:
            s = s.cut(_ring_prism(hole.coords, z0 - 1, z1 + 1))
        out.extend(s.solids().vals())
    return out


def fuse_all(shapes: list[cq.Shape]) -> cq.Workplane | None:
    if not shapes:
        return None
    r = shapes[0].fuse(*shapes[1:]) if len(shapes) > 1 else shapes[0]
    return cq.Workplane("XY").add(r.clean())


def cut_all(body: cq.Workplane, shapes: list[cq.Shape]) -> cq.Workplane:
    u = fuse_all(shapes)
    return body if u is None else body.cut(u)


def grip_cutter(g, top: float) -> list[cq.Shape]:
    """Greifmulde: Prisma bis oben; bei gerundeter Mulde ist der Boden ein liegender Zylinder
    entlang der Mittellinie, auf die Stadionform beschnitten -> U-Profil quer, runde Enden.
    (Keine Kugeln: deren Pole erzeugen nicht wasserdichte Netze und langsame Booleans.)"""
    from shapely.geometry import Point as _Pt

    if not g.rounded or isinstance(g.axis, _Pt):
        return prism(g.poly, g.z0, top)
    r = g.radius
    zc = g.z0 + r
    (ax, ay), (bx, by) = list(g.axis.coords)
    L = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
    if L < 1e-6:
        return prism(g.poly, g.z0, top)
    ux, uy = (bx - ax) / L, (by - ay) / L
    cyl = cq.Solid.makeCylinder(r, L + 2 * r, cq.Vector(ax - ux * r, ay - uy * r, zc), cq.Vector(ux, uy, 0))
    clip = fuse_all(prism(g.poly, g.z0 - 1, zc + 0.01))
    shapes = prism(g.poly, zc, top)
    if clip is not None:
        shapes.append(cyl.intersect(clip.val()))
    return shapes
