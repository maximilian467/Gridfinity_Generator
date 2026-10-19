from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from typing import Annotated

from pydantic import BaseModel, Field

from .. import scan, storage
from ..auth import Principal, current_user
from ..geometry.samples import synthetic_pliers
from ..scan import ScanError
from ..schemas import ObjectSpec
from ..vision import a4, profile, segment

router = APIRouter(prefix="/objects", tags=["objects"])

MAX_PHOTO_BYTES = 40 * 1024 * 1024
MAX_MASK_BYTES = 8 * 1024 * 1024
PHOTO_TYPES = {".jpg", ".jpeg", ".png", ".webp"}


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"Datei zu groß (max. {limit // (1024 * 1024)} MB)")
    return data


def _obj(oid: str, user: Principal) -> ObjectSpec:
    try:
        return storage.load_object(oid, user)
    except KeyError:
        raise HTTPException(404, "Objekt nicht gefunden") from None


def _check_view(view: str) -> None:
    if view not in ("top", "side"):
        raise HTTPException(422, "view muss top oder side sein")


def _http(e: ScanError) -> HTTPException:
    return HTTPException(e.status, str(e))


Pt = Annotated[list[Annotated[float, Field(ge=-1e5, le=1e5)]], Field(min_length=2, max_length=2)]


class CornersBody(BaseModel):
    corners_px: Annotated[list[Pt], Field(min_length=4, max_length=4)]


class SegmentBody(BaseModel):
    pos: Annotated[list[Pt], Field(max_length=50)] = []
    neg: Annotated[list[Pt], Field(max_length=50)] = []
    fill_holes: bool = True
    use_sam: bool = True
    remove_hand: bool = True


class ProfileBody(BaseModel):
    side_flip_lr: bool | None = None
    side_flip_ud: bool | None = None
    calipers: dict[str, Annotated[float, Field(ge=0, le=2000)]] | None = Field(None, max_length=4)
    levels: Annotated[list[Annotated[list[float], Field(min_length=3, max_length=3)]],
                      Field(min_length=1, max_length=8)] | None = None      # Ebenen [a, b, z] (Handkorrektur)
    level_count: int | None = Field(None, ge=1, le=5)                        # Anzahl Ebenen neu erkennen
    profile_overrides: dict[str, Annotated[list[float], Field(max_length=20000)]] | None = Field(None, max_length=2)
    side_skipped: bool | None = None                                         # ohne Seitenfoto auswerten
    thickness_mm: float | None = Field(None, ge=0.5, le=300)                 # Dicke von Hand (ohne Seitenfoto)
    uniform_thickness: bool | None = None


class NameBody(BaseModel):
    name: str = Field("Neues Objekt", max_length=120)


@router.post("", response_model=ObjectSpec)
def create(body: NameBody, user: Principal = Depends(current_user)) -> ObjectSpec:
    return storage.create_object(body.name.strip() or "Neues Objekt", user)


@router.post("/demo", response_model=ObjectSpec)
def create_demo(user: Principal = Depends(current_user)) -> ObjectSpec:
    demo = synthetic_pliers()
    spec = storage.create_object("Spitzzange (Demo)", user, contour_mm=demo.contour_mm, length_mm=demo.length_mm,
                                 width_mm=demo.width_mm, profile=demo.profile)
    return spec


@router.get("", response_model=list[ObjectSpec])
def list_(all: bool = False, user: Principal = Depends(current_user)) -> list[ObjectSpec]:
    return storage.list_objects(user, all_=all)


@router.get("/{oid}", response_model=ObjectSpec)
def get(oid: str, user: Principal = Depends(current_user)) -> ObjectSpec:
    return _obj(oid, user)


@router.put("/{oid}", response_model=ObjectSpec)
def rename(oid: str, body: NameBody, user: Principal = Depends(current_user)) -> ObjectSpec:
    spec = _obj(oid, user)
    spec.name = body.name.strip() or spec.name
    storage.save_object(spec)
    return spec


@router.delete("/{oid}")
def delete(oid: str, user: Principal = Depends(current_user)) -> dict:
    _obj(oid, user)
    storage.delete_object(oid)
    return {"ok": True}


@router.post("/{oid}/photos/{view}")
async def upload_photo(oid: str, view: str, file: UploadFile = File(...), user: Principal = Depends(current_user)) -> dict:
    _check_view(view)
    spec = _obj(oid, user)
    ext = Path(file.filename or "x.jpg").suffix.lower() or ".jpg"
    if ext not in PHOTO_TYPES:
        raise HTTPException(415, "Bitte ein Foto als JPG, PNG oder WebP hochladen")
    data = await _read_limited(file, MAX_PHOTO_BYTES)
    try:
        bgr, f35 = scan.store_photo(spec, view, data, ext)
    except ScanError as e:
        raise _http(e) from None
    scan.detect_corners(spec, view, bgr, f35)
    storage.save_object(spec)
    return spec.photos[view]


@router.put("/{oid}/photos/{view}/corners")
def set_corners(oid: str, view: str, body: CornersBody, user: Principal = Depends(current_user)) -> dict:
    _check_view(view)
    if len(body.corners_px) != 4:
        raise HTTPException(422, "4 Ecken erwartet")
    spec = _obj(oid, user)
    try:
        bgr, f35, _ = scan.load(spec, view)
    except ScanError as e:
        raise _http(e) from None
    scan.process_corners(spec, view, bgr, f35, a4.order_corners(np.array(body.corners_px, np.float32)))
    storage.save_object(spec)
    return spec.photos[view]


