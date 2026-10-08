from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from .. import storage
from ..geometry.samples import synthetic_pliers
from ..schemas import ObjectSpec, Profile
from ..vision import a4, contour, exif, pose, profile, segment

router = APIRouter(prefix="/objects", tags=["objects"])

VIEW_SCALE = 0.5          # Anzeigebild der entzerrten Ansicht
PREVIEW_MAX = 2000        # Anzeigebild des Originals


def _obj(oid: str) -> ObjectSpec:
    try:
        return storage.load_object(oid)
    except KeyError:
        raise HTTPException(404, "Objekt nicht gefunden") from None


def _check_view(view: str) -> None:
    if view not in ("top", "side"):
        raise HTTPException(422, "view muss top oder side sein")


def _photo(spec: ObjectSpec, view: str) -> dict:
    ph = spec.photos.get(view)
    if not ph:
        raise HTTPException(409, f"Foto '{view}' fehlt")
    return ph


def _load(spec: ObjectSpec, view: str):
    ph = _photo(spec, view)
    bgr, f35 = exif.load_image(storage.object_dir(spec.id) / ph["original"])
    return bgr, f35, ph


def _write_jpg(path: Path, img: np.ndarray, q: int = 90) -> None:
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, q])


def _process_corners(spec: ObjectSpec, view: str, bgr, f35, corners) -> dict:
    d = storage.object_dir(spec.id)
    ph = spec.photos[view]
    ph["corners_px"] = np.asarray(corners, float).tolist()
    p = pose.estimate_pose(corners, bgr.shape, f35)
    ph["pose"] = {"C_mm": list(p.C_mm), "f_px": p.f_px, "f35_assumed": p.f35_assumed, "warnings": list(p.warnings)}
    rect = a4.rectify(bgr, np.asarray(corners, np.float32))
    small = cv2.resize(rect, None, fx=VIEW_SCALE, fy=VIEW_SCALE, interpolation=cv2.INTER_AREA)
    _write_jpg(d / f"{view}_rect_view.jpg", small)
    ph["rectified_url"] = storage.url_for(d / f"{view}_rect_view.jpg")
    ph["view_scale"] = VIEW_SCALE
    ph["rect_size"] = [a4.RECT_W, a4.RECT_H]
    ph.pop("mask_url", None)
    return rect


class CornersBody(BaseModel):
    corners_px: list[list[float]]


class SegmentBody(BaseModel):
    pos: list[list[float]] = []
    neg: list[list[float]] = []
    fill_holes: bool = True
    use_sam: bool = True


class ProfileBody(BaseModel):
    side_flip_lr: bool | None = None
    side_flip_ud: bool | None = None
    calipers: dict[str, float] | None = None
    profile_overrides: dict[str, list[float]] | None = None


@router.post("", response_model=ObjectSpec)
def create(body: dict) -> ObjectSpec:
    return storage.create_object(body.get("name") or "Neues Objekt")


@router.post("/demo", response_model=ObjectSpec)
def create_demo() -> ObjectSpec:
    demo = synthetic_pliers()
    spec = storage.create_object("Spitzzange (Demo)", contour_mm=demo.contour_mm, length_mm=demo.length_mm,
                                 width_mm=demo.width_mm, profile=demo.profile)
    return spec


@router.get("", response_model=list[ObjectSpec])
def list_() -> list[ObjectSpec]:
    return storage.list_objects()


@router.get("/{oid}", response_model=ObjectSpec)
def get(oid: str) -> ObjectSpec:
    return _obj(oid)


@router.put("/{oid}", response_model=ObjectSpec)
def rename(oid: str, body: dict) -> ObjectSpec:
    spec = _obj(oid)
    spec.name = body.get("name", spec.name)
    storage.save_object(spec)
    return spec


@router.delete("/{oid}")
def delete(oid: str) -> dict:
    storage.delete_object(oid)
    return {"ok": True}


@router.post("/{oid}/photos/{view}")
async def upload_photo(oid: str, view: str, file: UploadFile = File(...)) -> dict:
    _check_view(view)
    spec = _obj(oid)
    d = storage.object_dir(oid)
    ext = Path(file.filename or "x.jpg").suffix.lower() or ".jpg"
    name = f"{view}_original{ext}"
    for old in d.glob(f"{view}_*"):
        old.unlink()
    (d / name).write_bytes(await file.read())
    try:
        bgr, f35 = exif.load_image(d / name)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"Bild nicht lesbar: {e}") from e
    h, w = bgr.shape[:2]
    k = min(1.0, PREVIEW_MAX / max(h, w))
    _write_jpg(d / f"{view}_preview.jpg", cv2.resize(bgr, None, fx=k, fy=k, interpolation=cv2.INTER_AREA))
    corners = a4.find_a4_corners(bgr)
    found = corners is not None
    if not found:   # Fallback: Bildrand-nahes Rechteck, Nutzer korrigiert
        corners = np.array([[w * .15, h * .2], [w * .85, h * .2], [w * .85, h * .8], [w * .15, h * .8]], np.float32)
    spec.photos[view] = {"original": name, "preview_url": storage.url_for(d / f"{view}_preview.jpg"),
                         "preview_scale": k, "size": [w, h], "f35": f35, "corners_found": found}
    _process_corners(spec, view, bgr, f35, corners)
    storage.save_object(spec)
    return spec.photos[view]


@router.put("/{oid}/photos/{view}/corners")
def set_corners(oid: str, view: str, body: CornersBody) -> dict:
    _check_view(view)
    if len(body.corners_px) != 4:
        raise HTTPException(422, "4 Ecken erwartet")
    spec = _obj(oid)
    bgr, f35, _ = _load(spec, view)
    _process_corners(spec, view, bgr, f35, a4.order_corners(np.array(body.corners_px, np.float32)))
    storage.save_object(spec)
    return spec.photos[view]


