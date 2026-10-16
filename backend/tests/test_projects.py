"""Projekte: Mustervorlage, automatische Einlagen, Anordnung in der Schublade, digitaler Klon."""
from fastapi.testclient import TestClient

from app.geometry.packing import Item, pack
from app.main import app

client = TestClient(app)


def test_pack_biggest_first_and_reports_left_out():
    free = {(i, j) for i in range(5) for j in range(3)} - {(4, 2)}       # Ecke fehlt
    placed, left = pack(5, 3, free, [Item("a", 3, 2), Item("b", 2, 3), Item("c", 2, 2), Item("d", 1, 1)])
    assert "a" in placed and "b" in placed
    cells = []
    for k, (ix, iy, rot) in placed.items():
        gx, gy = {"a": (3, 2), "b": (2, 3), "c": (2, 2), "d": (1, 1)}[k]
        w, h = (gx, gy) if rot == 0 else (gy, gx)
        cells += [(i, j) for i in range(ix, ix + w) for j in range(iy, iy + h)]
    assert len(cells) == len(set(cells)) and set(cells) <= free           # nichts überlappt, nichts auf der Lücke
    assert set(placed) | set(left) == {"a", "b", "c", "d"} and left        # c passt nicht mehr


def _project():
    p = client.post("/api/projects", json={"name": "Schreibtisch oben", "drawer_x": 400, "drawer_y": 300}).json()
    demo = client.post("/api/objects/demo").json()
    client.post(f"/api/projects/{p['id']}/assign", json={"kind": "object", "id": demo["id"]})
    demo2 = client.post("/api/objects/demo").json()
    client.post(f"/api/projects/{p['id']}/assign", json={"kind": "object", "id": demo2["id"]})
    return p, [demo, demo2]


def test_generate_arrange_clone_and_template():
    p, demos = _project()
    pid = p["id"]
    r = client.post(f"/api/projects/{pid}/generate", json={}).json()
    assert len(r["created"]) == 2 and not r["left_out"]
    ins = [client.get(f"/api/inserts/{i}").json() for i in r["created"]]
    assert all(i["project_id"] == pid and i["grip_recesses"] for i in ins)   # Greifmulde schon bearbeitbar
    c = client.get(f"/api/projects/{pid}/clone").json()
    assert len(c["inserts"]) == 2 and all(i["placed"] for i in c["inserts"])
    assert c["heights_equal"] and not c["warnings"]
    assert c["inserts"][0]["tools"][0]["contour"] and c["inserts"][0]["layout"]["pieces"]

    # Vorlage ändern: gilt für alle, außer für bewusst überschriebene Felder
    a = ins[0]
    a["overrides"] = ["clearance_xy"]
    a["clearance_xy"] = 1.0
    client.put(f"/api/inserts/{a['id']}", json=a)
    proj = client.get(f"/api/projects/{pid}").json()
    proj["template"]["clearance_xy"] = 3.0
    proj["template"]["height_mm"] = 40.0
    client.put(f"/api/projects/{pid}", json=proj)
    a2 = client.get(f"/api/inserts/{a['id']}").json()
    b2 = client.get(f"/api/inserts/{ins[1]['id']}").json()
    assert a2["clearance_xy"] == 1.0 and b2["clearance_xy"] == 3.0
    assert a2["height_mm"] == 40.0 and b2["height_mm"] == 40.0
    c = client.get(f"/api/projects/{pid}/clone").json()
    assert all(abs(i["total_height"] - 40.0) < 0.01 for i in c["inserts"])


