"""Fächer-Einlage (Sortierkasten ohne Werkzeug): Raster in gleich große Fächer geteilt."""
import cadquery as cq
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Polygon

from app.geometry.gridfinity import FOOT_H, LIP_MARGIN
from app.geometry.insert_cad import build_insert
from app.geometry.layout import comp_polygon, compute_layout, grid_compartments
from app.geometry.samples import synthetic_pliers
from app.main import app
from app.schemas import Compartment, InsertSpec, Placement

client = TestClient(app)


def _bin_spec(cols: int, rows: int, **kw) -> InsertSpec:
    spec = InsertSpec(grid_x=kw.pop("gx", 2), grid_y=kw.pop("gy", 2), auto_grip=False, auto_center=False, **kw)
    lay = compute_layout(spec, {})
    comps = [Compartment(x=p.bounds[0], y=p.bounds[1], w=p.bounds[2] - p.bounds[0], l=p.bounds[3] - p.bounds[1],
                         depth=None, generated=True, polygon=[list(c) for c in p.exterior.coords])
             for p in grid_compartments(lay, spec, cols, rows)]
    return spec.model_copy(update={"compartments": comps})


def test_grid_divides_inner_area_evenly():
    spec = _bin_spec(3, 2, gx=3, gy=2)
    lay = compute_layout(spec, {})
    polys = [c.poly for c in lay.comps]
    assert len(polys) == 6
    areas = [p.area for p in polys]
    assert max(areas) - min(areas) < 0.5                            # alle gleich groß
    ix0, iy0, ix1, iy1 = lay.inner.bounds
    x0 = min(p.bounds[0] for p in polys)
    x1 = max(p.bounds[2] for p in polys)
    y0 = min(p.bounds[1] for p in polys)
    y1 = max(p.bounds[3] for p in polys)
    assert (x0, y0) == pytest.approx((ix0, iy0), abs=0.05) and (x1, y1) == pytest.approx((ix1, iy1), abs=0.05)
    for i in range(6):
        for j in range(i + 1, 6):
            d = polys[i].distance(polys[j])
            assert d >= spec.comp_wall - 0.05                          # Wand zwischen den Fächern
    assert all(c.free_depth and c.z0 == pytest.approx(FOOT_H + spec.floor_min) for c in lay.comps)
    assert lay.shift == (0.0, 0.0) and not lay.warnings


def test_too_many_compartments_rejected():
    spec = InsertSpec(grid_x=1, grid_y=1, auto_grip=False)
    with pytest.raises(ValueError, match="schmaler"):
        grid_compartments(compute_layout(spec, {}), spec, 12, 1)


def test_bin_cad_one_watertight_body_with_open_compartments():
    spec = _bin_spec(2, 3, height_mm=32.0)
    r = build_insert(spec, {})
    assert r.checks.valid and r.checks.solid_count == 1 and r.checks.watertight
    assert r.volume_sum_ok and all(r.part_checks.values())
    bb = r.body.val().BoundingBox()
    assert (bb.xlen, bb.ylen) == pytest.approx((2 * 42 - 0.5, 2 * 42 - 0.5), abs=0.3)
    assert bb.zmin == pytest.approx(0, abs=0.05) and bb.zmax == pytest.approx(32.0, abs=0.1)
    solid = r.body.val()
    zs = r.layout.z_surface
    for c in r.layout.comps:
        pt = c.poly.representative_point()
        assert not solid.isInside(cq.Vector(pt.x, pt.y, c.z0 + 0.3))     # Fach offen bis zum Boden
        assert not solid.isInside(cq.Vector(pt.x, pt.y, zs - 1.0))
        assert solid.isInside(cq.Vector(pt.x, pt.y, c.z0 - 0.3))         # Boden darunter
    # Trennwand in der Mitte (2 Spalten) steht bis zur Oberfläche
    ox = (2 * 42 - 0.5) / 2
    assert solid.isInside(cq.Vector(ox, 30, zs - 1.0))
    # Außenwand zwischen Fach und Rand
    assert solid.isInside(cq.Vector(LIP_MARGIN / 2, 30, zs - 1.0))


def test_grid_around_tool_keeps_wall_to_pocket():
    o = synthetic_pliers()
    spec = InsertSpec(grid_x=5, grid_y=3, auto_center=False, auto_grip=False, comp_follow=True,
                      placements=[Placement(object_id="pliers", x=12, y=42)])
    lay = compute_layout(spec, {"pliers": o})
    polys = grid_compartments(lay, spec, 2, 2)
    assert polys
    pocket = lay.pocket_union()
    assert all(p.distance(pocket) >= spec.comp_wall - 0.05 for p in polys)
    assert all(lay.inner.buffer(1e-6).contains(p) for p in polys)


# ---- API -----------------------------------------------------------------------

