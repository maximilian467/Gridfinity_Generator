import io
import time
import zipfile

import cv2
import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.synth import camera, render, rot_rect

client = TestClient(app)


def jpg(img) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return buf.tobytes()


def wait_job(job_id: str, timeout: float = 240):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "error"):
            return j
        time.sleep(1)
    raise TimeoutError


def test_files_traversal_blocked():
    for u in ("/api/files/../../pyproject.toml", "/api/files/%2e%2e/%2e%2e/pyproject.toml",
              "/api/files/..%5C..%5Cpyproject.toml", "/%2e%2e/pyproject.toml"):
        r = client.get(u)
        assert b"[project]" not in r.content


def test_full_flow_with_synthetic_photos():
    L, W, T = 150.0, 38.0, 14.0
    top = render(rot_rect(140, 110, L, W, 25), T, camera(offset=(-10, 5)), seed=1)
    side = render(rot_rect(160, 100, L, T, -15), W, camera(offset=(5, -10)), seed=2)

    oid = client.post("/api/objects", json={"name": "Testbalken"}).json()["id"]
    for view, img in (("top", top), ("side", side)):
        r = client.post(f"/api/objects/{oid}/photos/{view}", files={"file": (f"{view}.jpg", jpg(img), "image/jpeg")})
        assert r.status_code == 200, r.text
        meta = r.json()
        assert meta["corners_found"] and len(meta["corners_px"]) == 4
        assert meta["pose"]["C_mm"][2] == pytest.approx(420, rel=0.03)
        seg = client.post(f"/api/objects/{oid}/photos/{view}/segment", json={})
        assert seg.status_code == 200, seg.text
        assert seg.json()["contour_px"]
        assert client.get(seg.json()["overlay_url"]).status_code == 200

    # manuelle Maske hochladen (Roundtrip)
    m = client.get(f"/api/files/objects/{oid}/top_mask.png").content
    r = client.put(f"/api/objects/{oid}/photos/top/mask", files={"file": ("m.png", m, "image/png")})
    assert r.status_code == 200

    obj = client.post(f"/api/objects/{oid}/profile", json={"side_flip_lr": False}).json()
    assert obj["length_mm"] == pytest.approx(L, abs=0.4)
    assert obj["width_mm"] == pytest.approx(W, abs=0.4)
    assert max(obj["profile"]["top"][10:-10]) == pytest.approx(T, abs=0.5)
    # Balken: eine Ebene; feste Anzahl und Handkorrektur der Ebenen
    assert len(obj["profile"]["levels"]) == 1 and len(obj["profile"]["measured"]) == len(obj["profile"]["s"])
    o2 = client.post(f"/api/objects/{oid}/profile", json={"side_flip_lr": False, "level_count": 2}).json()
    assert len(o2["profile"]["levels"]) == 2
    o3 = client.post(f"/api/objects/{oid}/profile", json={"side_flip_lr": False,
                                                          "levels": [[0, 60, 0], [60, 150, 3]]}).json()
    lv = o3["profile"]["levels"]
    assert [q[2] for q in lv] == [0, 3] and lv[-1][1] == pytest.approx(o3["length_mm"], abs=0.6)
    assert o3["profile"]["bottom"][-1] == pytest.approx(3)
    obj = client.post(f"/api/objects/{oid}/profile", json={"side_flip_lr": False}).json()

    # Einlage
    ins = client.post("/api/inserts", json={"name": "Test", "placements": [
        {"object_id": oid, "x": 8, "y": 24, "rot_deg": 0}]}).json()
    lay = client.post(f"/api/inserts/{ins['id']}/layout").json()
    assert lay["grid_x"] >= 4 and lay["pieces"] and not [w for w in lay["warnings"] if "Innenbereich" in w]
    job = client.post(f"/api/inserts/{ins['id']}/build").json()["job_id"]
    j = wait_job(job)
    assert j["status"] == "done", j.get("error")
    c = j["checks"]
    assert c["valid"] and c["solid_count"] == 1 and c["watertight"] and c["volume_sum_ok"]
    for key in ("3mf", "stl", "parts_zip", "step", "glb", "fit_test"):
        r = client.get(j["outputs"][key])
        assert r.status_code == 200 and len(r.content) > 500, key
    assert zipfile.ZipFile(io.BytesIO(client.get(j["outputs"]["3mf"]).content)).namelist()