def test_place_checks_space_and_delete_keeps_inserts():
    p, _ = _project()
    pid = p["id"]
    r = client.post(f"/api/projects/{pid}/generate", json={}).json()
    a, b = r["created"]
    proj = client.get(f"/api/projects/{pid}").json()
    qa = next(q for q in proj["placements"] if q["insert_id"] == a)
    # b genau auf a setzen: abgelehnt
    bad = client.post(f"/api/projects/{pid}/place", json={"insert_id": b, "placement": {**qa, "insert_id": b}})
    assert bad.status_code == 409
    # b herausnehmen, dann ist es nicht mehr platziert
    client.post(f"/api/projects/{pid}/place", json={"insert_id": b, "placement": None})
    c = client.get(f"/api/projects/{pid}/clone").json()
    assert next(i for i in c["inserts"] if i["id"] == b)["placed"] is None
    # Zelle unter a abwählen -> Warnung im Klon
    proj = client.get(f"/api/projects/{pid}").json()
    proj["drawer"]["disabled"] = [[qa["ix"], qa["iy"]]]
    client.put(f"/api/projects/{pid}", json=proj)
    assert any("abgewählten" in w for w in client.get(f"/api/projects/{pid}/clone").json()["warnings"])
    # Löschen archiviert nur: nicht mehr in der Liste, Daten bleiben, wiederherstellbar
    assert client.delete(f"/api/projects/{pid}").json()["archived"]
    assert pid not in [q["id"] for q in client.get("/api/projects").json()]
    assert pid in [q["id"] for q in client.get("/api/projects?archived=true").json()]
    assert client.get(f"/api/inserts/{a}").json()["project_id"] == pid
    assert client.get(f"/api/projects/{pid}").json()["archived"]
    client.post(f"/api/projects/{pid}/restore")
    assert pid in [q["id"] for q in client.get("/api/projects").json()]


def test_insert_created_in_project_uses_template():
    p, demos = _project()
    proj = client.get(f"/api/projects/{p['id']}").json()
    proj["template"]["sink"] = 0.8
    proj["template"]["color_hex"]["pocket"] = "#cc0000"
    client.put(f"/api/projects/{p['id']}", json=proj)
    i = client.post("/api/inserts", json={"name": "X", "project_id": p["id"],
                                         "placements": [{"object_id": demos[0]["id"]}]}).json()
    assert i["sink"] == 0.8 and i["color_hex"]["pocket"] == "#cc0000"


def test_template_change_keeps_single_grip_and_generate_is_idempotent():
    p, demos = _project()
    pid = p["id"]
    r = client.post(f"/api/projects/{pid}/generate", json={}).json()
    again = client.post(f"/api/projects/{pid}/generate", json={"object_ids": [demos[0]["id"]]}).json()
    assert again["created"] == [] and again["already"]
    proj = client.get(f"/api/projects/{pid}").json()
    proj["template"]["grip_width"] = 24.0
    client.put(f"/api/projects/{pid}", json=proj)
    ins = client.get(f"/api/inserts/{r['created'][0]}").json()
    assert ins["auto_grip"] is False and len(ins["grip_recesses"]) == 1
    lay = client.post(f"/api/inserts/{ins['id']}/layout", json=ins).json()
    assert len(lay["grips"]) == 1


def test_place_unfinished_insert_gives_422():
    p, _ = _project()
    raw = client.post("/api/objects", json={"name": "unfertig"}).json()
    i = client.post("/api/inserts", json={"name": "U", "project_id": p["id"], "placements": [{"object_id": raw["id"]}]}).json()
    r = client.post(f"/api/projects/{p['id']}/place", json={"insert_id": i["id"], "placement": {"insert_id": i["id"], "ix": 0, "iy": 0, "rot": 0}})
    assert r.status_code == 422
    a = client.post(f"/api/projects/{p['id']}/arrange", json={"mode": "all"}).json()
    assert i["id"] in a["unfinished"]


def test_forced_place_marks_overlap():
    p, _ = _project()
    pid = p["id"]
    a, b = client.post(f"/api/projects/{pid}/generate", json={}).json()["created"]
    qa = next(q for q in client.get(f"/api/projects/{pid}").json()["placements"] if q["insert_id"] == a)
    r = client.post(f"/api/projects/{pid}/place", json={"insert_id": b, "force": True,
                                                       "placement": {**qa, "insert_id": b, "rot": 90 - qa["rot"]}}).json()
    assert r["ok"] and r["fits"] is False
    c = client.get(f"/api/projects/{pid}/clone").json()
    over = [k for k in c["conflicts"] if k["kind"] == "overlap"]
    assert over and all(set(k["ids"]) == {a, b} for k in over)
    assert any("überlappt" in w for w in c["warnings"])
