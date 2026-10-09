"""Seitenprofil, Ruhelage, Abgleich mit Draufsicht, Parallaxenkorrektur (Plan B/E)."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.ndimage import maximum_filter1d, minimum_filter1d
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
    cut: str | None = None
    side_length: float = 0.0


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
    from .contour import largest_polygon
    p = largest_polygon(g)
    if p is None:
        raise ValueError("Kontur ergibt keine Fläche")
    return p


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


def _align(x0: float, x1: float, length: float, cut: str | None) -> tuple[float, float]:
    """Längsausrichtung der Seitensilhouette auf die Draufsicht: s = k*(x - x0) + t.
    cut = 'min'/'max': dieses Ende ist (z. B. von der Hand) verdeckt -> das freie Ende bündig
    setzen, nicht skalieren. Sonst zentrieren; Skalierung nur bei kleiner Abweichung (<= 5 %)."""
    ls = x1 - x0
    if cut == "min":
        return 1.0, length - ls
    if cut == "max":
        return 1.0, 0.0
    k = length / ls if abs(length / ls - 1) <= 0.05 else 1.0
    return k, (length - k * ls) / 2


def cut_end(frame: Frame, poly: Polygon, cut_point) -> str | None:
    """Welches Ende (lokal-x min/max) liegt am entfernten Handbereich?"""
    if cut_point is None:
        return None
    loc = polygon_local(poly, frame)
    x0, x1 = loc.bounds[0], loc.bounds[2]
    cx = float(frame.to_local(np.asarray([cut_point], float))[0, 0])
    return "min" if abs(cx - x0) < abs(cx - x1) else "max"


def side_profile(side_poly: Polygon, length: float, flip_lr: bool, flip_ud: bool,
                 frame: Frame | None = None, cut_point=None) -> SideProfile:
    frame = frame or pca_frame(side_poly)
    loc = polygon_local(side_poly, frame)
    x0, x1 = loc.bounds[0], loc.bounds[2]
    cut = cut_end(frame, side_poly, cut_point)
    k, t = _align(x0, x1, length, cut)
    loc = affinity.scale(loc, k, k, origin=(x0, 0))
    loc = affinity.translate(loc, t - x0, 0)
    if flip_lr:
        loc = affinity.scale(loc, -1, 1, origin=(length / 2, 0))
    if flip_ud:
        loc = affinity.scale(loc, 1, -1, origin=(0, 0))
    loc, tilt = rest_pose(loc)
    grid = np.arange(0, length + DS / 2, DS)
    lo, hi, missing = columns(loc, grid)
    z0 = lo.min()
    sp = SideProfile(grid, lo - z0, hi - z0, missing, float(k), tilt, frame, flip_lr, flip_ud)
    sp.cut = cut
    sp.side_length = float(x1 - x0)
    return sp


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    a = (a - a.mean()) / (a.std() + 1e-9)
    b = (b - b.mean()) / (b.std() + 1e-9)
    return float((a * b).mean())


def auto_flip_lr(side_poly: Polygon, top_local: Polygon, length: float, cut_point=None) -> bool:
    grid = np.arange(0, length + DS / 2, DS)
    wp = width_profile(top_local, grid)
    best, best_c = False, -2.0
    for flip in (False, True):
        sp = side_profile(side_poly, length, flip, False, cut_point=cut_point)
        ok = ~sp.missing
        if ok.sum() < 10:
            continue
        c = _corr(wp[ok], (sp.top - sp.bottom)[ok])
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
                 calipers: dict | None = None, iterations: int = 2, cut_point=None) -> ObjectGeometry:
    """cut_point: Papier-mm-Punkt des entfernten Handbereichs im Seitenfoto (oder None)."""
    warns: list[str] = []
    f_top = pca_frame(top_poly)
    top_loc = polygon_local(top_poly, f_top)
    length = top_loc.bounds[2] - top_loc.bounds[0]
    grid = np.arange(0, length + DS / 2, DS)
    f_side = pca_frame(side_poly)
    if flip_lr is None:
        flip_lr = auto_flip_lr(side_poly, top_loc, length, cut_point)

    def side_s_of_x(frame: Frame, cur: Polygon, flip: bool, L: float):
        bx = polygon_local(cur, frame).bounds
        k, t = _align(bx[0], bx[2], L, cut_end(frame, cur, cut_point))

        def f(x):
            s = k * (np.asarray(x) - bx[0]) + t
            return L - s if flip else s
        return f

    def top_s_of_x(frame: Frame, cur: Polygon):
        x0 = polygon_local(cur, frame).bounds[0]
        return lambda x: np.asarray(x) - x0

    prof = side_profile(side_poly, length, flip_lr, flip_ud, f_side, cut_point)
    top_c, top_c_frame = top_poly, f_top
    side_c = side_poly
    win = int(round(3.0 / DS)) * 2 + 1          # ±3 mm: Enden (Breite -> 0) nicht als Höhe 0 werten
    for _ in range(iterations):
        top_loc_c = polygon_local(top_c, top_c_frame)
        length = top_loc_c.bounds[2] - top_loc_c.bounds[0]
        grid = np.arange(0, length + DS / 2, DS)
        wp = maximum_filter1d(width_profile(top_loc_c, grid), win, mode="nearest")
        side_c = correct_polygon(side_poly, side_pose, f_side, side_s_of_x(f_side, side_c, flip_lr, length),
                                 lambda s: np.zeros_like(s), lambda s, g=grid, w=wp: np.interp(s, g, w))
        prof = side_profile(side_c, length, flip_lr, flip_ud, pca_frame(side_c), cut_point)
        top_c = correct_polygon(top_poly, top_pose, f_top, top_s_of_x(f_top, top_c),
                                lambda s, p=prof: np.interp(s, p.s, minimum_filter1d(p.bottom, win, mode="nearest")),
                                lambda s, p=prof: np.interp(s, p.s, maximum_filter1d(p.top, win, mode="nearest")))
        top_c_frame = pca_frame(top_c)

    # Plausibilität: unbrauchbares Seitenprofil (z. B. Hand im Umriss) darf die Draufsicht nicht zerstören
    raw_w = top_loc.bounds[3] - top_loc.bounds[1]
    implausible = float(prof.top.max()) > 1.5 * raw_w or top_c.area < 0.8 * top_poly.area
    if implausible:
        warns.append("Seitenprofil unplausibel (viel dicker als breit). Ist die Hand noch im Umriss der Seitenansicht? "
                     "Die Draufsicht wurde deshalb nicht korrigiert.")
        top_c, top_c_frame = top_poly, f_top
    loc = polygon_local(top_c, top_c_frame)
    contour = np.asarray(loc.exterior.coords)[:-1]
    L = float(contour[:, 0].max() - contour[:, 0].min())
    W = float(contour[:, 1].max() - contour[:, 1].min())
    # Seite erneut passend zur korrigierten Länge
    prof = side_profile(side_c, L, flip_lr, flip_ud, pca_frame(side_c), cut_point)

    dev = prof.side_length / L - 1
    if prof.cut and -dev * L >= 1.0:
        warns.append(f"Seitenfoto: ein Ende war von der Hand verdeckt, {-dev * L:.0f} mm Profil ergänzt")
    elif not prof.cut and abs(dev) > 0.03:
        warns.append(f"Länge Seitenfoto weicht {abs(dev) * 100:.1f} % von der Draufsicht ab")
    if abs(prof.tilt_deg) > 5:
        warns.append(f"Kippwinkel Ruhelage {prof.tilt_deg:.1f}°")
    if prof.missing.sum() * DS >= 1.0 and not prof.cut:
        warns.append(f"{prof.missing.sum() * DS:.0f} mm des Profils ergänzt (verdeckt oder nicht erkannt)")
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


# ---- Unterseite als Stützpunkte -----------------------------------------------------------

def _rdp(pts: np.ndarray, eps: float) -> list[int]:
    """Douglas-Peucker: Indizes der behaltenen Punkte."""
    def rec(i: int, j: int, out: list[int]) -> None:
        a, b = pts[i], pts[j]
        d = b - a
        L = float(np.hypot(*d)) or 1e-9
        seg = pts[i + 1:j]
        if len(seg) == 0:
            return
        dist = np.abs(d[0] * (seg[:, 1] - a[1]) - d[1] * (seg[:, 0] - a[0])) / L
        k = int(np.argmax(dist))
        if dist[k] > eps:
            m = i + 1 + k
            rec(i, m, out)
            out.append(m)
            rec(m, j, out)
    out = [0]
    rec(0, len(pts) - 1, out)
    out.append(len(pts) - 1)
    return sorted(set(out))


def bottom_points(s, bottom, max_points: int = 12, min_points: int = 5) -> list[list[float]]:
    """Unterseite auf wenige Stützpunkte reduzieren (Startwert für die Handkorrektur).
    Erst leicht glätten (Pixelrauschen), dann Douglas-Peucker mit wachsender Toleranz."""
    s = np.asarray(s, float)
    z = np.asarray(bottom, float)
    from scipy.ndimage import median_filter
    z = median_filter(z, size=7, mode="nearest")
    pts = np.column_stack([s, z])
    eps = 0.3
    idx = _rdp(pts, eps)
    while len(idx) > max_points and eps < 20:
        eps *= 1.3
        idx = _rdp(pts, eps)
    if len(idx) < min_points:                      # gleichmäßig ergänzen, damit man etwas zum Greifen hat
        extra = np.linspace(0, len(s) - 1, min_points).astype(int)
        idx = sorted(set(idx) | set(int(i) for i in extra))
    out = [[round(float(s[i]), 2), round(max(0.0, float(z[i])), 2)] for i in idx]
    zmin = min(p[1] for p in out)
    return [[p[0], round(p[1] - zmin, 2)] for p in out]


def bottom_from_points(s, points) -> np.ndarray:
    pts = sorted((float(a), float(b)) for a, b in points)
    xs = np.array([p[0] for p in pts])
    zs = np.array([p[1] for p in pts])
    z = np.interp(np.asarray(s, float), xs, zs)
    return z - z.min()


# ---- Unterseite als wenige Ebenen (Taschenboden in Stufen) ---------------------------------

def _gap_costs(z: np.ndarray, min_n: int) -> tuple[np.ndarray, np.ndarray]:
    """cost[i, j] = Luft unter dem Werkzeug, wenn der Boden im Abschnitt [i, j) auf dessen
    tiefstem Punkt liegt (Summe z - min). lvl[i, j] = dieser tiefste Punkt."""
    n = len(z)
    cost = np.full((n + 1, n + 1), np.inf)
    lvl = np.zeros((n + 1, n + 1))
    for i in range(n):
        m, acc = np.inf, 0.0
        for j in range(i + 1, n + 1):
            m = min(m, z[j - 1])
            acc += z[j - 1]
            if j - i >= min_n:
                cost[i, j] = acc - (j - i) * m
                lvl[i, j] = m
    return cost, lvl


def _segment(cost: np.ndarray, k: int) -> tuple[float, list[int]]:
    n = cost.shape[0] - 1
    best = np.full((k + 1, n + 1), np.inf)
    arg = np.zeros((k + 1, n + 1), int)
    best[0, 0] = 0.0
    for kk in range(1, k + 1):
        for j in range(1, n + 1):
            c = best[kk - 1, :j] + cost[:j, j]
            i = int(np.argmin(c))
            best[kk, j], arg[kk, j] = c[i], i
    if not np.isfinite(best[k, n]):
        return np.inf, []
    cuts, j = [n], n
    for kk in range(k, 0, -1):
        j = arg[kk, j]
        cuts.append(j)
    return float(best[k, n]), cuts[::-1]


def fit_levels(s, bottom, reliable=None, count: int | None = None, max_levels: int = 5,
               min_len: float = 10.0) -> list[list[float]]:
    """Unterseite durch wenige waagrechte Ebenen ersetzen (Zange: Backen, Griffschutz, Griffe).

    Jede Ebene liegt auf dem tiefsten Punkt des Werkzeugs in ihrem Abschnitt: das Werkzeug liegt
    so auf allen Ebenen auf und kann nicht wippen. Die Abschnittsgrenzen werden so gelegt, dass
    möglichst wenig Luft unter dem Werkzeug bleibt (Rampen landen in der tieferen Ebene).
    reliable: Maske der verlässlichen Spalten (verdeckte/ergänzte Stellen zählen nicht).
    count: feste Anzahl Ebenen, sonst automatisch (1..max_levels).
    Rückgabe [[a, b, z], ...] lückenlos von 0 bis L, tiefste Ebene z = 0."""
    from scipy.ndimage import median_filter
    s = np.asarray(s, float)
    z = median_filter(np.asarray(bottom, float), size=9, mode="nearest")     # ±2 mm Pixelrauschen
    ok = np.ones(len(s), bool) if reliable is None else np.asarray(reliable, bool)
    if ok.sum() < 10:
        ok = np.ones(len(s), bool)
    step = max(1, int(round(1.0 / max(s[1] - s[0], 1e-6))))                 # 1-mm-Raster für die Suche
    idx = np.nonzero(ok)[0][::step]
    ss, zz = s[idx], z[idx]
    L = float(s[-1])
    min_n = max(2, int(round(min_len / max(ss[1] - ss[0], 1e-6)))) if len(ss) > 1 else 1
    cost, lvl = _gap_costs(zz, min_n)
    kmax = max(1, min(max_levels, len(zz) // min_n))
    sols = {k: _segment(cost, k) for k in range(1, kmax + 1)}
    if count:
        k = min(count, kmax)
        while k > 1 and not sols[k][1]:
            k -= 1
    else:
        span = max(float(ss[-1] - ss[0]), 1.0)
        gap = {k: sols[k][0] / len(zz) for k in sols if sols[k][1]}   # mittlere Luft unter dem Werkzeug
        k = 1
        while k + 1 in gap and gap[k] > 0.6 and gap[k] - gap[k + 1] > 0.25 * (span / 150):
            k += 1
    cuts = sols[k][1]
    levels = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        sa = 0.0 if a == 0 else float((ss[a - 1] + ss[a]) / 2)
        sb = L if b == len(ss) else float((ss[b - 1] + ss[b]) / 2)
        levels.append([sa, sb, float(lvl[a, b])])
    if not count:                       # feste Anzahl gewünscht: nichts zusammenlegen
        levels = _tidy_levels(levels, L)
    zmin = min(lv[2] for lv in levels)
    return [[round(a, 1), round(b, 1), round(zv - zmin, 2)] for a, b, zv in levels]


def best_tilt(s, bottom, reliable=None, max_deg: float = 6.0, steps: int = 49,
              level_cost: float = 0.15) -> float:
    """Neigung (Steigung mm/mm), bei der die Unterseite am besten auf wenigen waagrechten Ebenen
    aufliegt. Die Ruhelage auf einem flachen Tisch (Hüllkurve) kippt z. B. eine Zange auf
    Griffschutz und Griffende, der gerade Griff wirkt dann schräg. In der Tasche gibt es aber
    Stufen: gerade Unterseiten sollen waagrecht liegen. Kosten = mittlere Luft unter dem
    Werkzeug + kleiner Aufschlag je Ebene."""
    from scipy.ndimage import median_filter
    s = np.asarray(s, float)
    b = np.asarray(bottom, float)
    ok = np.ones(len(s), bool) if reliable is None else np.asarray(reliable, bool)
    if ok.sum() < 10:
        ok = np.ones(len(s), bool)
    best_k, best_c = 0.0, np.inf
    for k in np.tan(np.radians(np.linspace(-max_deg, max_deg, steps))):
        z = b + k * s
        zf = median_filter(z, size=9, mode="nearest")
        lv = fit_levels(s, z, ok)
        floor = bottom_from_levels(s, lv) + zf[ok].min()
        c = float(np.mean((zf - floor)[ok])) + level_cost * len(lv) + 1e-3 * abs(k)
        if c < best_c:
            best_k, best_c = float(k), c
    return best_k


def _tidy_levels(levels: list[list[float]], L: float, min_step: float = 0.8) -> list[list[float]]:
    """Fast gleich hohe Nachbarn verbinden (tiefere Ebene gewinnt), kurze hohe Enden entfernen
    (z. B. Rest der Hand am Bildrand: dort ginge der Boden sonst sinnlos wieder hoch)."""
    out = [list(lv) for lv in levels]
    changed = True
    while changed and len(out) > 1:
        changed = False
        for i in range(len(out) - 1):
            if abs(out[i][2] - out[i + 1][2]) < min_step:
                out[i] = [out[i][0], out[i + 1][1], min(out[i][2], out[i + 1][2])]
                del out[i + 1]
                changed = True
                break
        for i in (0, len(out) - 1):
            if len(out) < 2:
                break
            j = 1 if i == 0 else len(out) - 2
            if out[i][1] - out[i][0] < 0.15 * L and out[i][2] > out[j][2]:
                a, b = min(out[i][0], out[j][0]), max(out[i][1], out[j][1])
                out[j] = [a, b, out[j][2]]
                del out[i]
                changed = True
                break
    return out


def normalize_levels(levels, L: float, keep_ref: bool = False) -> list[list[float]]:
    """Von Hand bearbeitete Ebenen säubern: sortiert, lückenlos 0..L, tiefste Ebene = 0
    (keep_ref: Höhen unverändert lassen)."""
    lv = sorted(([float(a), float(b), float(z)] for a, b, z in levels), key=lambda q: q[0])
    lv = [q for q in lv if q[1] > q[0]] or [[0.0, L, 0.0]]
    lv[0][0] = 0.0
    for i in range(1, len(lv)):
        lv[i][0] = lv[i - 1][1] = min(max(lv[i][0], lv[i - 1][0] + 1.0), L)
    lv[-1][1] = L
    lv = [q for q in lv if q[1] - q[0] >= 0.5]
    zmin = 0.0 if keep_ref else min(q[2] for q in lv)
    return [[round(a, 1), round(b, 1), round(z - zmin, 2)] for a, b, z in lv]


def bottom_from_levels(s, levels) -> np.ndarray:
    s = np.asarray(s, float)
    z = np.full(len(s), levels[-1][2], float)
    for a, b, zv in reversed(levels):
        z[(s >= a) & (s < b)] = zv
    return z


def smooth_top(s, top, bottom, window_mm: float = 3.0) -> np.ndarray:
    """Oberseite glätten (zählt nur für die Gesamtdicke), nie unter der Unterseite."""
    from scipy.ndimage import median_filter, uniform_filter1d
    t = np.asarray(top, float)
    n = max(3, int(round(window_mm / DS)) | 1)
    t = uniform_filter1d(median_filter(t, size=n, mode="nearest"), n, mode="nearest")
    return np.maximum(t, np.asarray(bottom, float) + 0.5)
