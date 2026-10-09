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


def grip_section(half_w: float, depth: float, edge_r: float, z_top: float, top: float,
                 n: int = 28) -> list[tuple[float, float]]:
    """Halber Querschnitt der Mulde (d >= 0 von der Mitte, z): ovaler Boden (Viertelellipse)
    ohne senkrechte Wand, oben mit Radius in die Oberfläche auslaufend. Polygonzug, damit die
    Körper aus Ebenen/Kegeln bestehen (robuste Booleans, wasserdicht)."""
    import math

    r = max(0.0, min(edge_r, half_w * 0.45, depth * 0.45))
    a = half_w - r                       # Ellipse endet senkrecht bei d = a, z = z_top
    b = depth
    pts = [(0.0, top), (0.0, z_top - b)]
    for i in range(1, n + 1):
        t = (math.pi / 2) * i / n
        if b * math.cos(t) < r:          # ab hier übernimmt der Kantenradius
            break
        pts.append((a * math.sin(t), z_top - b * math.cos(t)))
    if r > 0:
        # Viertelkreis um (a + r, z_top - r): tangential an die Wand und an die Oberfläche
        cx, cz = a + r, z_top - r
        k = max(6, n // 3)
        for i in range(0, k + 1):
            t = (math.pi / 2) * i / k
            pts.append((cx - r * math.cos(t), cz + r * math.sin(t)))
    else:
        pts.append((a, z_top))
    pts.append((half_w + 1.0, z_top))
    pts.append((half_w + 1.0, top))
    out = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - out[-1][0]) > 1e-4 or abs(p[1] - out[-1][1]) > 1e-4:
            out.append(p)
    return out


def grip_cutter(g, top: float, n_x: int = 40, n_cap: int = 14) -> list[cq.Shape]:
    """Greifmulde mit weichem Querschnitt (ovaler Boden, Oberkante mit Radius, keine senkrechte
    Wand). Ein einziger Körper als Loft durch Querschnitte quer zur Mittellinie: an den Enden
    die Schnitte der Rotationsschüssel (Abstand e vom Endpunkt), dazwischen das Profil.
    (Keine Rotationskörper: deren Pol ergibt kein wasserdichtes Netz.)
    Ohne Rundung: Prisma bis zum Boden."""
    import math

    import numpy as np
    from shapely.geometry import Point as _Pt

    z_top = g.z_top or top - 5.0
    half = g.radius
    depth = z_top - g.z0
    if not g.rounded or depth <= 0.2:
        return prism(g.poly, g.z0, top)
    sec = grip_section(half, depth, g.edge_r, z_top, top)
    fd = np.array([p[0] for p in sec[1:-1]])          # Bodenkurve z = f(d), d = Abstand zur Mittellinie
    fz = np.array([p[1] for p in sec[1:-1]])

    if isinstance(g.axis, _Pt):
        ax, ay = g.axis.x, g.axis.y
        L, ux, uy = 0.0, 1.0, 0.0
    else:
        (ax, ay), (bx, by) = list(g.axis.coords)
        L = math.hypot(bx - ax, by - ay)
        ux, uy = ((bx - ax) / L, (by - ay) / L) if L > 1e-6 else (1.0, 0.0)
    nx, ny = -uy, ux
    W = half + 1.0
    emax = half + 0.2                                  # dort liegt der ganze Schnitt über der Oberfläche
    v = np.sin(np.linspace(-np.pi / 2, np.pi / 2, n_x))    # dichter an den Rändern (Kantenradius)

    def wire(p: float, e: float) -> cq.Wire:
        X = math.sqrt(max(W * W - e * e, 0.25))
        xs = X * v
        zs = np.interp(np.sqrt(xs ** 2 + e ** 2), fd, fz)
        pts2 = [(float(x), float(z)) for x, z in zip(xs, zs)] + [(X, top), (-X, top)]
        bx_, by_ = ax + ux * p, ay + uy * p
        return cq.Wire.makePolygon([cq.Vector(bx_ + nx * x, by_ + ny * x, z) for x, z in pts2], close=True)

    es = [emax * math.sin(t) for t in np.linspace(0, math.pi / 2, n_cap)]   # 0 .. emax
    wires = [wire(-e, e) for e in reversed(es)]                              # Ende A: außen -> Endpunkt
    if L > 1e-6:
        wires += [wire(L + e, e) for e in es]                               # Ende B: Endpunkt -> außen
    else:
        wires += [wire(e, e) for e in es[1:]]
    return [cq.Solid.makeLoft(wires, ruled=True)]
