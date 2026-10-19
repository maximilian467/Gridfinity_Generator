"""Auswertung eines Werkzeugs ohne HTTP: Foto ablegen, A4-Ecken, Maske, Profil.

Genutzt von der Objekt-API (Scan-Assistent, Schritt für Schritt) und vom Stapel-Scan im Projekt
(build_tasks.batch_scan_job, alles automatisch). Fehler kommen als ScanError mit HTTP-Status.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from . import storage
from .schemas import ObjectSpec, Profile
from .vision import a4, contour, exif, hands, pose, profile, segment

VIEW_SCALE = 0.5          # Anzeigebild der entzerrten Ansicht
PREVIEW_MAX = 2000        # Anzeigebild des Originals
FIT_VERSION = 2
VIEW_NAMES = {"top": "Draufsicht", "side": "Seitenansicht"}


class ScanError(ValueError):
    def __init__(self, msg: str, status: int = 422):
        super().__init__(msg)
        self.status = status


def photo(spec: ObjectSpec, view: str) -> dict:
    ph = spec.photos.get(view)
    if not ph:
        raise ScanError(f"Foto '{view}' fehlt", 409)
    return ph


def load(spec: ObjectSpec, view: str):
    ph = photo(spec, view)
    bgr, f35 = exif.load_image(storage.object_dir(spec.id) / ph["original"])
    return bgr, f35, ph


def write_jpg(path: Path, img: np.ndarray, q: int = 90) -> None:
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, q])


def fallback_corners(w: int, h: int) -> np.ndarray:
    """Bildrand-nahes Rechteck, wenn das Blatt nicht gefunden wird (Nutzer korrigiert)."""
    return np.array([[w * .15, h * .2], [w * .85, h * .2], [w * .85, h * .8], [w * .15, h * .8]], np.float32)


def store_photo(spec: ObjectSpec, view: str, data: bytes, ext: str):
    """Original und Vorschaubild ablegen (ersetzt ein altes Foto dieser Ansicht). Gibt (bgr, f35) zurück."""
    d = storage.object_dir(spec.id)
    tmp = d / f".upload{ext}"
    tmp.write_bytes(data)
    try:
        bgr, f35 = exif.load_image(tmp)
    except Exception:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        raise ScanError("Bild nicht lesbar (beschädigt oder zu groß)") from None
    for old in d.glob(f"{view}_*"):
        old.unlink()
    if view == "side":                    # neues Seitenfoto: wieder mit Seitenansicht auswerten
        spec.side_skipped = False
    name = f"{view}_original{ext}"
    tmp.replace(d / name)
    h, w = bgr.shape[:2]
    k = min(1.0, PREVIEW_MAX / max(h, w))
    write_jpg(d / f"{view}_preview.jpg", cv2.resize(bgr, None, fx=k, fy=k, interpolation=cv2.INTER_AREA))
    spec.photos[view] = {"original": name, "preview_url": storage.url_for(d / f"{view}_preview.jpg"),
                         "preview_scale": k, "size": [w, h], "f35": f35, "corners_found": False,
                         "corners_px": fallback_corners(w, h).tolist()}
    return bgr, f35


def process_corners(spec: ObjectSpec, view: str, bgr, f35, corners) -> np.ndarray:
    d = storage.object_dir(spec.id)
    ph = spec.photos[view]
    ph["corners_px"] = np.asarray(corners, float).tolist()
    p = pose.estimate_pose(corners, bgr.shape, f35)
    ph["pose"] = {"C_mm": list(p.C_mm), "f_px": p.f_px, "f35_assumed": p.f35_assumed, "warnings": list(p.warnings)}
    rect = a4.rectify(bgr, np.asarray(corners, np.float32))
    small = cv2.resize(rect, None, fx=VIEW_SCALE, fy=VIEW_SCALE, interpolation=cv2.INTER_AREA)
    write_jpg(d / f"{view}_rect_view.jpg", small)
    ph["rectified_url"] = storage.url_for(d / f"{view}_rect_view.jpg")
    ph["view_scale"] = VIEW_SCALE
    ph["rect_size"] = [a4.RECT_W, a4.RECT_H]
    ph.pop("mask_url", None)
    return rect


def detect_corners(spec: ObjectSpec, view: str, bgr, f35) -> bool:
    """A4-Blatt suchen und entzerren; ohne Fund das Ersatzrechteck. True, wenn gefunden."""
    corners = a4.find_a4_corners(bgr)
    found = corners is not None
    if not found:
        h, w = bgr.shape[:2]
        corners = fallback_corners(w, h)
    spec.photos[view]["corners_found"] = found
    process_corners(spec, view, bgr, f35, corners)
    return found


def rect_of(spec: ObjectSpec, view: str) -> np.ndarray:
    bgr, _, ph = load(spec, view)
    return a4.rectify(bgr, np.asarray(ph["corners_px"], np.float32))


def save_mask(spec: ObjectSpec, view: str, rect: np.ndarray, mask: np.ndarray, fill_holes: bool,
              hand: np.ndarray | None = None) -> dict:
    d = storage.object_dir(spec.id)
    ph = spec.photos[view]
    cv2.imwrite(str(d / f"{view}_mask.png"), mask)
    over = cv2.resize(rect, None, fx=VIEW_SCALE, fy=VIEW_SCALE, interpolation=cv2.INTER_AREA)
    m = cv2.resize(mask, (over.shape[1], over.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
    tint = over.copy()
    tint[m] = (0.45 * tint[m] + 0.55 * np.array([30, 120, 255])).astype(np.uint8)
    cnts, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(tint, cnts, -1, (0, 60, 255), 1)
    hand_f = d / f"{view}_hand.png"
    if hand is not None and hand.any():
        cv2.imwrite(str(hand_f), hand)
        ph["hand_url"] = storage.url_for(hand_f)
    elif hand is not None:
        hand_f.unlink(missing_ok=True)
        ph.pop("hand_url", None)
    if hand is not None and hand.any():
        hm = cv2.resize(hand, (over.shape[1], over.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
        stripes = ((np.add.outer(np.arange(hm.shape[0]), np.arange(hm.shape[1])) // 6) % 2 == 0)
        sel = hm & stripes
        tint[sel] = (0.35 * tint[sel] + 0.65 * np.array([90, 90, 90])).astype(np.uint8)
    write_jpg(d / f"{view}_overlay.jpg", tint)
    ph["mask_url"] = storage.url_for(d / f"{view}_mask.png")
    ph["overlay_url"] = storage.url_for(d / f"{view}_overlay.jpg")
    ph["fill_holes"] = fill_holes
    info: dict = {"mask_url": ph["mask_url"], "overlay_url": ph["overlay_url"], "hand_url": ph.get("hand_url")}
    try:
        poly = contour.mask_to_polygon(mask, fill_holes)
        info["contour_px"] = (a4.mm_to_rect_px(np.asarray(poly.exterior.coords)) * VIEW_SCALE).round(1).tolist()
        # wenige, gut ziehbare Punkte für den Punkte-Editor (Abweichung <= 0,4 mm)
        # Seitenansicht ruhiger (nur die Dicke zählt), Draufsicht genauer (Taschenkontur)
        edit = np.asarray(poly.simplify(0.8 if view == "side" else 0.4).exterior.coords)[:-1]
        ph["edit_contour_px"] = (a4.mm_to_rect_px(edit) * VIEW_SCALE).round(1).tolist()
        info["edit_contour_px"] = ph["edit_contour_px"]
        info["area_mm2"] = poly.area
        x0, y0, x1, y1 = segment.paper_rect_px(0.5)
        ys, xs = np.nonzero(mask)
        info["touches_paper_edge"] = bool(xs.min() <= x0 or xs.max() >= x1 or ys.min() <= y0 or ys.max() >= y1)
    except ValueError:
        info["contour_px"] = []
    storage.save_object(spec)
    return info


def segment_view(spec: ObjectSpec, view: str, pos=(), neg=(), fill_holes: bool = True, use_sam: bool = True,
                 remove_hand: bool = True) -> dict:
    """Werkzeug freistellen (Klicks optional), in der Seitenansicht die Hand entfernen, Maske speichern."""
    ph = photo(spec, view)
    rect = rect_of(spec, view)
    ph["prompts"] = {"pos": list(pos), "neg": list(neg)}
    mask = segment.segment(rect, pos, neg, use_sam=use_sam, holes=fill_holes)
    if mask.max() == 0:
        raise ScanError("Kein Werkzeug gefunden. Ecken prüfen oder mit 'Auswählen' auf das Werkzeug klicken.")
    hand_info: dict = {"hand_removed": False}
    hand = np.zeros_like(mask) if view == "side" else None
    ph.pop("cut_point_mm", None)
    top_mask_f = storage.object_dir(spec.id) / "top_mask.png"

    def top():   # Rückfallebene ohne SAM: Farbmodell aus der Draufsicht
        if not (top_mask_f.exists() and "top" in spec.photos):
            return None
        return rect_of(spec, "top"), cv2.imread(str(top_mask_f), cv2.IMREAD_GRAYSCALE)

    if view == "side" and remove_hand:
        res = hands.remove_hand_auto(rect, mask, top)
        if res is not None and res.applied:
            mask, hand = res.mask, res.hand
            # Berührungspunkt Hand/Werkzeug (Papier-mm) -> verdecktes Ende fürs Profil
            near = cv2.dilate(mask, np.ones((61, 61), np.uint8)) > 0
            ys, xs = np.nonzero((hand > 0) & near)
            if len(xs):
                ph["cut_point_mm"] = a4.rect_px_to_mm([[float(xs.mean()), float(ys.mean())]])[0].tolist()
            hand_info = {"hand_removed": True, "hand_frac": round(res.removed_frac, 3)}
    info = save_mask(spec, view, rect, mask, fill_holes, hand)
    info.update(hand_info)
    info["sam_used"] = bool(use_sam and segment.sam_available() and (len(pos) or len(neg)))
    return info


def _level_ref(measured, reliable) -> float:
    """Höhe der Messung, die der tiefsten Ebene (z = 0) entspricht (wie in fit_levels gefiltert)."""
    from scipy.ndimage import median_filter
    z = median_filter(measured, size=9, mode="nearest")
    return float(z[reliable].min()) if reliable.any() else float(z.min())


def _pose_of(ph: dict) -> pose.CameraPose:
    """Kamerapose aus den gespeicherten Ecken neu schätzen (gleiche Ecken, aktuelle Rechnung) und ablegen."""
    if ph.get("corners_px") and ph.get("size"):
        w, h = ph["size"]
        p = pose.estimate_pose(np.asarray(ph["corners_px"], np.float32), (h, w), ph.get("f35"))
        ph["pose"] = {"C_mm": list(p.C_mm), "f_px": p.f_px, "f35_assumed": p.f35_assumed, "warnings": list(p.warnings)}
        return p
    pj = ph["pose"]
    return pose.CameraPose(tuple(pj["C_mm"]), pj["f_px"], pj["f35_assumed"], tuple(pj["warnings"]))


def _view_polygon(spec: ObjectSpec, view: str):
    ph = photo(spec, view)
    f = storage.object_dir(spec.id) / f"{view}_mask.png"
    if not f.exists():
        raise ScanError(f"Maske '{view}' fehlt", 409)
    try:
        return contour.mask_to_polygon(cv2.imread(str(f), cv2.IMREAD_GRAYSCALE), ph.get("fill_holes", True))
    except ValueError:
        raise ScanError(f"Der Umriss der {VIEW_NAMES[view]} ist leer oder ungültig.") from None


def _profile_top_only(spec: ObjectSpec, levels=None) -> ObjectSpec:
    """Ohne Seitenfoto: Kontur aus der Draufsicht, ebene Unterseite, Dicke von Hand."""
    if not spec.thickness_mm:
        raise ScanError("Ohne Seitenfoto wird die Dicke des Werkzeugs gebraucht.", 422)
    poly = _view_polygon(spec, "top")
    g = profile.build_top_only(poly, _pose_of(photo(spec, "top")), spec.thickness_mm, spec.uniform_thickness,
                               spec.calipers)
    s_grid = g.profile.s
    L = float(s_grid[-1])
    old = spec.profile is not None and spec.profile.measured is not None   # vorher mit Seitenfoto
    lv = profile.normalize_levels(levels, L) if levels and not old else [[0.0, round(L, 1), 0.0]]
    b_arr = profile.bottom_from_levels(s_grid, lv)
    t_arr = np.maximum(float(spec.thickness_mm), b_arr + 0.5)
    spec.contour_mm = g.contour.round(3).tolist()
    spec.length_mm, spec.width_mm = round(g.length, 2), round(g.width, 2)
    spec.profile = Profile(ds=0.5, s=s_grid.round(3).tolist(), bottom=b_arr.tolist(), top=t_arr.round(3).tolist(),
                           levels=lv, measured=None, fit_version=FIT_VERSION)
    spec.flip_lr_used = None
    spec.tilt_deg = 0.0
    spec.warnings = g.warnings
    spec.profile_missing = [False] * len(s_grid)
    storage.save_object(spec)
    return spec


def compute_profile(spec: ObjectSpec, levels=None, level_count: int | None = None,
                    profile_overrides: dict[str, list[float]] | None = None) -> ObjectSpec:
    """Kontur und Höhenprofil aus beiden Masken (Spiegelung/Messschieber stehen schon in spec).
    Ohne Seitenfoto (side_skipped) nur aus der Draufsicht mit der Dicke von Hand."""
    if spec.side_skipped:
        return _profile_top_only(spec, levels)
    polys, poses = {}, {}
    for view in ("top", "side"):
        polys[view] = _view_polygon(spec, view)
        poses[view] = _pose_of(spec.photos[view])
    try:
        g = profile.build_object(polys["top"], polys["side"], poses["top"], poses["side"], spec.side_flip_lr,
                                 spec.side_flip_ud, spec.calipers, cut_point=spec.photos["side"].get("cut_point_mm"))
    except (ValueError, IndexError) as e:
        raise ScanError(f"Profil konnte nicht berechnet werden ({e}). Bitte die Umrisse prüfen.") from e
    ov = profile_overrides or {}
    s_grid = g.profile.s
    L = float(s_grid[-1])
    # verdeckte/ergänzte Stellen (Hand) zählen nicht für die Ebenen, inklusive eines Saums daneben
    reliable = ~np.asarray(g.profile.missing, bool)
    if g.profile.cut and not reliable.all():
        from scipy.ndimage import binary_dilation
        reliable &= ~binary_dilation(~reliable, iterations=int(round(15.0 / profile.DS)))   # Handreste
    # Neigung so, dass gerade Unterseiten waagrecht auf den Ebenen liegen (statt Tisch-Ruhelage)
    k_tilt = profile.best_tilt(s_grid, g.profile.bottom, reliable)
    measured = np.asarray(g.profile.bottom, float) + k_tilt * np.asarray(s_grid)
    top_raw = np.asarray(g.profile.top, float) + k_tilt * np.asarray(s_grid)
    zp = _level_ref(measured, reliable)       # Bezug: tiefster (gefilterter) Messpunkt = 0
    # Ebenen aus älterer Auswertung (andere Neigung) passen nicht mehr: dann neu erkennen
    # ebenso Ebenen aus der Auswertung ohne Seitenfoto (ohne Messung): die Seite liefert jetzt mehr
    old = spec.profile is not None and (spec.profile.fit_version < FIT_VERSION or spec.profile.measured is None)
    if levels and not old:                    # Handkorrektur, im selben Bezug wie Messung/Oberseite
        raw = profile.normalize_levels([[a, b, z] for a, b, z in levels], L, keep_ref=True)
        zp += min(q[2] for q in raw)          # tiefere Ebene = Werkzeug dort dicker: alles mitschieben
        lv = profile.normalize_levels(raw, L)
    else:
        lv = profile.fit_levels(s_grid, measured, reliable, count=level_count)
    b_arr = profile.bottom_from_levels(s_grid, lv)
    meas = measured - zp
    t_arr = profile.smooth_top(s_grid, top_raw - zp, np.minimum(b_arr, meas))
    bottom, top = b_arr.tolist(), t_arr.tolist()
    for key, arr in (("bottom", bottom), ("top", top)):
        if key in ov:
            if len(ov[key]) != len(arr):
                raise ScanError(f"profile_overrides.{key}: Länge {len(arr)} erwartet")
            arr[:] = ov[key]
    spec.contour_mm = g.contour.round(3).tolist()
    spec.length_mm, spec.width_mm = round(g.length, 2), round(g.width, 2)
    spec.profile = Profile(ds=0.5, s=g.profile.s.round(3).tolist(), bottom=bottom, top=top,
                           levels=lv, measured=np.round(meas, 2).tolist(), fit_version=FIT_VERSION)
    spec.flip_lr_used = g.profile.flip_lr
    spec.tilt_deg = round(g.profile.tilt_deg + float(np.degrees(np.arctan(k_tilt))), 2)
    spec.warnings = g.warnings
    spec.profile_missing = g.profile.missing.tolist()
    storage.save_object(spec)
    return spec
