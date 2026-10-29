"""Schriftzüge auf der Einlage (erhaben, bündig, vertieft; eigene Farbe) und Blindstopfen (flach)."""
import cadquery as cq
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Polygon

from app.geometry.gridfinity import FOOT_H, LIP_H
from app.geometry.insert_cad import build_insert
from app.geometry.layout import TEXT_GAP, compute_layout
from app.geometry.samples import synthetic_pliers
from app.geometry.text import text_polygon
from app.main import app
from app.schemas import PLUG_MIN_H, InsertSpec, Placement, TextLabel, color_palette

client = TestClient(app)


def _plug(**kw) -> InsertSpec:
    return InsertSpec(grid_x=kw.pop("gx", 1), grid_y=kw.pop("gy", 1), height_mm=kw.pop("height_mm", 7.0),
                      stacking_lip=kw.pop("stacking_lip", False), blank=True, auto_grip=False, auto_center=False, **kw)


def test_text_outline_size_rotation_and_holes():
    t = TextLabel(text="HEH", x=50, y=20, size=10)
    p = text_polygon(t)
    x0, y0, x1, y1 = p.bounds
    assert y1 - y0 == pytest.approx(10, abs=0.05)                     # Versalhöhe = size
    assert ((x0 + x1) / 2, (y0 + y1) / 2) == pytest.approx((50, 20), abs=0.05)
    o = text_polygon(TextLabel(text="O", size=10))
    assert sum(len(g.interiors) for g in getattr(o, "geoms", [o])) == 1   # das O hat ein Loch
    r = text_polygon(t.model_copy(update={"rot_deg": 90}))
    rx0, ry0, rx1, ry1 = r.bounds
    assert (rx1 - rx0, ry1 - ry0) == pytest.approx((y1 - y0, x1 - x0), abs=0.2)
    assert r.area == pytest.approx(p.area, rel=1e-3)


def test_text_clipped_away_from_pocket_and_rim():
    o = synthetic_pliers()
    spec = InsertSpec(grid_x=5, grid_y=2, auto_grip=False, placements=[Placement(object_id="pliers", x=12, y=42)],
                      texts=[TextLabel(text="ZANGE", x=100, y=42, size=10)])      # mitten über der Tasche
    lay = compute_layout(spec, {"pliers": o})
    assert any("abgeschnitten" in w or "entfällt" in w for w in lay.warnings)
    for t in lay.texts:
        assert t.poly.distance(lay.pocket_union()) >= TEXT_GAP - 0.01
        assert lay.inner.buffer(1e-6).contains(t.poly)


def test_text_follows_centering():
    o = synthetic_pliers()
    spec = InsertSpec(grid_x=5, grid_y=3, auto_grip=False, placements=[Placement(object_id="pliers", x=0, y=0)],
                      texts=[TextLabel(text="A", x=20, y=-30, size=6)])
    lay = compute_layout(spec, {"pliers": o})
    sx, sy = lay.shift
    c = lay.texts[0].poly.centroid
    assert (round(c.x - sx), round(c.y - sy)) == pytest.approx((20, -30), abs=1.5)


@pytest.mark.parametrize("style", ["raised", "flush", "engraved"])
def test_text_cad_styles_one_body_and_own_color(style):
    spec = InsertSpec(grid_x=2, grid_y=1, height_mm=20, auto_grip=False, auto_center=False,
                      texts=[TextLabel(text="M4", x=41.75, y=20.75, size=9, style=style, height=1.0, color="#ffffff")])
    r = build_insert(spec, {})
    assert r.checks.valid and r.checks.solid_count == 1 and r.checks.watertight, r.checks.messages
    assert r.volume_sum_ok and all(r.part_checks.values())
    zs = r.layout.z_surface
    bb = r.body.val().BoundingBox()
    assert bb.zmax == pytest.approx(zs + LIP_H, abs=0.1)          # Stapelrand ist höher als 1 mm Schrift
    text = next(p for p in r.parts if p.group == "text")
    assert text.slot == color_palette(spec).index("#ffffff") + 1
    tb = text.shape.val().BoundingBox()
    t = r.layout.texts[0]
    pt = next(g for g in getattr(t.poly, "geoms", [t.poly])).representative_point()
    solid = r.body.val()
    if style == "raised":
        assert tb.zmax == pytest.approx(zs + 1.0, abs=0.05)
        assert solid.isInside(cq.Vector(pt.x, pt.y, zs + 0.5))
    elif style == "flush":
        assert (tb.zmin, tb.zmax) == pytest.approx((zs - 1.0, zs), abs=0.05)
        assert solid.isInside(cq.Vector(pt.x, pt.y, zs - 0.5))
    else:
        assert not solid.isInside(cq.Vector(pt.x, pt.y, zs - 0.5))       # vertieft: offen
        assert tb.zmax == pytest.approx(zs, abs=0.05)                     # Farbe am Boden und an den Wänden bis oben
        assert tb.zmin == pytest.approx(zs - 1.0 - spec.color_skin.floor, abs=0.05)


def test_flat_plug_one_watertight_body():
    spec = _plug(gx=2, gy=1, height_mm=PLUG_MIN_H, texts=[TextLabel(text="LEER", x=41.75, y=20.75, size=8)])
    lay = compute_layout(spec, {})
    assert not lay.lip and lay.total_height == pytest.approx(PLUG_MIN_H) and not lay.warnings
    r = build_insert(spec, {})
    assert r.checks.valid and r.checks.solid_count == 1 and r.checks.watertight
    bb = r.body.val().BoundingBox()
    assert bb.zmin == pytest.approx(0, abs=0.05) and bb.zmax == pytest.approx(PLUG_MIN_H + 0.6, abs=0.05)
    assert bb.xlen == pytest.approx(2 * 42 - 0.5, abs=0.3)
    assert PLUG_MIN_H > FOOT_H


