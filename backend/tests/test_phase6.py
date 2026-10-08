import pytest
from fastapi.testclient import TestClient
from shapely.geometry import box

from app.geometry.auto_compartments import propose_compartments
from app.geometry.baseplate import make_tile, plan_tiles
from app.geometry.checks import check_shape
from app.geometry.layout import compute_layout
from app.geometry.samples import synthetic_pliers
from app.main import app
from app.schemas import BaseplateSpec, InsertSpec, Placement


def test_tile_plan_and_geometry():
    spec = BaseplateSpec(drawer_x=500, drawer_y=300, bed_x=256, bed_y=256, clearance=0.5)
    tiles, info = plan_tiles(spec)
    assert info["cells_x"] == 11 and info["cells_y"] == 7
    assert info["tiles_x"] == 3 and info["tiles_y"] == 2
    assert all(t.w <= 256 + 1e-6 and t.h <= 256 + 1e-6 for t in tiles)
    # Rand nur an Außenkanten, Summe der Breiten = Schublade minus Spiel
    xs = sorted({t.x0 for t in tiles})
    assert sum(next(t.w for t in tiles if t.x0 == x) for x in xs) == pytest.approx(500 - 1.0, abs=0.01)
    t0 = tiles[0]
    assert t0.rim_l > 0 and t0.rim_r == 0
    one = make_tile(plan_tiles(BaseplateSpec(drawer_x=130, drawer_y=100, clearance=0.5))[0][0])
    c = check_shape(one)
    assert c.ok
    assert c.bbox[0] == pytest.approx(129.0, abs=0.1) and c.bbox[1] == pytest.approx(99.0, abs=0.1)


def test_auto_compartments_free_and_apart():
    o = synthetic_pliers()
    spec = InsertSpec(grid_x=5, grid_y=3, height_u=5, placements=[Placement(object_id="pliers", x=6, y=30)])
    lay = compute_layout(spec, {"pliers": o})
    props = propose_compartments(lay, spec)
    assert props
    pockets = lay.pocket_union()
    for p in props:
        r = box(p.x, p.y, p.x + p.w, p.y + p.l)
        assert lay.inner.contains(r)
        assert r.distance(pockets) >= spec.min_wall - 0.6
        assert p.w >= 20 and p.l >= 20
    for i in range(len(props)):
        for j in range(i + 1, len(props)):
            a, b = props[i], props[j]
            assert box(a.x, a.y, a.x + a.w, a.y + a.l).distance(box(b.x, b.y, b.x + b.w, b.y + b.l)) >= spec.min_wall - 0.6


def test_baseplate_api_job():
    import time
    c = TestClient(app)
    j = c.post("/api/baseplates/build", json={"drawer_x": 300, "drawer_y": 200}).json()["job_id"]
    for _ in range(120):
        r = c.get(f"/api/jobs/{j}").json()
        if r["status"] != "running":
            break
        time.sleep(1)
    assert r["status"] == "done", r.get("error")
    assert c.get(r["outputs"]["plan"]).text.startswith("<svg")
    assert c.get(r["outputs"]["zip"]).status_code == 200
    assert c.post("/api/baseplates/build", json={"drawer_x": 30, "drawer_y": 200}).status_code == 422
