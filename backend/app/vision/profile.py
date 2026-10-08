"""Seitenprofil, Ruhelage, Abgleich mit Draufsicht, Parallaxenkorrektur (Plan B/E)."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from shapely import affinity
from shapely.geometry import LineString, Polygon
from shapely.validation import make_valid

from .contour import Frame, pca_frame, polygon_local
from .pose import CameraPose, correct_points

DS = 0.5


@dataclass
class SideProfile:
    s: np.ndarray
    bottom: np.ndarray
    top: np.ndarray
    missing: np.ndarray            # bool: interpoliert
    scale: float                   # Längenanpassung Seite -> Draufsicht
    tilt_deg: float
    frame: Frame
    flip_lr: bool
    flip_ud: bool


@dataclass
class ObjectGeometry:
    contour: np.ndarray            # objekt-lokal (N,2), x = 0..L, y quer (CAD-y oben)
    length: float
    width: float
    profile: SideProfile
    warnings: list[str] = field(default_factory=list)


def columns(poly: Polygon, grid: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lo = np.full(len(grid), np.nan)
    hi = np.full(len(grid), np.nan)
    y0, y1 = poly.bounds[1] - 1, poly.bounds[3] + 1
    for i, x in enumerate(grid):
        g = LineString([(x, y0), (x, y1)]).intersection(poly)
        if not g.is_empty:
            b = g.bounds
            lo[i], hi[i] = b[1], b[3]
    missing = np.isnan(lo)
    if missing.all():
        raise ValueError("Silhouette leer")
    idx = np.arange(len(grid))
    for a in (lo, hi):
        a[missing] = np.interp(idx[missing], idx[~missing], a[~missing])
    return lo, hi, missing


def _cross(a, b) -> float:
    return float(a[0] * b[1] - a[1] * b[0])


def _largest(g) -> Polygon:
    g = make_valid(g).buffer(0)
    if g.geom_type == "Polygon":
        return g
    return max((x for x in g.geoms if x.geom_type == "Polygon"), key=lambda x: x.area)


def _lower_hull(pts: np.ndarray) -> np.ndarray:
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]
    h: list[np.ndarray] = []
    for p in pts:
        while len(h) >= 2 and _cross(h[-1] - h[-2], p - h[-2]) <= 0:
            h.pop()
        h.append(p)
    return np.array(h)


def rest_pose(poly: Polygon) -> tuple[Polygon, float]:
    """Dreht die Silhouette so, dass das Hüllsegment unter dem Schwerpunkt horizontal liegt."""
    pts = np.asarray(poly.exterior.coords)[:-1]
    hull = _lower_hull(pts)
    cx = poly.centroid.x
    for a, b in zip(hull[:-1], hull[1:]):
        if a[0] <= cx <= b[0] and b[0] - a[0] > 1e-9:
            ang = np.arctan2(b[1] - a[1], b[0] - a[0])
            return affinity.rotate(poly, -ang, origin=poly.centroid, use_radians=True), float(np.degrees(ang))
    return poly, 0.0


def width_profile(top_local: Polygon, grid: np.ndarray) -> np.ndarray:
    lo, hi, _ = columns(top_local, grid)
    return hi - lo


def side_profile(side_poly: Polygon, length: float, flip_lr: bool, flip_ud: bool,
                 frame: Frame | None = None) -> SideProfile:
    frame = frame or pca_frame(side_poly)
    loc = polygon_local(side_poly, frame)
    x0, x1 = loc.bounds[0], loc.bounds[2]
    k = length / (x1 - x0)
    loc = affinity.scale(loc, k, k, origin=(x0, 0))
    loc = affinity.translate(loc, -x0, 0)
    if flip_lr:
        loc = affinity.scale(loc, -1, 1, origin=(length / 2, 0))
    if flip_ud:
        loc = affinity.scale(loc, 1, -1, origin=(0, 0))
    loc, tilt = rest_pose(loc)
    grid = np.arange(0, length + DS / 2, DS)
    lo, hi, missing = columns(loc, grid)
    z0 = lo.min()
    return SideProfile(grid, lo - z0, hi - z0, missing, float(k), tilt, frame, flip_lr, flip_ud)


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    a = (a - a.mean()) / (a.std() + 1e-9)
    b = (b - b.mean()) / (b.std() + 1e-9)
    return float((a * b).mean())


def auto_flip_lr(side_poly: Polygon, top_local: Polygon, length: float) -> bool:
    grid = np.arange(0, length + DS / 2, DS)
    wp = width_profile(top_local, grid)
    best, best_c = False, -2.0
    for flip in (False, True):
        sp = side_profile(side_poly, length, flip, False)
        c = _corr(wp, sp.top - sp.bottom)
        if c > best_c:
            best, best_c = flip, c
    return best


def correct_polygon(poly: Polygon, pose: CameraPose, frame: Frame, s_of_x, h_low, h_high,
                    step: float = 0.2) -> Polygon:
    """Parallaxenkorrektur per Visual Hull: Ein Punkt q der Papierebene gehört zum wahren
    Fußabdruck, wenn die Projektionen seiner senkrechten Strecke (Höhen h_low(s)..h_high(s))
    in der Silhouette liegen. s_of_x: lokal-x -> s; h_*: s -> Höhe (mm)."""
    from shapely import contains_xy

    x0, y0, x1, y1 = poly.bounds
    gx, gy = np.meshgrid(np.arange(x0 - 10, x1 + 10, step), np.arange(y0 - 10, y1 + 10, step))
    q = np.column_stack([gx.ravel(), gy.ravel()])
    sq = s_of_x(frame.to_local(q)[:, 0])
    c = np.array(pose.C_mm[:2])
    ok = np.ones(len(q), bool)
    for hfn in (h_low, h_high):
        h = np.asarray(hfn(sq), float)
        p = c + (q - c) / (1.0 - h / pose.C_mm[2])[:, None]       # Projektion in die Papierebene
        ok &= contains_xy(poly, p[:, 0], p[:, 1])
    m = ok.reshape(gx.shape).astype(np.uint8)
    import cv2
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return poly
    cnt = max(cnts, key=cv2.contourArea).reshape(-1, 2).astype(float)
    pts = np.column_stack([gx[0, 0] + cnt[:, 0] * step, gy[0, 0] + cnt[:, 1] * step])
    return _largest(Polygon(pts)).buffer(step / 5, join_style=2).simplify(0.1)


def build_object(top_poly: Polygon, side_poly: Polygon, top_pose: CameraPose, side_pose: CameraPose,
                 flip_lr: bool | None = None, flip_ud: bool = False,
                 calipers: dict | None = None, iterations: int = 2) -> ObjectGeometry:
    warns: list[str] = []
    f_top = pca_frame(top_poly)
    top_loc = polygon_local(top_poly, f_top)
    length = top_loc.bounds[2] - top_loc.bounds[0]
    grid = np.arange(0, length + DS / 2, DS)
    f_side = pca_frame(side_poly)
    if flip_lr is None:
        flip_lr = auto_flip_lr(side_poly, top_loc, length)

    def make_s_of_x(frame: Frame, cur: Polygon, flip: bool):
        bx = polygon_local(cur, frame).bounds
        mid = (bx[0] + bx[2]) / 2

        def f(x):
            s = np.asarray(x) - mid + length / 2
            return length - s if flip else s
        return f

    prof = side_profile(side_poly, length, flip_lr, flip_ud, f_side)
    top_c, top_c_frame = top_poly, f_top
    side_c = side_poly
    for _ in range(iterations):
        wp = width_profile(polygon_local(top_c, top_c_frame), grid)
        side_c = correct_polygon(side_poly, side_pose, f_side, make_s_of_x(f_side, side_c, flip_lr),
                                 lambda s: np.zeros_like(s), lambda s: np.interp(s, grid, wp))
        prof = side_profile(side_c, length, flip_lr, flip_ud, pca_frame(side_c))
        top_c = correct_polygon(top_poly, top_pose, f_top, make_s_of_x(f_top, top_c, False),
                                lambda s: np.interp(s, prof.s, prof.bottom),
                                lambda s: np.interp(s, prof.s, prof.top))
        top_c_frame = pca_frame(top_c)

    loc = polygon_local(top_c, top_c_frame)
    contour = np.asarray(loc.exterior.coords)[:-1]
    L = float(contour[:, 0].max() - contour[:, 0].min())
    W = float(contour[:, 1].max() - contour[:, 1].min())
    # Seite erneut passend zur korrigierten Länge
    prof = side_profile(side_c, L, flip_lr, flip_ud, pca_frame(side_c))

    if abs(prof.scale - 1) > 0.03:
        warns.append(f"Länge Seitenfoto weicht {abs(prof.scale - 1) * 100:.1f} % von der Draufsicht ab")
    if abs(prof.tilt_deg) > 5:
        warns.append(f"Kippwinkel Ruhelage {prof.tilt_deg:.1f}°")
    if prof.missing.any():
        warns.append(f"{int(prof.missing.sum())} Profilspalten interpoliert (Finger?)")
    warns += list(top_pose.warnings) + list(side_pose.warnings)
    warns = list(dict.fromkeys(warns))

    calipers = calipers or {}
    if calipers.get("length"):
        k = calipers["length"] / L
        contour, L, W = contour * k, L * k, W * k
        prof.s, prof.bottom, prof.top = prof.s * k, prof.bottom * k, prof.top * k
    if calipers.get("max_thickness"):
        kz = calipers["max_thickness"] / float(prof.top.max())
        prof.bottom, prof.top = prof.bottom * kz, prof.top * kz
    if calipers.get("length"):
        grid = np.arange(0, L + DS / 2, DS)
        prof.bottom, prof.top = np.interp(grid, prof.s, prof.bottom), np.interp(grid, prof.s, prof.top)
        prof.missing = np.zeros(len(grid), bool)
        prof.s = grid
    return ObjectGeometry(contour, L, W, prof, warns)
