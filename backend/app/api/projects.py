"""Projekte: eine Schublade als digitaler Klon (Baseplate, Einlagen, Werkzeuge, Mustervorlage).

Einstellungen: Die Mustervorlage (template) gilt für alle Einlagen des Projekts. Ändert sich die
Vorlage, übernehmen alle Einlagen die neuen Werte, außer den Feldern, die eine Einlage bewusst
überschreibt (InsertSpec.overrides). Die Liste der vererbten Felder steht in schemas.TEMPLATE_FIELDS.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .. import build_tasks, jobs, scan, storage
from ..auth import Principal, current_user
from ..geometry.baseplate import plan_info, plan_plate
from ..geometry.gridfinity import PITCH
from ..geometry.layout import compute_layout
from ..geometry.packing import Item, fits, pack
from ..schemas import BLANK_OWN_FIELDS, TEMPLATE_FIELDS, DrawerPlacement, InsertSpec, Placement, ProjectSpec
from .inserts import layout_payload, standard_height
from .objects import MAX_PHOTO_BYTES, PHOTO_TYPES, _read_limited

router = APIRouter(prefix="/projects", tags=["projects"])


def _get(pid: str, user: Principal) -> ProjectSpec:
    try:
        return storage.load_project(pid, user)
    except KeyError:
        raise HTTPException(404, "Projekt nicht gefunden") from None


def _migrate(ins: InsertSpec) -> InsertSpec:
    """Altdaten vor ffb65dc: auto_grip stand in overrides bzw. wurde neben vorhandenen Mulden eingeschaltet."""
    if "auto_grip" in ins.overrides or (ins.auto_grip and ins.grip_recesses):
        ins = ins.model_copy(update={"overrides": [f for f in ins.overrides if f != "auto_grip"],
                                     "auto_grip": ins.auto_grip and not ins.grip_recesses})
        storage.save_insert(ins)
    return ins


def project_inserts(p: ProjectSpec) -> list[InsertSpec]:
    return [_migrate(i) for i in storage._read_inserts() if i.project_id == p.id]


def apply_template(p: ProjectSpec, ins: InsertSpec) -> InsertSpec:
    """Vorlagenwerte in die Einlage übernehmen, außer den überschriebenen Feldern (Blindstopfen:
    Höhe und Stapelrand immer eigene Werte)."""
    own = set(ins.overrides) | (set(BLANK_OWN_FIELDS) if ins.blank else set())
    upd = {f: getattr(p.template, f) for f in TEMPLATE_FIELDS if f not in own}
    return ins.model_copy(update=upd, deep=True)


@router.get("", response_model=list[ProjectSpec])
def list_(all: bool = False, archived: bool = False, user: Principal = Depends(current_user)) -> list[ProjectSpec]:
    """Aktive Projekte; mit archived=true nur die archivierten."""
    return [p for p in storage.list_projects(user, all_=all) if p.archived == archived]


class NewProject(BaseModel):
    name: str = Field("Schublade", max_length=120)
    drawer_x: float = Field(500, ge=20, le=2000)
    drawer_y: float = Field(350, ge=20, le=2000)


@router.post("", response_model=ProjectSpec)
def create(body: NewProject, user: Principal = Depends(current_user)) -> ProjectSpec:
    p = ProjectSpec(name=body.name.strip() or "Schublade")
    p.drawer.drawer_x, p.drawer.drawer_y = body.drawer_x, body.drawer_y
    std = standard_height(user)
    if std:                                   # alle Einlagen gleich hoch: Standardhöhe als Vorlage
        p.template.height_mm = std[0]
    return storage.create_project(p, user)


@router.get("/{pid}", response_model=ProjectSpec)
def get(pid: str, user: Principal = Depends(current_user)) -> ProjectSpec:
    return _get(pid, user)


@router.put("/{pid}", response_model=ProjectSpec)
def put(pid: str, spec: ProjectSpec, user: Principal = Depends(current_user)) -> ProjectSpec:
    old = _get(pid, user)
    spec = spec.model_copy(update={"id": pid, "owner_id": old.owner_id, "created_at": old.created_at,
                                   "archived": old.archived, "archived_at": old.archived_at})
    storage.save_project(spec)
    if spec.template != old.template:          # Vorlage geändert: an alle Einlagen weitergeben
        for ins in project_inserts(spec):
            new = apply_template(spec, ins)
            if new != ins:
                storage.save_insert(new)
    return spec


@router.delete("/{pid}")
def delete(pid: str, user: Principal = Depends(current_user)) -> dict:
    """Löschen = archivieren: das Projekt verschwindet aus der Liste, alle Daten (Schublade, Einlagen,
    Werkzeuge) bleiben erhalten und lassen sich wiederherstellen. Endgültig löschen: storage.delete_project."""
    from datetime import datetime, timezone
    p = _get(pid, user)
    p.archived, p.archived_at = True, datetime.now(timezone.utc).isoformat()
    storage.save_project(p)
    return {"ok": True, "archived": True}


@router.post("/{pid}/restore", response_model=ProjectSpec)
def restore(pid: str, user: Principal = Depends(current_user)) -> ProjectSpec:
    p = _get(pid, user)
    p.archived, p.archived_at = False, ""
    storage.save_project(p)
    return p


class AssignBody(BaseModel):
    kind: Literal["insert", "object"]
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    member: bool = True


@router.post("/{pid}/assign")
def assign(pid: str, body: AssignBody, user: Principal = Depends(current_user)) -> dict:
    """Einlage oder Werkzeug dem Projekt zuordnen (oder herausnehmen)."""
    p = _get(pid, user)
    try:
        if body.kind == "insert":
            ins = storage.load_insert(body.id, user)
            ins = apply_template(p, ins.model_copy(update={"project_id": pid, "overrides": []})) if body.member \
                else ins.model_copy(update={"project_id": None, "overrides": []})
            storage.save_insert(ins)
            if not body.member:
                p.placements = [q for q in p.placements if q.insert_id != body.id]
                storage.save_project(p)
        else:
            o = storage.load_object(body.id, user)
            o.project_id = pid if body.member else None
            storage.save_object(o)
    except KeyError:
        raise HTTPException(404, "Nicht gefunden") from None
    return {"ok": True}


def new_insert_for(p: ProjectSpec, obj, user: Principal) -> InsertSpec:
    """Einlage für ein Werkzeug nach der Mustervorlage; Greifmulde gleich als bearbeitbare Mulde."""
    ins = apply_template(p, InsertSpec(name=obj.name, project_id=p.id, auto_grip=False,
                                       placements=[Placement(object_id=obj.id, x=0, y=0, rot_deg=0)]))
    if p.template.auto_grip and obj.profile is not None and obj.contour_mm:
        lay = compute_layout(ins.model_copy(update={"auto_grip": True}), {obj.id: obj})
        r = lambda v: round(v, 1)  # noqa: E731
        grips = [g.params.model_copy(update={"x": r(g.params.x), "y": r(g.params.y), "l": r(g.params.l)})
                 for g in lay.grips if g.auto and g.params]
        ins = ins.model_copy(update={"grip_recesses": grips})
    return storage.create_insert(ins, user)


class GenerateBody(BaseModel):
    object_ids: list[str] | None = Field(None, max_length=200)    # None = alle Werkzeuge ohne Einlage
    arrange: bool = True


@router.post("/{pid}/generate")
def generate(pid: str, body: GenerateBody, user: Principal = Depends(current_user)) -> dict:
    """Für alle Werkzeuge des Projekts ohne Einlage eine Einlage nach der Vorlage anlegen und
    (optional) alles in der Schublade anordnen."""
    p = _get(pid, user)
    have = {pl.object_id for ins in project_inserts(p) for pl in ins.placements}
    objs = [o for o in storage.list_objects(user) if o.project_id == pid]
    if body.object_ids is not None:
        want = set(body.object_ids)
        objs = [o for o in storage.list_objects(user) if o.id in want]
    created, skipped = [], []
    already = []
    for o in objs:
        if o.id in have:                      # hat schon eine Einlage im Projekt
            already.append(o.name)
            continue
        if o.profile is None or not o.contour_mm:
            skipped.append(o.name)
            continue
        if o.project_id != pid:
            o.project_id = pid
            storage.save_object(o)
        created.append(new_insert_for(p, o, user).id)
    res = {"created": created, "skipped": skipped, "already": already}
    if body.arrange:
        res.update(arrange(pid, ArrangeBody(mode="missing"), user))
    return res


def _check_ready(ins: InsertSpec, objs: dict) -> None:
    """Einlage lässt sich berechnen: Werkzeuge fertig gescannt; ohne Werkzeug nur als
    Fächer-Einlage (mit Fächern) oder Blindstopfen."""
    if not ins.placements and not ins.compartments and not ins.blank:
        raise ValueError("Einlage ist leer (kein Werkzeug, keine Fächer)")
    if any(o.profile is None or not o.contour_mm for o in objs.values()):
        raise ValueError("Werkzeug noch nicht fertig gescannt")


def _footprint(ins: InsertSpec, user: Principal) -> tuple[int, int, float, dict]:
    objs = storage.objects_for(ins, user)
    _check_ready(ins, objs)
    lay = compute_layout(ins, objs)
    return lay.grid_x, lay.grid_y, lay.total_height, objs


class ArrangeBody(BaseModel):
    mode: Literal["all", "missing"] = "missing"      # all: alles neu anordnen; missing: nur, was noch fehlt


@router.post("/{pid}/arrange")
def arrange(pid: str, body: ArrangeBody, user: Principal = Depends(current_user)) -> dict:
    p = _get(pid, user)
    plan = plan_plate(p.drawer)
    free = set(plan.active)
    ids = {i.id: i for i in project_inserts(p)}
    keep = [q for q in p.placements if q.insert_id in ids] if body.mode == "missing" else []
    sizes: dict[str, tuple[int, int]] = {}
    broken: list[str] = []
    for iid, ins in ids.items():
        try:
            gx, gy, _, _ = _footprint(ins, user)
        except (KeyError, ValueError, IndexError):
            broken.append(iid)                # Werkzeug fehlt oder ist unfertig: kann nicht hinein
            continue
        sizes[iid] = (gx, gy)
    for q in keep:
        if q.insert_id in sizes:
            w, h = sizes[q.insert_id] if q.rot == 0 else sizes[q.insert_id][::-1]
            free -= {(i, j) for i in range(q.ix, q.ix + w) for j in range(q.iy, q.iy + h)}
    kept = {q.insert_id for q in keep}
    items = [Item(iid, *sizes[iid]) for iid in sizes if iid not in kept]
    placed, left = pack(plan.nx, plan.ny, free, items)
    keep = [q for q in keep if q.insert_id not in broken]
    p.placements = keep + [DrawerPlacement(insert_id=k, ix=v[0], iy=v[1], rot=v[2]) for k, v in placed.items()]
    storage.save_project(p)
    return {"placed": list(placed), "left_out": left, "left_out_names": [ids[i].name for i in left],
            "unfinished": broken, "unfinished_names": [ids[i].name for i in broken]}


def _tool_payload(ins: InsertSpec, lay, objs: dict) -> list[dict]:
    """Werkzeuge der Einlage für die 3D-Ansicht: Kontur, Ober-/Unterseite, Lage in der Einlage."""
    out = []
    sx, sy = lay.shift
    for k, pl in enumerate(ins.placements):
        o = objs.get(pl.object_id)
        if o is None or o.profile is None:
            continue
        T = max(o.profile.top)
        sink = lay.sink[k] if k < len(lay.sink) else ins.sink
        z_rest = lay.z_surface - sink * T + ins.overhang
        step = max(1, len(o.profile.s) // 160)            # Low-Poly: höchstens ca. 160 Stützstellen
        out.append({
            "object_id": o.id, "name": o.name, "contour": o.contour_mm,
            "s": o.profile.s[::step], "bottom": o.profile.bottom[::step], "top": o.profile.top[::step],
            "z_rest": z_rest, "x": pl.x + sx, "y": pl.y + sy, "rot_deg": pl.rot_deg,
            "has_texture": "top" in o.photos and bool(o.photos["top"].get("mask_url")),
        })
    return out


@router.get("/{pid}/clone")
def clone(pid: str, user: Principal = Depends(current_user)) -> dict:
    """Alles für die Schubladen-Ansicht: Baseplate-Plan, Einlagen (Layout, Lage, Farben), Werkzeuge."""
    p = _get(pid, user)
    try:
        plan = plan_plate(p.drawer)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    pos = {q.insert_id: q for q in p.placements}
    inserts, warnings, heights, tops = [], [], [], []
    occupied: dict[tuple[int, int], tuple[str, str]] = {}
    conflicts: dict[tuple[int, int], dict] = {}          # Zellen mit Überlappung oder außerhalb (zum Markieren)
    for ins in project_inserts(p):
        item = {"id": ins.id, "name": ins.name, "colors": ins.color_hex.model_dump(), "overrides": ins.overrides,
                "blank": ins.blank,
                "placed": pos[ins.id].model_dump() if ins.id in pos else None, "error": None}
        try:
            objs = storage.objects_for(ins, user)
            _check_ready(ins, objs)
            lay = compute_layout(ins, objs)
            from shapely.ops import unary_union

            from .inserts import _polys
            cut = unary_union([q.poly for q in lay.pieces] + [g.poly for g in lay.grips] + [c.poly for c in lay.comps])
            item.update(gx=lay.grid_x, gy=lay.grid_y, total_height=lay.total_height,
                        layout=layout_payload(ins, user), tools=_tool_payload(ins, lay, objs),
                        cut_union=_polys(cut.simplify(0.05)))
            if ins.id in pos:
                tops.append(lay.text_top)          # inkl. erhabener Schrift (Schubladenhöhe)
                if not ins.blank:                   # Blindstopfen sind absichtlich flacher
                    heights.append((lay.total_height, ins.name))
                q = pos[ins.id]
                w, h = (lay.grid_x, lay.grid_y) if q.rot == 0 else (lay.grid_y, lay.grid_x)
                for c in [(i, j) for i in range(q.ix, q.ix + w) for j in range(q.iy, q.iy + h)]:
                    if c not in plan.active:          # Rand, abgewählte Zelle oder außerhalb der Schublade
                        k = conflicts.setdefault(c, {"cell": list(c), "kind": "outside", "inserts": [], "ids": []})
                        k["inserts"].append(ins.name)
                        k["ids"].append(ins.id)
                        if f"{ins.name} liegt" not in " ".join(warnings):
                            warnings.append(f"{ins.name} liegt teilweise außerhalb der Baseplate oder auf einer abgewählten Zelle (rot markiert).")
                    if c in occupied:
                        oid, oname = occupied[c]
                        k = conflicts.setdefault(c, {"cell": list(c), "kind": "overlap", "inserts": [], "ids": []})
                        k["kind"] = "overlap"
                        for i_, n_ in ((oid, oname), (ins.id, ins.name)):
                            if i_ not in k["ids"]:
                                k["ids"].append(i_)
                                k["inserts"].append(n_)
                        warnings.append(f"{ins.name} überlappt {oname} (rot markiert).")
                    occupied.setdefault(c, (ins.id, ins.name))
        except (KeyError, ValueError, IndexError) as e:
            item["error"] = str(e) if not isinstance(e, KeyError) else "Werkzeug fehlt"
        inserts.append(item)
    if heights:
        hs = [h for h, _ in heights]
        if max(hs) - min(hs) > 0.05:
            low = min(heights)[1]
            high = max(heights)[1]
            warnings.append(f"Einlagen unterschiedlich hoch: {min(hs):.1f} mm ({low}) bis {max(hs):.1f} mm ({high}).")
    if tops and p.drawer_h and max(tops) > p.drawer_h:
        warnings.append(f"Höchste Einlage ({max(tops):.1f} mm) ist höher als die Schublade ({p.drawer_h:.0f} mm).")
    return {"plan": plan_info(p.drawer, plan), "pitch": PITCH, "inserts": inserts,
            "warnings": list(dict.fromkeys(warnings)), "conflicts": list(conflicts.values()),
            "heights_equal": bool(heights) and max(h for h, _ in heights) - min(h for h, _ in heights) <= 0.05}


class PlaceBody(BaseModel):
    placement: DrawerPlacement | None = None     # None = aus der Schublade nehmen
    insert_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    force: bool = False                          # trotzdem setzen; Überlappung zeigt der Klon rot an


@router.post("/{pid}/place")
def place(pid: str, body: PlaceBody, user: Principal = Depends(current_user)) -> dict:
    """Eine Einlage von Hand setzen/verschieben/drehen oder herausnehmen. Prüft Platz; mit force wird
    trotzdem gesetzt (z. B. Drehen an engem Platz) und der Klon markiert die Überlappung."""
    p = _get(pid, user)
    others = [q for q in p.placements if q.insert_id != body.insert_id]
    ok = True
    if body.placement is not None:
        try:
            ins = storage.load_insert(body.insert_id, user)
        except KeyError:
            raise HTTPException(404, "Einlage nicht gefunden") from None
        if ins.project_id != pid:
            raise HTTPException(422, "Einlage gehört nicht zu diesem Projekt")
        try:
            plan = plan_plate(p.drawer)
            gx, gy, _, _ = _footprint(ins, user)
        except (KeyError, ValueError, IndexError) as e:
            raise HTTPException(422, f"{ins.name} lässt sich nicht einsetzen: Werkzeug fehlt oder ist noch nicht fertig gescannt ({e}).") from e
        free = set(plan.active)
        ids = {i.id: i for i in project_inserts(p)}
        for q in others:
            if q.insert_id in ids:
                try:
                    qx, qy, _, _ = _footprint(ids[q.insert_id], user)
                except (KeyError, ValueError, IndexError):
                    continue
                w, h = (qx, qy) if q.rot == 0 else (qy, qx)
                free -= {(i, j) for i in range(q.ix, q.ix + w) for j in range(q.iy, q.iy + h)}
        w, h = (gx, gy) if body.placement.rot == 0 else (gy, gx)
        ok = fits(free, body.placement.ix, body.placement.iy, w, h)
        if not ok and not body.force:
            raise HTTPException(409, "Dort ist kein Platz (Rand, abgewählte Zelle oder andere Einlage).")
        others.append(body.placement.model_copy(update={"insert_id": body.insert_id}))
    p.placements = others
    storage.save_project(p)
    return {"ok": True, "fits": body.placement is None or ok, "placements": [q.model_dump() for q in p.placements]}


# ---- Stapel-Scan: viele Werkzeuge auf einmal (je Paar Draufsicht + Seitenansicht) ----------------
MAX_BATCH = 60


@router.post("/{pid}/scan-pair")
async def scan_pair(pid: str, top: UploadFile = File(...), side: UploadFile = File(...),
                    name: str = Form("", max_length=120), user: Principal = Depends(current_user)) -> dict:
    """Ein Fotopaar ablegen: legt das Werkzeug im Projekt an, ausgewertet wird später im Stapel-Scan."""
    _get(pid, user)
    files = {}
    for view, f in (("top", top), ("side", side)):
        ext = Path(f.filename or "x.jpg").suffix.lower() or ".jpg"
        if ext not in PHOTO_TYPES:
            raise HTTPException(415, "Bitte Fotos als JPG, PNG oder WebP hochladen")
        files[view] = (await _read_limited(f, MAX_PHOTO_BYTES), ext)
    n = sum(1 for o in storage.list_objects(user) if o.project_id == pid)
    obj = storage.create_object(name.strip() or f"Werkzeug {n + 1}", user)
    obj.project_id = pid
    try:
        for view, (data, ext) in files.items():
            scan.store_photo(obj, view, data, ext)
    except scan.ScanError as e:
        storage.delete_object(obj.id)
        raise HTTPException(e.status, f"{scan.VIEW_NAMES[view]}: {e}") from None
    storage.save_object(obj)
    return {"id": obj.id, "name": obj.name}


class BatchBody(BaseModel):
    object_ids: list[str] = Field(min_length=1, max_length=MAX_BATCH)


@router.post("/{pid}/batch-scan")
def batch_scan(pid: str, body: BatchBody, user: Principal = Depends(current_user)) -> dict:
    """Hintergrund-Job: alle Paare auswerten, dann Einlagen nach der Vorlage erzeugen und anordnen."""
    _get(pid, user)
    for oid in body.object_ids:
        try:
            o = storage.load_object(oid, user)
        except KeyError:
            raise HTTPException(404, "Werkzeug nicht gefunden") from None
        if o.project_id != pid:
            raise HTTPException(422, f"{o.name} gehört nicht zu diesem Projekt")
        if not ("top" in o.photos and "side" in o.photos):
            raise HTTPException(409, f"{o.name}: Draufsicht oder Seitenansicht fehlt")
    job_id = jobs.submit("scan", build_tasks.batch_scan_job, storage.project_dir(pid) / "scans", pid,
                         list(dict.fromkeys(body.object_ids)), user, owner=user)
    return {"job_id": job_id}