def test_flat_insert_with_lip_keeps_minimum_and_warns():
    lay = compute_layout(_plug(height_mm=6.0, stacking_lip=True), {})
    assert lay.lip and lay.total_height == pytest.approx(7 + LIP_H)
    assert any("Stapelrand" in w for w in lay.warnings)


def test_engraved_text_too_flat_is_dropped():
    lay = compute_layout(_plug(height_mm=PLUG_MIN_H, texts=[TextLabel(text="X", x=20, y=20, style="engraved")]), {})
    assert not lay.texts and any("zu flach" in w for w in lay.warnings)


# ---- API -----------------------------------------------------------------------

def test_api_plug_with_text_and_layout():
    r = client.post("/api/inserts/plug", json={"name": "Deckel", "grid_x": 2, "grid_y": 1, "height_mm": 6, "text": "M3"})
    assert r.status_code == 200, r.text
    ins = r.json()
    assert ins["blank"] and ins["height_mm"] == 6 and not ins["stacking_lip"] and len(ins["texts"]) == 1
    lay = client.post(f"/api/inserts/{ins['id']}/layout", json=ins).json()
    assert lay["total_height"] == pytest.approx(6) and not lay["lip"] and len(lay["texts"]) == 1
    assert lay["text_top"] == pytest.approx(6.6)
    poly = Polygon(lay["texts"][0]["polygons"][0]["exterior"])
    assert poly.centroid.x == pytest.approx(41.75, abs=6)
    assert client.post("/api/inserts/plug", json={"height_mm": 4}).status_code == 422


def test_plug_in_project_keeps_own_height_and_lip():
    p = client.post("/api/projects", json={"name": "Stopfen", "drawer_x": 300, "drawer_y": 200}).json()
    p["template"]["height_mm"] = 30.0
    p["template"]["color_hex"]["body"] = "#112233"
    client.put(f"/api/projects/{p['id']}", json=p)
    plug = client.post("/api/inserts/plug", json={"grid_x": 1, "grid_y": 1, "height_mm": 6, "project_id": p["id"]}).json()
    assert plug["height_mm"] == 6 and not plug["stacking_lip"] and plug["color_hex"]["body"] == "#112233"
    # Vorlage ändert sich: Höhe und Rand bleiben, Farbe folgt
    p = client.get(f"/api/projects/{p['id']}").json()
    p["template"]["height_mm"] = 40.0
    p["template"]["color_hex"]["body"] = "#445566"
    client.put(f"/api/projects/{p['id']}", json=p)
    cur = client.get(f"/api/inserts/{plug['id']}").json()
    assert cur["height_mm"] == 6 and not cur["stacking_lip"] and cur["color_hex"]["body"] == "#445566"
    # wieder zuordnen setzt eigene Werte zurück, beim Blindstopfen aber nicht die Höhe
    client.post(f"/api/projects/{p['id']}/assign", json={"kind": "insert", "id": plug["id"], "member": True})
    assert client.get(f"/api/inserts/{plug['id']}").json()["height_mm"] == 6
    tool = client.post("/api/inserts/bin", json={"grid_x": 1, "grid_y": 1, "cols": 1, "rows": 1, "project_id": p["id"]}).json()
    a = client.post(f"/api/projects/{p['id']}/arrange", json={"mode": "all"}).json()
    assert plug["id"] in a["placed"] and not a["unfinished"]
    c = client.get(f"/api/projects/{p['id']}/clone").json()
    item = next(i for i in c["inserts"] if i["id"] == plug["id"])
    assert item["error"] is None and item["blank"] and item["total_height"] == pytest.approx(6)
    assert tool["id"] in [i["id"] for i in c["inserts"]]
    assert not any("unterschiedlich hoch" in w for w in c["warnings"])     # Stopfen zählen nicht mit


def test_build_job_plug_slots_without_gaps():
    """Blindstopfen: Taschenfarbe gibt es nicht, die Schrift bekommt Slot 2 (nicht 3)."""
    import xml.etree.ElementTree as ET
    import zipfile

    from app import config
    from app.build_tasks import build_insert_job

    spec = _plug(gx=1, gy=1, height_mm=6.0, texts=[TextLabel(text="A", x=20.75, y=20.75, size=10, color="#d6322e")])
    out = config.DATA_DIR / "inserts" / "plugjob" / "out"
    r = build_insert_job(str(out), spec.model_dump_json(), {})
    assert r["checks"]["solid_count"] == 1 and r["checks"]["watertight"] and r["checks"]["volume_sum_ok"]
    assert set(r["checks"]["parts"]) == {"Körper", "Schrift"} and "fit_test" not in r["outputs"]
    cfg = ET.fromstring(zipfile.ZipFile(out / "einlage.3mf").read("Metadata/model_settings.config"))
    ex = {pt.find("metadata[@key='name']").get("value"): pt.find("metadata[@key='extruder']").get("value")
          for pt in cfg.iter("part")}
    assert ex == {"Körper": "1", "Schrift": "2"}


def test_only_plugs_in_drawer_count_as_equal_height():
    """Nur Blindstopfen in der Schublade: keine Warnung 'unterschiedlich hoch'."""
    p = client.post("/api/projects", json={"name": "nur Stopfen", "drawer_x": 300, "drawer_y": 200}).json()
    for h in (6, 9):
        client.post("/api/inserts/plug", json={"height_mm": h, "project_id": p["id"]})
    client.post(f"/api/projects/{p['id']}/arrange", json={"mode": "all"})
    c = client.get(f"/api/projects/{p['id']}/clone").json()
    assert sum(1 for i in c["inserts"] if i["placed"]) == 2 and c["heights_equal"]
