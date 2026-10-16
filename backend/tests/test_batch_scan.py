"""Stapel-Scan im Projekt: viele Fotopaare hochladen, automatisch auswerten, Einlagen erzeugen und anordnen."""
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.synth import IMG_H, IMG_W, camera, render, rot_rect
from tests.test_api import jpg

client = TestClient(app)


def _pair(pid: str, top, side, name: str = "") -> dict:
    r = client.post(f"/api/projects/{pid}/scan-pair", data={"name": name},
                    files={"top": ("top.jpg", jpg(top), "image/jpeg"), "side": ("side.jpg", jpg(side), "image/jpeg")})
    assert r.status_code == 200, r.text
    return r.json()


def test_batch_scan_creates_arranged_inserts_and_keeps_failures_unfinished():
    L, W, T = 150.0, 38.0, 14.0
    top = render(rot_rect(140, 110, L, W, 25), T, camera(offset=(-10, 5)), seed=1)
    side = render(rot_rect(160, 100, L, T, -15), W, camera(offset=(5, -10)), seed=2)
    no_paper = np.random.default_rng(4).integers(0, 255, (IMG_H // 2, IMG_W // 2, 3)).astype(np.uint8)  # kein A4-Blatt
    empty = render(rot_rect(140, 110, 3, 3, 0), 1, camera(), seed=3)                      # Blatt ohne Werkzeug

    pid = client.post("/api/projects", json={"name": "Stapel", "drawer_x": 400, "drawer_y": 300}).json()["id"]
    good = _pair(pid, top, side, "Balken")
    bad_a4 = _pair(pid, top, no_paper)
    bad_tool = _pair(pid, empty, side, "Leer")
    assert bad_a4["name"] == "Werkzeug 2"                                                 # Name automatisch
    objs = {o["id"]: o for o in client.get("/api/objects").json()}
    assert all(objs[x["id"]]["project_id"] == pid for x in (good, bad_a4, bad_tool))
    assert objs[good["id"]]["photos"]["top"]["preview_url"]

    # Prüfungen vor dem Start
    other = client.post("/api/objects", json={"name": "fremd"}).json()
    assert client.post(f"/api/projects/{pid}/batch-scan", json={"object_ids": [other["id"]]}).status_code == 422
    r = client.post(f"/api/projects/{pid}/scan-pair", files={"top": ("a.jpg", b"kein bild", "image/jpeg"),
                                                            "side": ("b.jpg", jpg(side), "image/jpeg")})
    assert r.status_code == 422 and "Draufsicht" in r.json()["detail"]
    assert len([o for o in client.get("/api/objects").json() if o["project_id"] == pid]) == 3   # nichts übrig

    ids = [good["id"], bad_a4["id"], bad_tool["id"]]
    job_id = client.post(f"/api/projects/{pid}/batch-scan", json={"object_ids": ids}).json()["job_id"]
    seen_running = False
    t0 = time.time()
    while True:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["items"] and any(it["status"] == "running" for it in j["items"]):
            seen_running = True
        if j["status"] != "running":
            break
        assert time.time() - t0 < 400
        time.sleep(0.5)
    assert j["status"] == "done", j["error"]
    assert seen_running
    items = {it["id"]: it for it in j["items"]}
    assert items[good["id"]]["status"] == "done" and not items[good["id"]]["warnings"]
    assert items[good["id"]]["length_mm"] == pytest.approx(L, abs=0.6)
    assert items[bad_a4["id"]]["status"] == "error" and "A4" in items[bad_a4["id"]]["error"]
    assert items[bad_tool["id"]]["status"] == "error" and "Kein Werkzeug" in items[bad_tool["id"]]["error"]
    assert j["checks"]["done"] == 1 and j["checks"]["failed"] == 2
    assert len(j["checks"]["generate"]["created"]) == 1 and not j["checks"]["generate"]["left_out"]

    # fertiges Werkzeug: Profil wie im Einzel-Scan; Einlage nach Vorlage liegt in der Schublade
    o = client.get(f"/api/objects/{good['id']}").json()
    assert o["width_mm"] == pytest.approx(W, abs=0.5)
    assert max(o["profile"]["top"][10:-10]) == pytest.approx(T, abs=0.6)
    c = client.get(f"/api/projects/{pid}/clone").json()
    assert len(c["inserts"]) == 1 and c["inserts"][0]["placed"]
    assert c["inserts"][0]["tools"][0]["object_id"] == good["id"]

    # fehlgeschlagene Werkzeuge bleiben unfertig, aber im Scan-Assistenten bearbeitbar
    b = client.get(f"/api/objects/{bad_a4['id']}").json()
    assert b["profile"] is None and b["photos"]["top"]["rectified_url"] and not b["photos"]["side"]["corners_found"]
    assert len(b["photos"]["side"]["corners_px"]) == 4 and b["photos"]["side"]["rectified_url"]
    e = client.get(f"/api/objects/{bad_tool['id']}").json()
    assert e["profile"] is None and e["photos"]["top"]["corners_found"]
    # Nacharbeit im Assistenten: Ecken der Seitenansicht setzen, freistellen, Profil -> fertig
    side_ok = client.post(f"/api/objects/{bad_a4['id']}/photos/side",
                          files={"file": ("s.jpg", jpg(side), "image/jpeg")}).json()
    assert side_ok["corners_found"]
    for view in ("top", "side"):
        assert client.post(f"/api/objects/{bad_a4['id']}/photos/{view}/segment", json={}).status_code == 200
    assert client.post(f"/api/objects/{bad_a4['id']}/profile", json={}).json()["profile"]