def test_demo_object_and_insert_crud():
    demo = client.post("/api/objects/demo").json()
    assert demo["length_mm"] == pytest.approx(160)
    ins = client.post("/api/inserts", json={"name": "Demo", "placements": [
        {"object_id": demo["id"], "x": 6, "y": 30}]}).json()
    lay = client.post(f"/api/inserts/{ins['id']}/layout").json()
    assert lay["grid_x"] == 5 and lay["height_u"] >= 3
    # Live-Layout mit ungespeicherter Spec im Body
    spec = client.get(f"/api/inserts/{ins['id']}").json()
    spec["clearance_xy"] = 3.0
    lay2 = client.post(f"/api/inserts/{ins['id']}/layout", json=spec).json()
    assert lay2["grid_x"] >= lay["grid_x"]
    dup = client.post(f"/api/inserts/{ins['id']}/duplicate").json()
    assert dup["id"] != ins["id"]
    assert client.delete(f"/api/inserts/{ins['id']}").json()["ok"]
    assert client.get(f"/api/inserts/{ins['id']}").status_code == 404


def test_compartments_merge_split_and_reason():
    from shapely.geometry import Polygon, box
    demo = client.post("/api/objects/demo").json()
    ins = client.post("/api/inserts", json={"grid_x": 3, "grid_y": 5, "auto_grip": False, "comp_follow": False,
                                            "placements": [{"object_id": demo["id"], "rot_deg": 90}]}).json()
    spec = dict(ins)
    r = client.post(f"/api/inserts/{ins['id']}/auto-compartments", json=spec).json()
    assert r["compartments"] and r["reason"] is None
    spec["compartments"] = r["compartments"]
    sp = client.post(f"/api/inserts/{ins['id']}/compartments/edit",
                     json={"spec": spec, "op": "split", "indices": [0], "parts": 2}).json()
    assert len(sp["compartments"]) == len(r["compartments"]) + 1
    spec["compartments"] = sp["compartments"]
    P = [Polygon(c["polygon"]) for c in spec["compartments"]]
    i, j = next((i, j) for i in range(len(P)) for j in range(i + 1, len(P)) if P[i].distance(P[j]) < 3)
    # gerade (Standard): ein Rechteck, mindestens so groß wie der größere Kasten
    m0 = client.post(f"/api/inserts/{ins['id']}/compartments/edit",
                     json={"spec": spec, "op": "merge", "indices": [i, j]}).json()
    R = Polygon(m0["compartments"][-1]["polygon"])
    assert R.area > 0.97 * box(*R.bounds).area and R.area >= max(P[i].area, P[j].area) * 0.97
    # konturfolgend: Wand dazwischen fällt weg, nichts geht verloren
    m = client.post(f"/api/inserts/{ins['id']}/compartments/edit",
                    json={"spec": {**spec, "comp_follow": True}, "op": "merge", "indices": [i, j]}).json()
    assert Polygon(m["compartments"][-1]["polygon"]).area >= P[i].area + P[j].area
    spec["compartments"] = m["compartments"]
    assert not client.post(f"/api/inserts/{ins['id']}/layout", json=spec).json()["warnings"]
    # zu knapp: verständlicher Grund statt stiller Leere
    tight = client.post("/api/inserts", json={"grid_x": 4, "grid_y": 2, "auto_grip": False, "comp_min_size": 60,
                                              "placements": [{"object_id": demo["id"]}]}).json()
    r = client.post(f"/api/inserts/{tight['id']}/auto-compartments", json=tight).json()
    assert r["compartments"] == [] and "Platz" in r["reason"]


def test_single_compartment_at_click():
    from shapely.geometry import Point, Polygon
    demo = client.post("/api/objects/demo").json()
    ins = client.post("/api/inserts", json={"grid_x": 3, "grid_y": 5, "auto_grip": False, "comp_depth": None,
                                            "placements": [{"object_id": demo["id"], "rot_deg": 90}]}).json()
    lay = client.post(f"/api/inserts/{ins['id']}/layout", json=ins).json()
    ox, oy = lay["outer"]
    r = client.post(f"/api/inserts/{ins['id']}/compartments/at", json={"spec": ins, "x": 8, "y": oy / 2})
    assert r.status_code == 200, r.text
    comps = r.json()["compartments"]
    assert len(comps) == 1 and comps[0]["depth"] is None
    sx, sy = lay["shift"]
    assert Polygon(comps[0]["polygon"]).buffer(0.6).contains(Point(8 - sx, oy / 2 - sy))
    ins["compartments"] = comps
    lay2 = client.post(f"/api/inserts/{ins['id']}/layout", json=ins).json()
    assert not lay2["warnings"] and lay2["compartments"][0]["max_depth"]
    # Klick in eine Tasche: verständlicher Fehler
    bad = client.post(f"/api/inserts/{ins['id']}/compartments/at", json={"spec": ins, "x": ox / 2, "y": oy / 2})
    assert bad.status_code == 422