def _save_mask(spec: ObjectSpec, view: str, rect: np.ndarray, mask: np.ndarray, fill_holes: bool) -> dict:
    d = storage.object_dir(spec.id)
    ph = spec.photos[view]
    cv2.imwrite(str(d / f"{view}_mask.png"), mask)
    over = cv2.resize(rect, None, fx=VIEW_SCALE, fy=VIEW_SCALE, interpolation=cv2.INTER_AREA)
    m = cv2.resize(mask, (over.shape[1], over.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
    tint = over.copy()
    tint[m] = (0.45 * tint[m] + 0.55 * np.array([30, 120, 255])).astype(np.uint8)
    cnts, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(tint, cnts, -1, (0, 60, 255), 1)
    _write_jpg(d / f"{view}_overlay.jpg", tint)
    ph["mask_url"] = storage.url_for(d / f"{view}_mask.png")
    ph["overlay_url"] = storage.url_for(d / f"{view}_overlay.jpg")
    ph["fill_holes"] = fill_holes
    info: dict = {"mask_url": ph["mask_url"], "overlay_url": ph["overlay_url"]}
    try:
        poly = contour.mask_to_polygon(mask, fill_holes)
        info["contour_px"] = (a4.mm_to_rect_px(np.asarray(poly.exterior.coords)) * VIEW_SCALE).round(1).tolist()
        info["area_mm2"] = poly.area
        x0, y0, x1, y1 = segment.paper_rect_px(0.5)
        ys, xs = np.nonzero(mask)
        info["touches_paper_edge"] = bool(xs.min() <= x0 or xs.max() >= x1 or ys.min() <= y0 or ys.max() >= y1)
    except ValueError:
        info["contour_px"] = []
    storage.save_object(spec)
    return info


@router.post("/{oid}/photos/{view}/segment")
def run_segment(oid: str, view: str, body: SegmentBody) -> dict:
    _check_view(view)
    spec = _obj(oid)
    bgr, _, ph = _load(spec, view)
    rect = a4.rectify(bgr, np.asarray(ph["corners_px"], np.float32))
    ph["prompts"] = {"pos": body.pos, "neg": body.neg}
    mask = segment.segment(rect, body.pos, body.neg, use_sam=body.use_sam)
    if mask.max() == 0:
        raise HTTPException(422, "Nichts erkannt: Ecken prüfen oder positiven Klick setzen")
    info = _save_mask(spec, view, rect, mask, body.fill_holes)
    info["sam_used"] = bool(body.use_sam and segment.sam_available() and (body.pos or body.neg))
    return info


@router.put("/{oid}/photos/{view}/mask")
async def upload_mask(oid: str, view: str, file: UploadFile = File(...), fill_holes: bool = True) -> dict:
    _check_view(view)
    spec = _obj(oid)
    bgr, _, ph = _load(spec, view)
    data = np.frombuffer(await file.read(), np.uint8)
    m = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    if m is None:
        raise HTTPException(422, "PNG nicht lesbar")
    m = cv2.resize(m, (a4.RECT_W, a4.RECT_H), interpolation=cv2.INTER_NEAREST)
    mask = ((m > 127).astype(np.uint8)) * 255
    rect = a4.rectify(bgr, np.asarray(ph["corners_px"], np.float32))
    return _save_mask(spec, view, rect, mask, fill_holes)


@router.post("/{oid}/profile", response_model=ObjectSpec)
def compute_profile(oid: str, body: ProfileBody) -> ObjectSpec:
    spec = _obj(oid)
    if body.side_flip_lr is not None or "side_flip_lr" in body.model_fields_set:
        spec.side_flip_lr = body.side_flip_lr
    if body.side_flip_ud is not None:
        spec.side_flip_ud = body.side_flip_ud
    if body.calipers is not None:
        spec.calipers = {k: v for k, v in body.calipers.items() if v}
    d = storage.object_dir(oid)
    polys, poses = {}, {}
    for view in ("top", "side"):
        ph = _photo(spec, view)
        if not (d / f"{view}_mask.png").exists():
            raise HTTPException(409, f"Maske '{view}' fehlt")
        mask = cv2.imread(str(d / f"{view}_mask.png"), cv2.IMREAD_GRAYSCALE)
        polys[view] = contour.mask_to_polygon(mask, ph.get("fill_holes", True))
        pj = ph["pose"]
        poses[view] = pose.CameraPose(tuple(pj["C_mm"]), pj["f_px"], pj["f35_assumed"], tuple(pj["warnings"]))
    g = profile.build_object(polys["top"], polys["side"], poses["top"], poses["side"], spec.side_flip_lr,
                             spec.side_flip_ud, spec.calipers)
    ov = body.profile_overrides or {}
    bottom, top = g.profile.bottom.tolist(), g.profile.top.tolist()
    for key, arr in (("bottom", bottom), ("top", top)):
        if key in ov:
            if len(ov[key]) != len(arr):
                raise HTTPException(422, f"profile_overrides.{key}: Länge {len(arr)} erwartet")
            arr[:] = ov[key]
    zmin = min(bottom)
    bottom = [b - zmin for b in bottom]
    top = [t - zmin for t in top]
    spec.contour_mm = g.contour.round(3).tolist()
    spec.length_mm, spec.width_mm = round(g.length, 2), round(g.width, 2)
    spec.profile = Profile(ds=0.5, s=g.profile.s.round(3).tolist(), bottom=bottom, top=top)
    spec.flip_lr_used = g.profile.flip_lr
    spec.tilt_deg = round(g.profile.tilt_deg, 2)
    spec.warnings = g.warnings
    storage.save_object(spec)
    return spec
