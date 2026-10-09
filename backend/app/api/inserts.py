from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
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
    reason = None
    if not out:
        reason = (f"Kein freier Platz für einen Kasten von mindestens {spec.comp_min_size:.0f} x {spec.comp_min_size:.0f} mm. "
                  "Die Einlage ist zu knapp: Raster vergrößern oder die Mindestgröße senken.")
    return {"compartments": [c.model_dump() for c in out], "reason": reason,
            "grid": [lay.grid_x, lay.grid_y]}


class CompEdit(BaseModel):
    spec: InsertSpec
    op: Literal["merge", "split"]
    indices: list[int] = Field(min_length=1, max_length=60)
    parts: int = Field(2, ge=2, le=4)


def _free_area(spec: InsertSpec, keep_idx: set[int]):
    """Innenbereich minus Taschen/Mulden/übrige Fächer (+ Wand): dort dürfen Kästen liegen."""
    from shapely import affinity
    from shapely.ops import unary_union
    others = [c for i, c in enumerate(spec.compartments) if i not in keep_idx]
    lay = compute_layout(spec.model_copy(update={"compartments": others}), storage.objects_for(spec))
    occ = [p.poly for p in lay.pieces] + [g.poly for g in lay.grips] + [c.poly for c in lay.comps]
    wall = max(spec.comp_wall, 0.8) + 0.15
    free = lay.inner.buffer(-0.01)
    if occ:
        free = free.difference(unary_union(occ).buffer(wall, join_style=1))
    # zurück in Spec-Koordinaten (vor der Zentrierung)
    return affinity.translate(free, -lay.shift[0], -lay.shift[1]), wall


@router.post("/{iid}/compartments/edit")
def edit_compartments(iid: str, body: CompEdit) -> dict:
    """Kästen verbinden (inkl. der Wand dazwischen) oder in gleich große Fächer teilen."""
    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union
    from ..geometry.layout import comp_polygon
    from ..schemas import Compartment

    spec = body.spec.model_copy(update={"id": iid})
    idx = sorted({i for i in body.indices if 0 <= i < len(spec.compartments)})
    if not idx or (body.op == "merge" and len(idx) < 2):
        raise HTTPException(422, "Zum Verbinden mindestens zwei Kästen auswählen")
    polys = [comp_polygon(spec.compartments[i]) for i in idx]
    free, wall = _free_area(spec, set(idx))
    depth = min(spec.compartments[i].depth for i in idx)

    def as_comp(p: Polygon) -> Compartment:
        p = p.buffer(-2.0, join_style=1).buffer(2.0, join_style=1).simplify(0.1)
        x0, y0, x1, y1 = p.bounds
        return Compartment(x=x0, y=y0, w=x1 - x0, l=y1 - y0, depth=depth, generated=True,
                           polygon=[[round(a, 2), round(b, 2)] for a, b in p.exterior.coords])

    new: list[Compartment] = []
    if body.op == "merge":
        bridge = wall / 2 + 0.6                     # Wand zwischen den Kästen mit auffüllen
        merged = unary_union([p.buffer(bridge, join_style=2) for p in polys]).buffer(-bridge, join_style=2)
        merged = merged.intersection(free)
        parts = [g for g in getattr(merged, "geoms", [merged]) if g.geom_type == "Polygon" and g.area > 50]
        if len(parts) != 1:
            raise HTTPException(422, "Diese Kästen liegen nicht nebeneinander und lassen sich nicht verbinden")
        new = [as_comp(parts[0])]
    else:
        for p in polys:
            x0, y0, x1, y1 = p.bounds
            horiz = (x1 - x0) >= (y1 - y0)              # entlang der längeren Seite teilen
            n = body.parts
            cuts = []
            for k in range(1, n):
                t = k / n
                if horiz:
                    xc = x0 + t * (x1 - x0)
                    cuts.append(box(xc - wall / 2, y0 - 1, xc + wall / 2, y1 + 1))
                else:
                    yc = y0 + t * (y1 - y0)
                    cuts.append(box(x0 - 1, yc - wall / 2, x1 + 1, yc + wall / 2))
            rest = p.difference(unary_union(cuts))
            pieces = [g for g in getattr(rest, "geoms", [rest]) if g.geom_type == "Polygon" and g.area > 50]
            if any(min(g.bounds[2] - g.bounds[0], g.bounds[3] - g.bounds[1]) < 8 for g in pieces):
                raise HTTPException(422, "Die Fächer würden schmaler als 8 mm, Teilen nicht möglich")
            new += [as_comp(g) for g in pieces]
    keep = [c for i, c in enumerate(spec.compartments) if i not in idx]
    return {"compartments": [c.model_dump() for c in keep + new]}


@router.post("/{iid}/build")
def build(iid: str, spec: InsertSpec | None = None) -> dict:
    spec = spec.model_copy(update={"id": iid}) if spec else get(iid)
    layout_payload(spec)                         # validiert Objekte
    objects = {k: v.model_dump_json() for k, v in storage.objects_for(spec).items()}
    job_id = jobs.submit("insert", build_tasks.build_insert_job, storage.insert_dir(iid) / "out",
                         spec.model_dump_json(), objects)
    return {"job_id": job_id}
