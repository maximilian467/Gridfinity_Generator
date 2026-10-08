from __future__ import annotations

from fastapi import APIRouter, HTTPException
from shapely.geometry import MultiPolygon, Polygon

from .. import build_tasks, jobs, storage
from ..geometry.layout import compute_layout
from ..schemas import InsertSpec

router = APIRouter(prefix="/inserts", tags=["inserts"])


def _polys(g) -> list[dict]:
    if g.is_empty:
        return []
    geoms = [g] if isinstance(g, Polygon) else list(g.geoms) if isinstance(g, MultiPolygon) else []
    return [{"exterior": [list(c) for c in p.exterior.coords],
             "holes": [[list(c) for c in h.coords] for h in p.interiors]} for p in geoms]


def layout_payload(spec: InsertSpec) -> dict:
    try:
        objects = storage.objects_for(spec)
    except KeyError as e:
        raise HTTPException(404, f"Objekt {e} nicht gefunden") from e
    for o in objects.values():
        if o.profile is None or not o.contour_mm:
            raise HTTPException(422, f"Objekt {o.name} hat noch keine Kontur/Profil")
    lay = compute_layout(spec, objects)
    ox, oy = lay.outer
    return {
        "grid_x": lay.grid_x, "grid_y": lay.grid_y, "height_u": lay.height_u, "z_surface": lay.z_surface,
        "outer": [ox, oy],
        "pieces": [{"placement": p.placement, "zone": p.zone, "z0": p.z0, "depth": lay.z_surface - p.z0,
                    "polygons": _polys(p.poly)} for p in lay.pieces],
        "grips": [{"z0": z, "depth": lay.z_surface - z, "polygons": _polys(g)} for g, z in lay.grips],
        "compartments": [{"z0": z, "depth": lay.z_surface - z, "polygons": _polys(g)} for g, z, _ in lay.comps],
        "zones": [[{"a": z.a, "b": z.b, "floor": z.floor} for z in zs] for zs in lay.zones],
        "warnings": lay.warnings,
    }


@router.post("", response_model=InsertSpec)
def create(spec: InsertSpec) -> InsertSpec:
    return storage.create_insert(spec)


@router.get("", response_model=list[InsertSpec])
def list_() -> list[InsertSpec]:
    return storage.list_inserts()


@router.get("/{iid}", response_model=InsertSpec)
def get(iid: str) -> InsertSpec:
    try:
        return storage.load_insert(iid)
    except KeyError:
        raise HTTPException(404, "Einlage nicht gefunden") from None


@router.put("/{iid}", response_model=InsertSpec)
def put(iid: str, spec: InsertSpec) -> InsertSpec:
    spec = spec.model_copy(update={"id": iid})
    storage.save_insert(spec)
    return spec


@router.delete("/{iid}")
def delete(iid: str) -> dict:
    storage.delete_insert(iid)
    return {"ok": True}


@router.post("/{iid}/duplicate", response_model=InsertSpec)
def duplicate(iid: str) -> InsertSpec:
    spec = get(iid)
    return storage.create_insert(spec.model_copy(update={"name": spec.name + " (Kopie)"}, deep=True))


@router.post("/{iid}/layout")
def layout(iid: str, spec: InsertSpec | None = None) -> dict:
    """Schnelles 2D-Layout; optional mit ungespeicherter Spec im Body (Live-Vorschau)."""
    return layout_payload(spec.model_copy(update={"id": iid}) if spec else get(iid))


@router.post("/{iid}/build")
def build(iid: str, spec: InsertSpec | None = None) -> dict:
    spec = spec.model_copy(update={"id": iid}) if spec else get(iid)
    layout_payload(spec)                         # validiert Objekte
    objects = {k: v.model_dump_json() for k, v in storage.objects_for(spec).items()}
    job_id = jobs.submit("insert", build_tasks.build_insert_job, storage.insert_dir(iid) / "out",
                         spec.model_dump_json(), objects)
    return {"job_id": job_id}
