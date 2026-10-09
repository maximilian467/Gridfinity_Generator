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
        "total_height": lay.total_height, "sink": lay.sink,
        "outer": [ox, oy],
        "pieces": [{"placement": p.placement, "zone": p.zone, "z0": p.z0, "depth": lay.z_surface - p.z0,
                    "polygons": _polys(p.poly)} for p in lay.pieces],
        "grips": [{"z0": g.z0, "depth": lay.z_surface - g.z0, "polygons": _polys(g.poly), "auto": g.auto,
                   "placement": g.placement, "rounded": g.rounded,
                   "params": g.params.model_dump() if g.params else None} for g in lay.grips],
        "compartments": [{"z0": c.z0, "depth": lay.z_surface - c.z0, "polygons": _polys(c.poly), "auto": c.auto,
                          "max_depth": c.free_depth} for c in lay.comps],
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
    from ..geometry.layout import auto_compartments
    from ..schemas import Compartment

    spec = spec.model_copy(update={"id": iid}) if spec else get(iid)
    layout_payload(spec)
    keep = [c for c in spec.compartments if not c.generated]
    lay = compute_layout(spec.model_copy(update={"auto_compartments": False, "compartments": keep}), storage.objects_for(spec))
    sx, sy = lay.shift
    depth = round(spec.comp_depth, 1) if spec.comp_depth else None
    out = []
    for poly in auto_compartments(lay, spec):
        # in Spec-Koordinaten (vor Zentrierung) zurückgeben, damit sie mit dem Inhalt mitwandern
        from shapely import affinity
        p = affinity.translate(poly, -sx, -sy)
        x0, y0, x1, y1 = p.bounds
        out.append(Compartment(x=x0, y=y0, w=x1 - x0, l=y1 - y0, depth=depth, generated=True,
                               polygon=[list(map(lambda v: round(v, 2), c)) for c in p.exterior.coords]))
    reason = None
    if not out:
        reason = (f"Kein freier Platz für einen Kasten von mindestens {spec.comp_min_size:.0f} x {spec.comp_min_size:.0f} mm. "
                  "Die Einlage ist zu knapp: Raster vergrößern oder die Mindestgröße senken.")
    return {"compartments": [c.model_dump() for c in out], "reason": reason,
            "grid": [lay.grid_x, lay.grid_y]}


class CompEdit(BaseModel):
    spec: InsertSpec
    op: Literal["merge", "split", "cut"]
    indices: list[int] = Field(min_length=1, max_length=60)
    parts: int = Field(2, ge=2, le=4)
    axis: Literal["h", "v"] = "h"               # cut: h = waagrechter Schnitt (entlang x), v = senkrecht
    at: float = Field(0.0, ge=-2000, le=2000)    # cut: Lage des Schnitts (Spec-Koordinaten)


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
    if body.op == "cut" and idx:
        p = comp_polygon(spec.compartments[idx[0]])
        x0, y0, x1, y1 = p.bounds
        h = max(spec.comp_wall, 0.8) / 2
        band = (box(x0 - 1, body.at - h, x1 + 1, body.at + h) if body.axis == "h"
                else box(body.at - h, y0 - 1, body.at + h, y1 + 1))
        rest = p.difference(band)
        pieces = [g for g in getattr(rest, "geoms", [rest]) if g.geom_type == "Polygon" and g.area > 20]
        if len(pieces) < 2:
            raise HTTPException(422, "Der Schnitt muss durch den Kasten gehen")
        if any(min(g.bounds[2] - g.bounds[0], g.bounds[3] - g.bounds[1]) < 6 for g in pieces):
            raise HTTPException(422, "Ein Fach würde schmaler als 6 mm")
        c0 = spec.compartments[idx[0]]

        def piece(g):
            g = g.buffer(-1.0, join_style=1).buffer(1.0, join_style=1).simplify(0.1)
            bx0, by0, bx1, by1 = g.bounds
            return Compartment(x=bx0, y=by0, w=bx1 - bx0, l=by1 - by0, depth=c0.depth, generated=True,
                               polygon=[[round(a, 2), round(b, 2)] for a, b in g.exterior.coords])
        keep = [c for i, c in enumerate(spec.compartments) if i != idx[0]]
        return {"compartments": [c.model_dump() for c in keep] + [piece(g).model_dump() for g in pieces]}
    if not idx or (body.op == "merge" and len(idx) < 2):
        raise HTTPException(422, "Zum Verbinden mindestens zwei Kästen auswählen")
    polys = [comp_polygon(spec.compartments[i]) for i in idx]
    free, wall = _free_area(spec, set(idx))
    ds = [spec.compartments[i].depth for i in idx if spec.compartments[i].depth is not None]
    depth = min(ds) if ds else None

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


class CompAt(BaseModel):
    spec: InsertSpec
    x: float = Field(ge=-2000, le=2000)      # Klickpunkt im Layout (nach Zentrierung)
    y: float = Field(ge=-2000, le=2000)


