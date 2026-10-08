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
        "grips": [{"z0": g.z0, "depth": lay.z_surface - g.z0, "polygons": _polys(g.poly), "auto": g.auto,
                   "placement": g.placement, "rounded": g.rounded,
                   "params": g.params.model_dump() if g.params else None} for g in lay.grips],
        "compartments": [{"z0": c.z0, "depth": lay.z_surface - c.z0, "polygons": _polys(c.poly), "auto": c.auto}
                         for c in lay.comps],
        "shift": list(lay.shift),
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


@router.post("/{iid}/auto-compartments")
def auto_compartments(iid: str, spec: InsertSpec | None = None) -> dict:
    """Vorschläge für Kästen in den freien Flächen (frei geformt, Wand folgt der Kontur)."""
    from ..geometry.gridfinity import FOOT_H
    from ..geometry.layout import auto_compartments
    from ..schemas import Compartment

    spec = spec.model_copy(update={"id": iid}) if spec else get(iid)
    layout_payload(spec)
    keep = [c for c in spec.compartments if not c.generated]
    lay = compute_layout(spec.model_copy(update={"auto_compartments": False, "compartments": keep}), storage.objects_for(spec))
    sx, sy = lay.shift
    depth = spec.comp_depth or (lay.z_surface - FOOT_H - spec.floor_min)
    out = []
    for poly in auto_compartments(lay, spec):
        # in Spec-Koordinaten (vor Zentrierung) zurückgeben, damit sie mit dem Inhalt mitwandern
        from shapely import affinity
        p = affinity.translate(poly, -sx, -sy)
        x0, y0, x1, y1 = p.bounds
        out.append(Compartment(x=x0, y=y0, w=x1 - x0, l=y1 - y0, depth=round(depth, 1), generated=True,
                               polygon=[list(map(lambda v: round(v, 2), c)) for c in p.exterior.coords]))
    return {"compartments": [c.model_dump() for c in out]}


@router.post("/{iid}/build")
def build(iid: str, spec: InsertSpec | None = None) -> dict:
    spec = spec.model_copy(update={"id": iid}) if spec else get(iid)
    layout_payload(spec)                         # validiert Objekte
    objects = {k: v.model_dump_json() for k, v in storage.objects_for(spec).items()}
    job_id = jobs.submit("insert", build_tasks.build_insert_job, storage.insert_dir(iid) / "out",
                         spec.model_dump_json(), objects)
    return {"job_id": job_id}