@router.post("/{oid}/photos/{view}/segment")
def run_segment(oid: str, view: str, body: SegmentBody, user: Principal = Depends(current_user)) -> dict:
    _check_view(view)
    spec = _obj(oid, user)
    try:
        return scan.segment_view(spec, view, body.pos, body.neg, fill_holes=body.fill_holes, use_sam=body.use_sam,
                                 remove_hand=body.remove_hand)
    except ScanError as e:
        raise _http(e) from None


@router.put("/{oid}/photos/{view}/mask")
async def upload_mask(oid: str, view: str, file: UploadFile = File(...), fill_holes: bool = True,
                      user: Principal = Depends(current_user)) -> dict:
    _check_view(view)
    spec = _obj(oid, user)
    try:
        bgr, _, ph = scan.load(spec, view)
    except ScanError as e:
        raise _http(e) from None
    raw = await _read_limited(file, MAX_MASK_BYTES)
    try:
        from io import BytesIO

        from PIL import Image
        m = np.asarray(Image.open(BytesIO(raw)).convert("L"))     # PIL prüft die Pixelzahl (Bombenschutz)
    except Exception:  # noqa: BLE001
        raise HTTPException(422, "Maske nicht lesbar (PNG erwartet)") from None
    m = cv2.resize(m, (a4.RECT_W, a4.RECT_H), interpolation=cv2.INTER_NEAREST)
    mask = ((m > 127).astype(np.uint8)) * 255
    if fill_holes:                       # gemalte/verschobene Kontur: keine Hohlräume im Werkzeug
        mask = segment.fill_holes(mask) * 255
    rect = a4.rectify(bgr, np.asarray(ph["corners_px"], np.float32))
    return scan.save_mask(spec, view, rect, mask, fill_holes)


class LevelsBody(BaseModel):
    levels: Annotated[list[Annotated[list[float], Field(min_length=3, max_length=3)]], Field(min_length=1, max_length=8)]


@router.get("/{oid}/texture")
def texture(oid: str, user: Principal = Depends(current_user)) -> dict:
    """Farbbild der Oberseite in Werkzeug-Koordinaten (für die 3D-Ansicht); wird zwischengespeichert."""
    from ..vision.texture import make_texture
    spec = _obj(oid, user)
    d = storage.object_dir(oid)
    ph = spec.photos.get("top") or {}
    if not spec.contour_mm or not (d / "top_mask.png").exists() or not (d / "top_rect_view.jpg").exists():
        raise HTTPException(404, "Kein Foto der Draufsicht")
    out = d / "top_texture.png"
    meta_f = d / "top_texture.json"
    src = max((d / f).stat().st_mtime for f in ("object.json", "top_mask.png", "top_rect_view.jpg"))
    if not (out.exists() and meta_f.exists() and out.stat().st_mtime >= src):
        rect = cv2.imread(str(d / "top_rect_view.jpg"))
        mask = cv2.imread(str(d / "top_mask.png"), cv2.IMREAD_GRAYSCALE)
        try:
            meta = make_texture(rect, float(ph.get("view_scale", scan.VIEW_SCALE)), mask, spec.contour_mm, out)
        except ValueError as e:
            raise HTTPException(422, f"Textur nicht möglich: {e}") from e
        import json
        meta_f.write_text(json.dumps(meta), encoding="utf-8")
    import json
    meta = json.loads(meta_f.read_text(encoding="utf-8"))
    return {"url": storage.url_for(out) + f"?v={int(out.stat().st_mtime)}", **meta}


@router.put("/{oid}/levels", response_model=ObjectSpec)
def set_levels(oid: str, body: LevelsBody, user: Principal = Depends(current_user)) -> ObjectSpec:
    """Ebenen von Hand setzen, ohne die Fotos neu auszuwerten (schnell; geht auch für die Demo).
    Die Höhen gelten im aktuellen Bezug; wird eine Ebene die tiefste, wandert alles mit,
    d. h. das Werkzeug ist dort entsprechend dicker."""
    spec = _obj(oid, user)
    if spec.profile is None:
        raise HTTPException(409, "Objekt hat noch kein Profil")
    pr = spec.profile
    L = float(pr.s[-1])
    raw = profile.normalize_levels(body.levels, L, keep_ref=True)
    m = min(q[2] for q in raw)
    lv = [[a, b, round(z - m, 2)] for a, b, z in raw]
    s_arr = np.asarray(pr.s)
    pr.levels = lv
    pr.bottom = profile.bottom_from_levels(s_arr, lv).tolist()
    pr.top = (np.asarray(pr.top) - m).round(3).tolist()
    if pr.measured:
        pr.measured = (np.asarray(pr.measured) - m).round(2).tolist()
    storage.save_object(spec)
    return spec


@router.post("/{oid}/profile", response_model=ObjectSpec)
def compute_profile(oid: str, body: ProfileBody, user: Principal = Depends(current_user)) -> ObjectSpec:
    spec = _obj(oid, user)
    if body.side_flip_lr is not None or "side_flip_lr" in body.model_fields_set:
        spec.side_flip_lr = body.side_flip_lr
    if body.side_flip_ud is not None:
        spec.side_flip_ud = body.side_flip_ud
    if body.calipers is not None:
        spec.calipers = {k: v for k, v in body.calipers.items() if v}
    if body.side_skipped is not None:
        spec.side_skipped = body.side_skipped
    if body.thickness_mm is not None:
        spec.thickness_mm = body.thickness_mm
    if body.uniform_thickness is not None:
        spec.uniform_thickness = body.uniform_thickness
    try:
        return scan.compute_profile(spec, body.levels, body.level_count, body.profile_overrides)
    except ScanError as e:
        raise _http(e) from None