@router.post("/{iid}/compartments/at")
def compartment_at(iid: str, body: CompAt) -> dict:
    """Einzelnen Kasten anlegen: füllt die freie Fläche um den Klickpunkt (Wand folgt der
    Kontur, Abstand = Wandstärke). Danach teilbar/verbindbar wie die erzeugten Kästen."""
    from shapely import affinity
    from shapely.geometry import Point

    from ..geometry.layout import auto_compartments
    from ..schemas import Compartment

    spec = body.spec.model_copy(update={"id": iid})
    layout_payload(spec)
    lay = compute_layout(spec.model_copy(update={"auto_compartments": False}), storage.objects_for(spec))
    pt = Point(body.x, body.y)
    # dieselben Vorgaben wie 'Kästen erzeugen' (größte freie Rechtecke, an die Kontur gewachsen),
    # davon der Kasten unter dem Klickpunkt
    probe = spec.model_copy(update={"comp_min_size": min(spec.comp_min_size, 10.0)})
    cands = auto_compartments(lay, probe, max_n=30)
    region = next((g for g in cands if g.buffer(0.5).contains(pt)), None)
    if region is None:
        raise HTTPException(422, "Dort ist kein freier Platz für einen Kasten (Tasche, Mulde oder Kasten zu nah)")
    region = affinity.translate(region, -lay.shift[0], -lay.shift[1])
    region = region.simplify(0.1)
    x0, y0, x1, y1 = region.bounds
    c = Compartment(x=x0, y=y0, w=x1 - x0, l=y1 - y0, generated=True,
                    depth=round(spec.comp_depth, 1) if spec.comp_depth else None,
                    polygon=[[round(a, 2), round(b, 2)] for a, b in region.exterior.coords])
    return {"compartments": [c.model_dump() for c in spec.compartments] + [c.model_dump()]}


class CompRect(BaseModel):
    spec: InsertSpec
    x0: float = Field(ge=-2000, le=2000)        # aufgezogenes Rechteck im Layout (nach Zentrierung)
    y0: float = Field(ge=-2000, le=2000)
    x1: float = Field(ge=-2000, le=2000)
    y1: float = Field(ge=-2000, le=2000)


@router.post("/{iid}/compartments/rect")
def compartment_rect(iid: str, body: CompRect) -> dict:
    """Kasten aus einem aufgezogenen Rechteck: gerade Kanten, wo gezeichnet wurde; wo das
    Rechteck in Werkzeug, Mulde, Rand oder andere Kästen ragt, folgt die Wand deren Kontur."""
    from shapely import affinity
    from shapely.geometry import box

    from ..geometry.layout import _polys
    from ..schemas import Compartment

    spec = body.spec.model_copy(update={"id": iid})
    layout_payload(spec)
    free, _ = _free_area(spec, set())                      # Spec-Koordinaten
    lay = compute_layout(spec, storage.objects_for(spec))
    r = affinity.translate(box(min(body.x0, body.x1), min(body.y0, body.y1), max(body.x0, body.x1),
                               max(body.y0, body.y1)), -lay.shift[0], -lay.shift[1])
    region = r.intersection(free)
    parts = [g for g in _polys(region) if g.area > 30]
    if not parts:
        raise HTTPException(422, "In diesem Rechteck ist kein freier Platz")
    g = max(parts, key=lambda q: q.area)
    g = g.buffer(-1.5, join_style=1).buffer(1.5, join_style=1)    # Ecken leicht runden, Splitter weg
    gs = _polys(g)
    if not gs:
        raise HTTPException(422, "Das Rechteck ist zu schmal für einen Kasten")
    g = max(gs, key=lambda q: q.area).simplify(0.1)
    if min(g.bounds[2] - g.bounds[0], g.bounds[3] - g.bounds[1]) < 6:
        raise HTTPException(422, "Der Kasten wäre schmaler als 6 mm")
    x0, y0, x1, y1 = g.bounds
    c = Compartment(x=x0, y=y0, w=x1 - x0, l=y1 - y0, generated=True,
                    depth=round(spec.comp_depth, 1) if spec.comp_depth else None,
                    polygon=[[round(a, 2), round(b, 2)] for a, b in g.exterior.coords])
    return {"compartments": [q.model_dump() for q in spec.compartments] + [c.model_dump()]}


@router.post("/{iid}/build")
def build(iid: str, spec: InsertSpec | None = None) -> dict:
    spec = spec.model_copy(update={"id": iid}) if spec else get(iid)
    layout_payload(spec)                         # validiert Objekte
    objects = {k: v.model_dump_json() for k, v in storage.objects_for(spec).items()}
    job_id = jobs.submit("insert", build_tasks.build_insert_job, storage.insert_dir(iid) / "out",
                         spec.model_dump_json(), objects)
    return {"job_id": job_id}
