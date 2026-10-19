"""Ohne Seitenfoto (Dicke von Hand) und Taschentiefe von Hand."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.synth import camera, render, rot_rect
from tests.test_api import jpg

client = TestClient(app)


def _top_only_object(L, W, T):
    img = render(rot_rect(150, 105, L, W, 20), T, camera(offset=(-40, 30)), seed=7)
    oid = client.post("/api/objects", json={"name": "Flachwerkzeug"}).json()["id"]
    r = client.post(f"/api/objects/{oid}/photos/top", files={"file": ("top.jpg", jpg(img), "image/jpeg")})
    assert r.status_code == 200, r.text
    assert client.post(f"/api/objects/{oid}/photos/top/segment", json={}).status_code == 200
    return oid


def test_profile_without_side_photo():
    L, W, T = 150.0, 38.0, 14.0
    oid = _top_only_object(L, W, T)
    # ohne Seitenfoto und ohne Freigabe: wie bisher Fehler
    assert client.post(f"/api/objects/{oid}/profile", json={}).status_code == 409
    # ohne Dicke geht es nicht
    r = client.post(f"/api/objects/{oid}/profile", json={"side_skipped": True})
    assert r.status_code == 422 and "Dicke" in r.text
    # überall gleich dick: Parallaxe mit der Dicke herausgerechnet
    o = client.post(f"/api/objects/{oid}/profile", json={"side_skipped": True, "thickness_mm": T,
                                                         "uniform_thickness": True}).json()
    assert o["side_skipped"] and o["length_mm"] == pytest.approx(L, abs=0.5)
    assert o["width_mm"] == pytest.approx(W, abs=0.5)
    pr = o["profile"]
    assert pr["levels"] == [[0.0, pytest.approx(o["length_mm"], abs=0.5), 0.0]]     # Raster 0,5 mm
    assert max(pr["top"]) == pytest.approx(T) and min(pr["top"]) == pytest.approx(T) and max(pr["bottom"]) == 0
    assert pr["measured"] is None
    # nicht gleich dick: Foto-Umriss bleibt (nie kleiner, eher etwas länger)
    o2 = client.post(f"/api/objects/{oid}/profile", json={"uniform_thickness": False}).json()
    assert o2["length_mm"] > o["length_mm"] + 1.0 and o2["width_mm"] >= o["width_mm"] - 0.1
    assert any("Perspektive nicht herausgerechnet" in w for w in o2["warnings"])
    # Ebene von Hand bleibt erhalten (wie mit Seitenfoto)
    o3 = client.post(f"/api/objects/{oid}/profile", json={"levels": [[0, 50, 0], [50, 400, 2]]}).json()
    assert [q[2] for q in o3["profile"]["levels"]] == [0, 2]
    assert min(o3["profile"]["top"]) == pytest.approx(T)

    # Einlage damit bauen: Layout und Tiefe
    ins = client.post("/api/inserts", json={"name": "Ohne Seite", "placements": [{"object_id": oid}]}).json()
    lay = client.post(f"/api/inserts/{ins['id']}/layout").json()
    assert lay["pieces"] and lay["depth"][0] == pytest.approx(0.65 * T, abs=0.05)

    # neues Seitenfoto: wieder mit Seitenansicht auswerten
    side = render(rot_rect(160, 100, L, T, -15), W, camera(offset=(5, -10)), seed=8)
    client.post(f"/api/objects/{oid}/photos/side", files={"file": ("s.jpg", jpg(side), "image/jpeg")})
    assert client.get(f"/api/objects/{oid}").json()["side_skipped"] is False


def test_pocket_depth_by_hand():
    demo = client.post("/api/objects/demo").json()
    T = max(demo["profile"]["top"])
    ins = client.post("/api/inserts", json={"name": "Tiefe", "placements": [{"object_id": demo["id"]}]}).json()
    spec = client.get(f"/api/inserts/{ins['id']}").json()
    lay = client.post(f"/api/inserts/{ins['id']}/layout", json=spec).json()
    assert lay["depth"][0] == pytest.approx(0.65 * T, abs=0.05)

    spec["depth_mm"] = 20.0
    lay = client.post(f"/api/inserts/{ins['id']}/layout", json=spec).json()
    assert lay["depth"][0] == pytest.approx(20.0) and lay["sink"][0] == pytest.approx(20.0 / T)
    clz = spec["clearance_z"]
    deepest = max(p["depth"] for p in lay["pieces"])
    assert deepest == pytest.approx(20.0 + clz, abs=0.01)      # tiefste Ebene: Tiefe + Bodenabstand

    # zu flach für die Ebenen: wird angehoben und gemeldet
    spec["depth_mm"] = 1.0
    lay = client.post(f"/api/inserts/{ins['id']}/layout", json=spec).json()
    assert lay["depth"][0] > 1.0 and any("mindestens 1 mm Tasche" in w for w in lay["warnings"])

    # feste Gesamthöhe zu klein: Hinweis nennt die Tiefe statt Prozent
    spec.update(depth_mm=30.0, height_mm=25.0)
    lay = client.post(f"/api/inserts/{ins['id']}/layout", json=spec).json()
    assert any("Taschen nur" in w for w in lay["warnings"])


def test_depth_is_template_field():
    from app.schemas import TEMPLATE_FIELDS, InsertTemplate
    assert "depth_mm" in TEMPLATE_FIELDS and InsertTemplate().depth_mm is None