def test_api_create_bin_and_redivide():
    r = client.post("/api/inserts/bin", json={"name": "Schrauben", "grid_x": 3, "grid_y": 2, "cols": 3, "rows": 2,
                                              "height_mm": 25})
    assert r.status_code == 200, r.text
    ins = r.json()
    assert ins["name"] == "Schrauben" and ins["placements"] == [] and ins["height_mm"] == 25
    assert len(ins["compartments"]) == 6 and all(c["generated"] and c["depth"] is None for c in ins["compartments"])
    lay = client.post(f"/api/inserts/{ins['id']}/layout", json=ins).json()
    assert (lay["grid_x"], lay["grid_y"]) == (3, 2) and lay["total_height"] == pytest.approx(25)
    assert len(lay["compartments"]) == 6 and not lay["warnings"]

    # eigenes Fach bleibt, erzeugte werden ersetzt
    own = {"x": 10, "y": 10, "w": 20, "l": 20, "depth": 5}
    spec = {**ins, "compartments": [*ins["compartments"], own]}
    g = client.post(f"/api/inserts/{ins['id']}/compartments/grid", json={"spec": {**spec, "compartments": [own]},
                                                                         "cols": 1, "rows": 1}).json()
    assert len(g["compartments"]) == 2 and not g["compartments"][0]["generated"]
    big = Polygon(g["compartments"][1]["polygon"])
    assert big.distance(comp_polygon(Compartment(**own))) >= ins["comp_wall"] - 0.05

    bad = client.post(f"/api/inserts/{ins['id']}/compartments/grid", json={"spec": ins, "cols": 1, "rows": 12})
    assert bad.status_code == 422 and "schmaler" in bad.json()["detail"]


def test_deleting_a_compartment_does_not_move_others():
    ins = client.post("/api/inserts/bin", json={"grid_x": 2, "grid_y": 1, "cols": 2, "rows": 1, "height_mm": 20}).json()
    a = client.post(f"/api/inserts/{ins['id']}/layout", json=ins).json()["compartments"]
    one = {**ins, "compartments": ins["compartments"][:1]}
    b = client.post(f"/api/inserts/{ins['id']}/layout", json=one).json()["compartments"]
    assert b[0]["polygons"][0]["exterior"] == a[0]["polygons"][0]["exterior"]


def test_bin_too_small_creates_nothing():
    n = len(client.get("/api/inserts").json())
    r = client.post("/api/inserts/bin", json={"grid_x": 1, "grid_y": 1, "cols": 10, "rows": 1})
    assert r.status_code == 422
    assert len(client.get("/api/inserts").json()) == n


def test_bin_in_project_uses_template_and_goes_into_drawer():
    p = client.post("/api/projects", json={"name": "Kleinteile", "drawer_x": 300, "drawer_y": 200}).json()
    p["template"]["height_mm"] = 30.0
    p["template"]["comp_wall"] = 2.0
    client.put(f"/api/projects/{p['id']}", json=p)
    ins = client.post("/api/inserts/bin", json={"grid_x": 2, "grid_y": 2, "cols": 2, "rows": 2,
                                                "project_id": p["id"]}).json()
    assert ins["project_id"] == p["id"] and ins["height_mm"] == 30.0 and ins["comp_wall"] == 2.0
    assert "height_mm" not in ins["overrides"]
    polys = [Polygon(c["polygon"]) for c in ins["compartments"]]
    assert min(polys[0].distance(q) for q in polys[1:]) >= 2.0 - 0.05      # Wand aus der Vorlage
    own = client.post("/api/inserts/bin", json={"grid_x": 1, "grid_y": 1, "cols": 1, "rows": 1,
                                                "height_mm": 20, "project_id": p["id"]}).json()
    assert own["height_mm"] == 20 and "height_mm" in own["overrides"]
    a = client.post(f"/api/projects/{p['id']}/arrange", json={"mode": "all"}).json()
    assert ins["id"] in a["placed"] and own["id"] in a["placed"] and not a["unfinished"]
    c = client.get(f"/api/projects/{p['id']}/clone").json()
    item = next(i for i in c["inserts"] if i["id"] == ins["id"])
    assert item["error"] is None and (item["gx"], item["gy"]) == (2, 2) and item["tools"] == []
    assert len(item["layout"]["compartments"]) == 4


def test_empty_insert_in_project_reports_empty():
    p = client.post("/api/projects", json={"name": "Leer", "drawer_x": 300, "drawer_y": 200}).json()
    i = client.post("/api/inserts", json={"name": "Leer", "project_id": p["id"]}).json()
    a = client.post(f"/api/projects/{p['id']}/arrange", json={"mode": "all"}).json()
    assert i["id"] in a["unfinished"]
    c = client.get(f"/api/projects/{p['id']}/clone").json()
    assert "leer" in next(x for x in c["inserts"] if x["id"] == i["id"])["error"]
