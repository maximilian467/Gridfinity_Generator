"""2D-Layout der Einlage (nur shapely): Taschenstücke je Zone, Greifmulden, Kästen, Warnungen."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from shapely import affinity, contains_xy
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union

from ..schemas import Compartment, GripRecess, InsertSpec, ObjectSpec
from .gridfinity import FOOT_H, LIP_H, LIP_MARGIN, PITCH, UNIT_H, bin_outer, surface_z
from .zones import Zone, compute_zones, zones_from_levels


@dataclass
class Piece:
    poly: object        # shapely (Multi)Polygon im Einlagen-Koordinatensystem
    z0: float           # Cutter-Boden (absolut)
    placement: int
    zone: int


@dataclass
class Grip:
    poly: object
    z0: float                       # tiefster Punkt der Mulde
    rounded: bool
    radius: float                   # halbe Breite (Öffnung oben)
    axis: LineString | Point        # Mittellinie (Stadion) bzw. Mittelpunkt (Kreis)
    auto: bool = False
    placement: int | None = None
    params: GripRecess | None = None      # automatische Mulde als übernehmbare Spec (vor Zentrierung)
    edge_r: float = 4.0                   # Rundung der Oberkante
    z_top: float = 0.0                    # Oberfläche der Einlage


@dataclass
class Comp:
    poly: object
    z0: float
    radius: float
    auto: bool = False
    free_depth: bool = False        # Tiefe folgt der Höhe (so tief wie möglich)


@dataclass
class Layout:
    grid_x: int
    grid_y: int
    height_u: float
    z_surface: float
    total_height: float = 0.0                          # inkl. Stapelrand
    sink: list[float] = field(default_factory=list)    # je Platzierung: tatsächlicher Einsinkanteil
    pieces: list[Piece] = field(default_factory=list)
    grips: list[Grip] = field(default_factory=list)
    comps: list[Comp] = field(default_factory=list)
    zones: list[list[Zone]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    shift: tuple[float, float] = (0.0, 0.0)      # Verschiebung durch Zentrierung (auf alle Spec-Positionen)

    @property
    def outer(self) -> tuple[float, float]:
        return bin_outer(self.grid_x, self.grid_y)

    @property
    def inner(self):
        ox, oy = self.outer
        return box(LIP_MARGIN, LIP_MARGIN, ox - LIP_MARGIN, oy - LIP_MARGIN)

    def pocket_union(self):
        return unary_union([p.poly for p in self.pieces])

    @property
    def manual_grips(self) -> list[Grip]:
        return [g for g in self.grips if not g.auto]

    @property
    def manual_comps(self) -> list[Comp]:
        return [c for c in self.comps if not c.auto]


def _polys(g) -> list[Polygon]:
    if g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    return [p for p in getattr(g, "geoms", []) if isinstance(p, Polygon)]


def smooth_hull(poly, sigma: float, step: float = 0.5):
    """Glatte Hülle: Kontur gleichmäßig abtasten, mit Gauß (sigma mm) glätten und dort, wo die
    Original-Kontur noch heraussteht, lokal und weich nach außen schieben. Ergebnis: ruhige
    Linie ohne Wellen und Zacken, die das Original vollständig enthält (etwas mehr Spiel an
    Wellenbergen und spitzen Enden, sonst keins)."""
    from scipy.ndimage import gaussian_filter1d, maximum_filter1d
    from shapely.geometry.polygon import orient

    if sigma <= 0:
        return poly
    parts = _polys(poly)
    if not parts:
        return poly
    p = orient(max(parts, key=lambda q: q.area), 1.0)           # gegen den Uhrzeigersinn
    ring = p.exterior
    n = max(int(ring.length / step), 16)
    P = np.array([ring.interpolate(i * ring.length / n).coords[0] for i in range(n)])
    k = sigma / (ring.length / n)
    S = gaussian_filter1d(P, k, axis=0, mode="wrap")
    t = np.roll(S, -1, axis=0) - np.roll(S, 1, axis=0)
    nrm = np.column_stack([t[:, 1], -t[:, 0]])
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12
    e = np.einsum("ij,ij->i", P - S, nrm)                      # > 0: Original steht außen über
    w = int(k) * 2 + 1
    d = gaussian_filter1d(maximum_filter1d(np.maximum(e, 0), w, mode="wrap"), k / 3, mode="wrap")
    Q = Polygon(S + d[:, None] * nrm).buffer(0)
    qs = _polys(Q)
    if not qs:
        return poly
    Q = orient(max(qs, key=lambda q: q.area), 1.0)
    # zweiter, leichter Durchgang: letzte Knicke aus dem Aufweiten verschwinden
    r2 = Q.exterior
    m = max(int(r2.length / step), 16)
    R = np.array([r2.interpolate(i * r2.length / m).coords[0] for i in range(m)])
    R = gaussian_filter1d(R, k / 4, axis=0, mode="wrap")
    q2 = _polys(Polygon(R).buffer(0))
    if q2:
        Q = max(q2, key=lambda q: q.area)
    rest = poly.difference(Q)
    if not rest.is_empty and rest.area > 1e-6:                 # letzte Reste: minimal aufweiten
        r = max(Q.exterior.distance(Point(c)) for g in _polys(rest) for c in g.exterior.coords)
        Q = Q.buffer(r + 0.02, join_style=1)
    return Q


def pocket_outline(contour: list[list[float]], cxy: float, cend: float, smooth: float = 0.0):
    """Taschenkontur: Spiel als runder Offset, Längszugabe als Minkowski-Summe mit einer Strecke,
    danach glätten (nie kleiner als Werkzeug + Spiel)."""
    poly = Polygon(contour).buffer(0)
    b = poly.buffer(cxy, join_style=1)
    n = 9 if cend > 0 else 1
    shifts = [-cend + 2 * cend * i / (n - 1) for i in range(n)] if n > 1 else [0.0]
    o = unary_union([affinity.translate(b, dx, 0) for dx in shifts]).simplify(0.05)
    return smooth_hull(o, smooth).simplify(0.03)


def _stadium_axis(g: GripRecess) -> LineString:
    half = max(g.l - g.w, 0) / 2
    a = math.radians(g.rot_deg)
    ux, uy = -math.sin(a), math.cos(a)          # Stadionlänge liegt (unrotiert) entlang y
    return LineString([(g.x - ux * half, g.y - uy * half), (g.x + ux * half, g.y + uy * half)])


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


def comp_polygon(c: Compartment):
    if c.polygon:
        return Polygon(c.polygon).buffer(0)
    r = max(min(c.radius, c.w / 2, c.l / 2), 0.01)
    return box(c.x + r, c.y + r, c.x + c.w - r, c.y + c.l - r).buffer(r, 16)


def balance_point(obj: ObjectSpec) -> float:
    """Schwerpunkt entlang der Länge (Breite x Dicke gewichtet): dort lässt sich das Werkzeug
    am besten anheben. Bei Zangen landet das am Gelenk."""
    prof = obj.profile
    s = np.asarray(prof.s)
    t = np.asarray(prof.top) - np.asarray(prof.bottom)
    poly = Polygon(obj.contour_mm).buffer(0)
    y0, y1 = poly.bounds[1] - 1, poly.bounds[3] + 1
    w = np.array([LineString([(x, y0), (x, y1)]).intersection(poly).length for x in s])
    m = w * np.clip(t, 0.1, None)
    return float((m * s).sum() / max(m.sum(), 1e-9))


def grip_across(outline, sg: float, width: float, overhang: float) -> tuple[float, float]:
    """Quer zur Achse an Stelle sg: Mitte und Länge (Taschenbreite + 2 x Überstand)."""
    y0, y1 = outline.bounds[1] - 1, outline.bounds[3] + 1
    cut = LineString([(sg, y0), (sg, y1)]).intersection(outline)
    lo, hi = (cut.bounds[1], cut.bounds[3]) if not cut.is_empty else (-10.0, 10.0)
    return (lo + hi) / 2, max((hi - lo) + 2 * overhang, width)


def auto_grip_for(obj: ObjectSpec, outline, spec: InsertSpec) -> GripRecess:
    """Greifmulde quer unter dem Werkzeug am Schwerpunkt (objekt-lokale Koordinaten)."""
    sg = balance_point(obj)
    yc, L = grip_across(outline, sg, spec.grip_width, spec.grip_overhang)
    return GripRecess(shape="stadium", x=sg, y=yc, w=spec.grip_width, l=L,
                      rot_deg=0.0, depth_below=spec.grip_depth_below, rounded=True, s=round(sg, 1))


def _place(geom, pl):
    return affinity.translate(affinity.rotate(geom, pl.rot_deg, origin=(0, 0)), pl.x, pl.y)


def _make_grip(g: GripRecess, pieces: list[Piece], zmin_all: float, auto=False, placement=None) -> Grip:
    gp = grip_polygon(g)
    touched = [p.z0 for p in pieces if p.poly.intersects(gp)]
    z0 = (min(touched) if touched else zmin_all) - g.depth_below
    axis = Point(g.x, g.y) if g.shape == "circle" else _stadium_axis(g)
    return Grip(gp, z0, g.rounded and g.shape != "rect", g.w / 2, axis, auto, placement, g if auto else None,
                edge_r=g.edge_r)


def tool_depth(obj: ObjectSpec, spec: InsertSpec) -> tuple[float, float]:
    """Wie tief die tiefste Stelle des Werkzeugs unter der Oberfläche liegt (ohne Bodenabstand):
    Einsinkanteil x Werkzeugdicke, mindestens so, dass jede Ebene 1 mm Tasche behält.
    Rückgabe (Tiefe, kleinste sinnvolle Tiefe)."""
    prof = obj.profile
    T = max(prof.top)
    zmax = max((lv[2] for lv in prof.levels), default=0.0) if prof.levels else 0.0
    dmin = min(zmax + 1.0, T)
    return max(spec.sink * T, dmin), dmin


def _rock_warning(obj: ObjectSpec) -> str | None:
    """Liegt das Werkzeug beiderseits seines Schwerpunkts auf? Sonst kann es wippen."""
    prof = obj.profile
    if not prof.measured or not prof.levels or len(prof.measured) != len(prof.s):
        return None
    s = np.asarray(prof.s)
    meas = np.asarray(prof.measured)
    floor = np.asarray(prof.bottom)
    ok = ~np.asarray(obj.profile_missing, bool) if len(obj.profile_missing) == len(s) else np.ones(len(s), bool)
    touch = s[ok & (meas - floor < 0.8)]
    if len(touch) < 2:
        return None
    sb = balance_point(obj)
    L = obj.length_mm
    if not (touch.min() < sb - 0.1 * L and touch.max() > sb + 0.1 * L):
        return (f"{obj.name}: liegt nur auf einer Seite des Schwerpunkts auf und kann wippen. "
                "Im Seitenprofil die Ebenen prüfen (Ebene unter dem aufliegenden Teil tiefer setzen).")
    return None


def _assemble(spec: InsertSpec, objects: dict[str, ObjectSpec], gx: int, gy: int, u: float,
              reduce: float = 0.0) -> Layout:
    """reduce: Tiefe, um die alle Werkzeuge flacher eingesetzt werden (feste Gesamthöhe)."""
    zs = surface_z(u)
    lay = Layout(gx, gy, u, zs, total_height=zs + (LIP_H if spec.stacking_lip else 0.0))
    margin = spec.clearance_xy + spec.clearance_end
    auto_grips: list[tuple[GripRecess, int]] = []
    outlines: dict[int, object] = {}
    for pi, pl in enumerate(spec.placements):
        obj = objects[pl.object_id]
        prof = obj.profile
        if prof.levels:
            zones = zones_from_levels(prof.levels, obj.length_mm, margin)
        else:                       # ältere Objekte ohne Ebenen
            zones = compute_zones(prof.s, prof.bottom, obj.length_mm, margin, spec.step_tol,
                                  spec.min_zone_len, spec.max_zones, prof.ds)
        lay.zones.append(zones)
        outline = pocket_outline(obj.contour_mm, spec.clearance_xy, spec.clearance_end, spec.smooth_mm)
        outlines[pi] = outline
        D, dmin = tool_depth(obj, spec)
        D = max(D - reduce, dmin)
        lay.sink.append(D / max(max(prof.top), 1e-6))
        z_rest = zs - D + spec.overhang
        w = _rock_warning(obj)
        if w and w not in lay.warnings:
            lay.warnings.append(w)
        for zi, z in enumerate(zones):
            piece = outline.intersection(box(z.a - 0.05, -1e4, z.b + 0.05, 1e4))
            if piece.is_empty:
                continue
            lay.pieces.append(Piece(_place(piece, pl), z_rest + z.floor - spec.clearance_z, pi, zi))
        if spec.auto_grip:
            g = auto_grip_for(obj, outline, spec)
            c = _place(Point(g.x, g.y), pl)
            auto_grips.append((g.model_copy(update={"x": c.x, "y": c.y, "rot_deg": pl.rot_deg, "attach": pi}), pi))
        if spec.overhang > 0 and pi == 0:
            lay.warnings.append("Überstand > 0: Einlage ist nicht stapelbar")
    zmin_all = min((p.z0 for p in lay.pieces), default=zs - 10)
    for g, pi in auto_grips:
        lay.grips.append(_make_grip(g, lay.pieces, zmin_all, auto=True, placement=pi))
    for g in spec.grip_recesses:
        if g.attach is not None and g.attach < len(spec.placements) and g.attach in outlines:
            pl = spec.placements[g.attach]
            outline = outlines[g.attach]
            sg = g.s if g.s is not None else balance_point(objects[pl.object_id])
            yc, L = grip_across(outline, sg, g.w, spec.grip_overhang)
            c = _place(Point(sg, yc), pl)
            g = g.model_copy(update={"x": c.x, "y": c.y, "rot_deg": pl.rot_deg, "s": sg,
                                     "l": L if g.auto_length else g.l})
        lay.grips.append(_make_grip(g, lay.pieces, zmin_all))
    need = FOOT_H + spec.floor_min
    for c in spec.compartments:
        # ohne Tiefe: so tief wie möglich (folgt der Einlagenhöhe)
        lay.comps.append(Comp(comp_polygon(c), need if c.depth is None else zs - c.depth, c.radius,
                              free_depth=c.depth is None))
    for g in lay.grips:
        g.z_top = zs
    return lay


def _content(lay: Layout):
    polys = [p.poly for p in lay.pieces] + [g.poly for g in lay.grips] + [c.poly for c in lay.comps]
    return unary_union(polys) if polys else None


def _translate_layout(lay: Layout, dx: float, dy: float) -> None:
    for p in lay.pieces:
        p.poly = affinity.translate(p.poly, dx, dy)
    for g in lay.grips:
        g.poly = affinity.translate(g.poly, dx, dy)
        g.axis = affinity.translate(g.axis, dx, dy)
    for c in lay.comps:
        c.poly = affinity.translate(c.poly, dx, dy)
    lay.shift = (lay.shift[0] + dx, lay.shift[1] + dy)


def _center(lay: Layout) -> None:
    # Mitte nur aus Taschen und Mulden: Fächer füllen die Restfläche und wandern nur mit
    # (sonst verschiebt jedes erzeugte Fach die Mitte und damit alle anderen Fächer)
    polys = [p.poly for p in lay.pieces] + [g.poly for g in lay.grips]
    u = unary_union(polys) if polys else _content(lay)
    if u is None:
        return
    x0, y0, x1, y1 = u.bounds
    ix0, iy0, ix1, iy1 = lay.inner.bounds
    _translate_layout(lay, (ix0 + ix1) / 2 - (x0 + x1) / 2, (iy0 + iy1) / 2 - (y0 + y1) / 2)


def _min_floor(lay: Layout) -> float:
    zs = [p.z0 for p in lay.pieces] + [g.z0 for g in lay.grips] \
        + [c.z0 for c in lay.comps if not c.auto and not c.free_depth]
    return min(zs, default=1e9)


def _min_tool_floor(lay: Layout) -> float:
    return min([p.z0 for p in lay.pieces] + [g.z0 for g in lay.grips], default=1e9)


def compute_layout(spec: InsertSpec, objects: dict[str, ObjectSpec]) -> Layout:
    # Rastergröße: nur Taschen und Mulden zählen. Kästen füllen die Restfläche; zählten sie mit,
    # würde jedes Erzeugen von Kästen das Raster um ein Feld wachsen lassen.
    gx, gy = spec.grid_x, spec.grid_y
    if gx is None or gy is None:
        probe = _assemble(spec.model_copy(update={"compartments": []}), objects, 1, 1, 1)
        polys = [p.poly for p in probe.pieces] + [g.poly for g in probe.grips]
        if polys:
            x0, y0, x1, y1 = unary_union(polys).bounds
            if spec.auto_center:       # nur die Größe zählt
                need_x, need_y = (x1 - x0), (y1 - y0)
            else:
                need_x, need_y = x1 - LIP_MARGIN, y1 - LIP_MARGIN
            ax = math.ceil((need_x + 2 * LIP_MARGIN + 0.5 + 0.4) / PITCH)
            ay = math.ceil((need_y + 2 * LIP_MARGIN + 0.5 + 0.4) / PITCH)
        else:
            ax = ay = 1
        gx = gx or max(ax, 1)
        gy = gy or max(ay, 1)
    # Höhe
    need = FOOT_H + spec.floor_min
    if spec.height_mm is not None:
        # feste Gesamthöhe (inkl. Stapelrand): passt das Werkzeug nicht, sitzt es flacher
        u = max((spec.height_mm - (LIP_H if spec.stacking_lip else 0.0)) / UNIT_H, 1.0)
        lay = _assemble(spec, objects, gx, gy, u)
        short = need - _min_tool_floor(lay)
        if short > 1e-6 and spec.placements:
            lay = _assemble(spec, objects, gx, gy, u, reduce=short)
            sink = min(lay.sink) if lay.sink else 0
            lay.warnings.append(f"Für {spec.height_mm:.0f} mm Gesamthöhe sitzen die Werkzeuge flacher "
                                f"(nur {sink * 100:.0f} % eingesunken).")
    elif spec.height_u is None:
        for u_ in range(1, 31):
            lay = _assemble(spec, objects, gx, gy, u_)
            if _min_floor(lay) >= need:
                break
    else:
        lay = _assemble(spec, objects, gx, gy, spec.height_u)
    if spec.auto_center:
        _center(lay)
    if _min_floor(lay) < need - 1e-6:
        lay.warnings.append(f"Tiefster Boden {_min_floor(lay):.1f} mm < Mindest {need:.2f} mm: "
                            "Einlage höher wählen oder Fächer flacher machen")
    if spec.auto_compartments:
        for poly in auto_compartments(lay, spec):
            depth = spec.comp_depth if spec.comp_depth else lay.z_surface - need
            lay.comps.append(Comp(poly, max(lay.z_surface - depth, need), 3.0, auto=True))
    _check(lay, spec)
    return lay


# ---- Automatische Kästen ------------------------------------------------------------

def _max_rect(free: np.ndarray, min_h: int = 1, min_w: int = 1):
    """Größtes Rechteck aus True-Zellen mit Mindestmaßen (sonst gewinnt ein langer, zu schmaler
    Streifen und daneben bliebe Platz ungenutzt)."""
    best, best_area = None, 0
    h = np.zeros(free.shape[1], int)
    for r in range(free.shape[0]):
        h = np.where(free[r], h + 1, 0)
        stack: list[tuple[int, int]] = []
        for c in range(len(h) + 1):
            cur = h[c] if c < len(h) else 0
            start = c
            while stack and stack[-1][1] >= cur:
                s, hh = stack.pop()
                if hh * (c - s) > best_area and hh >= min_h and c - s >= min_w:
                    best_area, best = hh * (c - s), (r - hh + 1, s, hh, c - s)
                start = s
            stack.append((start, cur))
    return best


def auto_compartments(lay: Layout, spec: InsertSpec, max_n: int = 10, grow: float = 8.0) -> list:
    """Freie Fläche (Innenbereich minus Taschen/Mulden/Fächer mit Wandabstand) in Kästen teilen:
    größte freie Rechtecke (>= Mindestgröße) suchen und an Hindernisse heranwachsen lassen, so dass
    die Kastenwand der Werkzeugkontur folgt."""
    wall = max(spec.comp_wall, 0.8) + 0.15        # Reserve für Vereinfachung/Tessellierung
    occupied = [p.poly for p in lay.pieces] + [g.poly for g in lay.grips] + [c.poly for c in lay.comps]
    free = lay.inner.buffer(-0.01)
    if occupied:
        free = free.difference(unary_union(occupied).buffer(wall, join_style=1))
    x0, y0, x1, y1 = lay.inner.bounds
    xs = np.arange(x0 + 0.5, x1, 1.0)
    ys = np.arange(y0 + 0.5, y1, 1.0)
    gx, gy = np.meshgrid(xs, ys)
    out = []
    remaining = free
    for _ in range(max_n):
        if remaining.is_empty:
            break
        mask = contains_xy(remaining.buffer(-0.5), gx.ravel(), gy.ravel()).reshape(gx.shape)
        m = int(math.ceil(spec.comp_min_size))
        r = _max_rect(mask, m, m)
        if r is None:
            break
        r0, c0, hh, ww = r
        if hh < spec.comp_min_size or ww < spec.comp_min_size:
            break
        rect = box(x0 + c0, y0 + r0, x0 + c0 + ww, y0 + r0 + hh)
        if not spec.comp_follow:                 # gerade Rechtecke, so groß wie frei
            region = rect.buffer(-2.0, join_style=1).buffer(2.0, join_style=1)
            out.append(region.simplify(0.05))
            remaining = remaining.difference(rect.buffer(wall, join_style=2))
            continue
        region = rect.buffer(grow, join_style=2).intersection(remaining)
        parts = _polys(region)
        if not parts:
            break
        region = max(parts, key=lambda p: p.intersection(rect).area)
        region = region.buffer(-3.0, join_style=1).buffer(3.0, join_style=1)   # Ecken runden, Splitter weg
        region = max(_polys(region), key=lambda p: p.area) if _polys(region) else None
        if region is None or region.area < spec.comp_min_size ** 2 * 0.8:
            remaining = remaining.difference(rect)
            continue
        out.append(region.simplify(0.1))
        remaining = remaining.difference(region.buffer(wall, join_style=1))
    return out


def _check(lay: Layout, spec: InsertSpec) -> None:
    inner = lay.inner
    items = [("Tasche", p.poly) for p in lay.pieces] + [("Mulde", g.poly) for g in lay.grips] \
        + [("Fach", c.poly) for c in lay.comps]
    for name, poly in items:
        if not inner.buffer(1e-6).contains(poly):
            lay.warnings.append(f"{name} ragt über den Innenbereich (Rand {LIP_MARGIN} mm) hinaus")
            break
    groups: list[tuple[str, object]] = []
    for pi in sorted({p.placement for p in lay.pieces}):
        groups.append((f"Tasche {pi + 1}", unary_union([p.poly for p in lay.pieces if p.placement == pi])))
    groups += [(f"Fach {i + 1}", c.poly) for i, c in enumerate(lay.comps)]
    for i in range(len(groups)):
        for j in range(i + 1, len(groups)):
            a, b = groups[i], groups[j]
            if a[1].intersects(b[1]):
                lay.warnings.append(f"{a[0]} und {b[0]} überlappen")
            elif a[1].distance(b[1]) < spec.min_wall - 1e-6:
                lay.warnings.append(f"Wand zwischen {a[0]} und {b[0]} < {spec.min_wall} mm")


__all__ = ["Layout", "Piece", "Grip", "Comp", "compute_layout", "pocket_outline", "grip_polygon",
           "comp_polygon", "auto_compartments", "balance_point", "MultiPolygon"]



def largest_rect(region, step: float = 0.5):
    """Größtes achsparalleles Rechteck in einer (Multi-)Fläche (Raster step mm)."""
    x0, y0, x1, y1 = region.bounds
    xs = np.arange(x0 + step / 2, x1, step)
    ys = np.arange(y0 + step / 2, y1, step)
    if len(xs) == 0 or len(ys) == 0:
        return None
    gx, gy = np.meshgrid(xs, ys)
    mask = contains_xy(region, gx.ravel(), gy.ravel()).reshape(gx.shape)
    r = _max_rect(mask)
    if r is None:
        return None
    r0, c0, hh, ww = r
    return box(x0 + c0 * step, y0 + r0 * step, x0 + (c0 + ww) * step, y0 + (r0 + hh) * step)


def band_rect(free, axis: str, a: float, b: float, px: float, py: float, follow: bool = False):
    """Kasten zwischen zwei geraden Linien (axis 'h': waagrecht bei y = a und y = b). Quer dazu
    reicht er vom Klickpunkt aus bis zum nächsten Hindernis (Werkzeug + Wand, Rand, anderer
    Kasten). follow=False: gerades Rechteck; True: Wand folgt der Kontur des Hindernisses."""
    lo, hi = min(a, b), max(a, b)
    fx0, fy0, fx1, fy1 = free.bounds
    big = 1e4
    band = box(-big, lo, big, hi) if axis == "h" else box(lo, -big, hi, big)
    region = band.intersection(free)
    comps = _polys(region)
    pt = Point(px, py)
    comp = next((g for g in comps if g.buffer(0.3).contains(pt)), None)
    if comp is None:
        return None
    if follow:
        return comp
    obst = band.intersection(box(fx0 - 1, fy0 - 1, fx1 + 1, fy1 + 1)).difference(free)
    if axis == "h":
        left = obst.intersection(box(-big, lo, px, hi))
        right = obst.intersection(box(px, lo, big, hi))
        x_a = left.bounds[2] if not left.is_empty else fx0
        x_b = right.bounds[0] if not right.is_empty else fx1
        return box(x_a, lo, x_b, hi) if x_b > x_a else None
    below = obst.intersection(box(lo, -big, hi, py))
    above = obst.intersection(box(lo, py, hi, big))
    y_a = below.bounds[3] if not below.is_empty else fy0
    y_b = above.bounds[1] if not above.is_empty else fy1
    return box(lo, y_a, hi, y_b) if y_b > y_a else None