def test_set_levels_keeps_reference():
    demo = client.post("/api/objects/demo").json()
    lv = demo["profile"]["levels"]
    T = max(demo["profile"]["top"])
    gi = min(range(len(lv)), key=lambda i: lv[i][2])          # tiefste Ebene (Griffschutz)
    lv2 = [[a, b, z - 2.0 if i == gi else z] for i, (a, b, z) in enumerate(lv)]
    o = client.put(f"/api/objects/{demo['id']}/levels", json={"levels": lv2}).json()
    # Griffschutz 2 mm tiefer = Werkzeug dort 2 mm dicker: andere Ebenen 2 mm höher, Oberseite mit
    assert o["profile"]["levels"][gi][2] == 0
    assert [q[2] for i, q in enumerate(o["profile"]["levels"]) if i != gi] == pytest.approx(
        [q[2] + 2 for i, q in enumerate(lv) if i != gi])
    assert max(o["profile"]["top"]) == pytest.approx(T + 2, abs=0.01)


def test_compartment_rect_and_straight_cut():
    from shapely.geometry import Polygon, box
    demo = client.post("/api/objects/demo").json()
    ins = client.post("/api/inserts", json={"grid_x": 3, "grid_y": 5, "auto_grip": False,
                                            "placements": [{"object_id": demo["id"], "rot_deg": 90}]}).json()
    lay = client.post(f"/api/inserts/{ins['id']}/layout", json=ins).json()
    ox, oy = lay["outer"]
    # Rechteck vom Rand bis über die Tasche hinaus: gerade Kanten außen, Wand folgt der Tasche
    r = client.post(f"/api/inserts/{ins['id']}/compartments/rect",
                    json={"spec": ins, "x0": 4, "y0": 10, "x1": ox / 2, "y1": 60})
    assert r.status_code == 200, r.text
    c = r.json()["compartments"][0]
    P = Polygon(c["polygon"])
    sx, sy = lay["shift"]
    assert P.bounds[1] == pytest.approx(10 - sy, abs=0.3) and P.bounds[3] == pytest.approx(60 - sy, abs=0.3)
    assert P.area > 0.9 * box(*P.bounds).area * 0.5
    ins["compartments"] = r.json()["compartments"]
    assert not client.post(f"/api/inserts/{ins['id']}/layout", json=ins).json()["warnings"]
    # gerader waagrechter Schnitt in der Mitte
    mid = (P.bounds[1] + P.bounds[3]) / 2
    cut = client.post(f"/api/inserts/{ins['id']}/compartments/edit",
                      json={"spec": ins, "op": "cut", "indices": [0], "axis": "h", "at": mid}).json()
    lo, hi = sorted((Polygon(q["polygon"]) for q in cut["compartments"]), key=lambda g: g.bounds[1])
    assert lo.bounds[3] == pytest.approx(mid - 0.8, abs=0.4) and hi.bounds[1] == pytest.approx(mid + 0.8, abs=0.4)


def test_compartment_between_two_lines_is_straight():
    from shapely.geometry import Polygon, box
    demo = client.post("/api/objects/demo").json()
    ins = client.post("/api/inserts", json={"grid_x": 3, "grid_y": 5, "auto_grip": False, "comp_follow": False,
                                            "placements": [{"object_id": demo["id"], "rot_deg": 90}]}).json()
    lay = client.post(f"/api/inserts/{ins['id']}/layout", json=ins).json()
    ox, oy = lay["outer"]
    r = client.post(f"/api/inserts/{ins['id']}/compartments/band",
                    json={"spec": ins, "axis": "h", "a": 20, "b": 70, "x": 8, "y": 40})
    assert r.status_code == 200, r.text
    P = Polygon(r.json()["compartments"][0]["polygon"])
    sx, sy = lay["shift"]
    # gerades Rechteck (nur Eckradien), zwischen den Linien, links bis zum Rand, rechts bis vor die Tasche
    assert P.area > 0.97 * box(*P.bounds).area
    assert P.bounds[1] == pytest.approx(20 - sy, abs=0.2) and P.bounds[3] == pytest.approx(70 - sy, abs=0.2)
    ins["compartments"] = r.json()["compartments"]
    lay2 = client.post(f"/api/inserts/{ins['id']}/layout", json=ins).json()
    assert not lay2["warnings"]
    pocket = Polygon(lay2["pieces"][0]["polygons"][0]["exterior"])
    comp = Polygon(lay2["compartments"][0]["polygons"][0]["exterior"])
    assert 1.5 <= comp.distance(pocket) <= 4.0 or comp.bounds[2] < pocket.bounds[0]
