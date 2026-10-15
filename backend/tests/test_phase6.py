import pytest
from fastapi.testclient import TestClient

from app.geometry.baseplate import make_tile, plan_plate
from app.geometry.checks import check_shape
from app.main import app
from app.schemas import BaseplateSpec


def test_tile_plan_and_geometry():
    spec = BaseplateSpec(drawer_x=500, drawer_y=300, bed_x=256, bed_y=256, clearance=0.5)
    plan = plan_plate(spec)
    assert (plan.nx, plan.ny) == (11, 7)
    assert (len(plan.col_sizes), len(plan.row_sizes)) == (3, 2)
    assert all(t.w <= 256 + 1e-6 and t.h <= 256 + 1e-6 for t in plan.tiles)
    # Rand nur an Außenkanten: alle Kacheln zusammen füllen die Schublade minus Spiel
    from shapely.ops import unary_union
    u = unary_union([t.poly for t in plan.tiles])
    assert u.bounds == pytest.approx((0.5, 0.5, 499.5, 299.5), abs=0.01)
    assert u.area == pytest.approx(499 * 299, rel=1e-6)
    one = plan_plate(BaseplateSpec(drawer_x=130, drawer_y=100, clearance=0.5))
    s = make_tile(one, one.tiles[0])
    c = check_shape(s)
    assert c.ok
    assert c.bbox[0] == pytest.approx(129.0, abs=0.1) and c.bbox[1] == pytest.approx(99.0, abs=0.1)
    assert c.bbox[2] == pytest.approx(4.75, abs=0.05)


def test_tile_profile_matches_gridfinity_and_has_no_corner_gaps():
    """Querschnitt durch die Zellmitte: 42-mm-Raster, Profil 45°/senkrecht/45°, offener Boden;
    die Kachel ist bis in die Ecken voll (keine runden Außenecken, die beim Stoß Lücken lassen)."""
    from app.geometry.checks import tessellate
    plan = plan_plate(BaseplateSpec(drawer_x=127, drawer_y=85, clearance=0.5))       # 3 x 2, Rand 0
    m = tessellate(make_tile(plan, plan.tiles[0]))
    sec = m.section(plane_origin=[21, 0, 0], plane_normal=[1, 0, 0])
    pts = sec.vertices[:, 1:]
    assert pts[:, 1].max() == pytest.approx(4.65, abs=0.05)          # Grat zwischen den Zellen
    # Taschenboden offen: zwischen den Wänden gibt es bei z = 0 nichts
    inner = pts[(pts[:, 0] > 4) & (pts[:, 0] < 38)]
    assert len(inner) == 0 or inner[:, 1].min() > -1e-6
    # volle Ecken: Material an allen vier Außenecken auf halber Höhe
    import cadquery as cq
    solid = make_tile(plan, plan.tiles[0]).val()
    for x, y in [(0.3, 0.3), (125.7, 0.3), (0.3, 83.7), (125.7, 83.7)]:
        assert solid.isInside(cq.Vector(x, y, 1.0))
    assert not solid.isInside(cq.Vector(21, 21, 1.0))           # Zellmitte offen


def test_disabled_cells_and_tiles():
    spec = BaseplateSpec(drawer_x=300, drawer_y=200, bed_x=180, bed_y=180, disabled=[[0, 0], [3, 2], [6, 3]])
    plan = plan_plate(spec)
    assert (0, 0) not in plan.active and (3, 2) not in plan.active
    assert all((0, 0) not in t.cells for t in plan.tiles)
    assert sum(len(t.cells) for t in plan.tiles) == plan.nx * plan.ny - 3
    # die abgewählte Ecke bleibt frei (auch der Rand daneben)
    from shapely.geometry import Point
    assert not any(t.poly.contains(Point(10, 10)) for t in plan.tiles)
    with pytest.raises(ValueError):
        plan_plate(BaseplateSpec(drawer_x=50, drawer_y=50, disabled=[[0, 0]]))


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


def test_tile_split_by_disabled_cells_becomes_separate_tiles():
    # 3 x 1 Zellen auf einer Kachel, Mitte abgewählt -> zwei getrennte Kacheln
    plan = plan_plate(BaseplateSpec(drawer_x=127, drawer_y=43, clearance=0.5, disabled=[[1, 0]]))
    assert len(plan.tiles) == 2 and all(len(t.cells) == 1 for t in plan.tiles)
