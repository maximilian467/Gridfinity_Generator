"""Eigene Daten je Nutzer: Nutzer B kommt mit keiner Route an die Daten von Nutzer A (IDOR)."""
import json
import secrets
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app import auth, config, db, storage
from app.main import app
from app.models import Session, User, utcnow

SPEC = {"name": "x", "grid_x": 3, "grid_y": 2}


def make_user(email: str, role: str = "user") -> tuple[TestClient, int]:
    with db.session() as s:
        s.execute(delete(User).where(User.email == email))
        u = User(email=email, role=role, status="active")
        s.add(u)
        s.flush()
        tok = secrets.token_urlsafe(32)
        s.add(Session(token_hash=auth._hash(tok), user_id=u.id, expires_at=utcnow() + timedelta(days=1)))
        uid = u.id
    c = TestClient(app)
    c.cookies.set(auth.COOKIE, tok)
    return c, uid


@pytest.fixture
def world(monkeypatch):
    """A besitzt ein Objekt, eine Einlage (mit Ausgabedatei) und eine Basisplatte; B ist ein zweiter Nutzer."""
    monkeypatch.setenv("AUTH_DISABLED", "0")
    a, a_id = make_user("a@owner.test")
    b, _ = make_user("b@owner.test")
    admin, _ = make_user("chef@owner.test", role="admin")
    obj = a.post("/api/objects/demo").json()
    ins = a.post("/api/inserts", json={**SPEC, "placements": [{"object_id": obj["id"]}]}).json()
    (storage.object_dir(obj["id"]) / "top_preview.jpg").write_bytes(b"jpg")
    out = storage.insert_dir(ins["id"]) / "out" / "job1"
    out.mkdir(parents=True)
    (out / "insert.3mf").write_bytes(b"3mf")
    jid = "bpjob" + secrets.token_hex(3)
    bp = config.DATA_DIR / "baseplates" / jid
    bp.mkdir(parents=True)
    (bp / "job.json").write_text(json.dumps({"id": jid, "kind": "baseplate", "status": "done", "progress": 1,
                                             "outputs": {}, "checks": {}, "warnings": [], "error": None,
                                             "owner_id": a_id}))
    (bp / "plate.stl").write_bytes(b"stl")
    return {"a": a, "b": b, "admin": admin, "a_id": a_id, "obj": obj, "ins": ins, "jid": jid}


def foreign_requests(w):
    o, i, spec = w["obj"]["id"], w["ins"]["id"], w["ins"]
    jpg = {"file": ("x.jpg", b"x", "image/jpeg")}
    return [
        ("GET", f"/api/objects/{o}", {}), ("PUT", f"/api/objects/{o}", {"json": {"name": "weg"}}),
        ("DELETE", f"/api/objects/{o}", {}), ("POST", f"/api/objects/{o}/photos/top", {"files": jpg}),
        ("PUT", f"/api/objects/{o}/photos/top/corners", {"json": {"corners_px": [[0, 0], [1, 0], [1, 1], [0, 1]]}}),
        ("POST", f"/api/objects/{o}/photos/top/segment", {"json": {}}),
        ("PUT", f"/api/objects/{o}/photos/top/mask", {"files": {"file": ("m.png", b"x", "image/png")}}),
        ("PUT", f"/api/objects/{o}/levels", {"json": {"levels": [[0, 10, 0]]}}),
        ("POST", f"/api/objects/{o}/profile", {"json": {}}),
        ("GET", f"/api/inserts/{i}", {}), ("PUT", f"/api/inserts/{i}", {"json": spec}),
        ("DELETE", f"/api/inserts/{i}", {}), ("POST", f"/api/inserts/{i}/duplicate", {}),
        ("POST", f"/api/inserts/{i}/layout", {}), ("POST", f"/api/inserts/{i}/layout", {"json": spec}),
        ("POST", f"/api/inserts/{i}/auto-compartments", {"json": spec}),
        ("POST", f"/api/inserts/{i}/compartments/edit", {"json": {"spec": spec, "op": "split", "indices": [0]}}),
        ("POST", f"/api/inserts/{i}/compartments/at", {"json": {"spec": spec, "x": 1, "y": 1}}),
        ("POST", f"/api/inserts/{i}/compartments/rect", {"json": {"spec": spec, "x0": 0, "y0": 0, "x1": 9, "y1": 9}}),
        ("POST", f"/api/inserts/{i}/build", {}),
        ("GET", f"/api/files/objects/{o}/top_preview.jpg", {}),
        ("GET", f"/api/files/inserts/{i}/out/job1/insert.3mf", {}),
        ("GET", f"/api/files/baseplates/{w['jid']}/plate.stl", {}),
        ("GET", f"/api/jobs/{w['jid']}", {}),
    ]


def test_other_user_gets_404_everywhere(world):
    for method, url, kw in foreign_requests(world):
        r = world["b"].request(method, url, **kw)
        assert r.status_code == 404, (method, url, r.status_code, r.text[:200])
    # nichts wurde verändert oder gelöscht
    a = world["a"]
    assert a.get(f"/api/objects/{world['obj']['id']}").json()["name"] == "Spitzzange (Demo)"
    assert a.get(f"/api/inserts/{world['ins']['id']}").status_code == 200
    assert a.get(f"/api/files/objects/{world['obj']['id']}/top_preview.jpg").content == b"jpg"


def test_owner_and_admin_have_access(world):
    for c in (world["a"], world["admin"]):
        assert c.get(f"/api/objects/{world['obj']['id']}").status_code == 200
        assert c.get(f"/api/files/inserts/{world['ins']['id']}/out/job1/insert.3mf").content == b"3mf"
        assert c.get(f"/api/files/baseplates/{world['jid']}/plate.stl").status_code == 200
        assert c.get(f"/api/jobs/{world['jid']}").status_code == 200
    assert world["a"].post(f"/api/inserts/{world['ins']['id']}/layout").status_code == 200


def test_lists_are_private(world):
    def ids(r):
        return {x["id"] for x in r.json()}
    assert world["obj"]["id"] in ids(world["a"].get("/api/objects"))
    assert world["obj"]["id"] not in ids(world["b"].get("/api/objects"))
    assert world["ins"]["id"] not in ids(world["b"].get("/api/inserts"))
    assert world["obj"]["id"] not in ids(world["b"].get("/api/objects?all=true"))     # nur Admins
    assert world["obj"]["id"] not in ids(world["admin"].get("/api/objects"))
    assert world["obj"]["id"] in ids(world["admin"].get("/api/objects?all=true"))
    assert world["ins"]["id"] in ids(world["admin"].get("/api/inserts?all=true"))


def test_cannot_place_foreign_object(world):
    b = world["b"]
    pl = {"placements": [{"object_id": world["obj"]["id"]}]}
    assert b.post("/api/inserts", json={**SPEC, **pl}).status_code == 404
    own = b.post("/api/inserts", json=SPEC).json()
    assert b.put(f"/api/inserts/{own['id']}", json={**own, **pl}).status_code == 404
    assert b.post(f"/api/inserts/{own['id']}/layout", json={**own, **pl}).status_code == 404
    # gelöschte (nicht vorhandene) Objekte stören das Speichern nicht
    assert b.put(f"/api/inserts/{own['id']}", json={**own, "placements": [{"object_id": "fehlt123"}]}).status_code == 200


def test_owner_id_cannot_be_spoofed(world):
    b = world["b"]
    ins = b.post("/api/inserts", json={**SPEC, "owner_id": world["a_id"]}).json()
    assert ins["owner_id"] != world["a_id"]
    r = b.put(f"/api/inserts/{ins['id']}", json={**ins, "owner_id": world["a_id"]})
    assert r.json()["owner_id"] == ins["owner_id"]
    assert ins["id"] not in {x["id"] for x in world["a"].get("/api/inserts").json()}


def test_legacy_data_only_for_admins(world):
    legacy = storage.ObjectSpec(id="legacy" + secrets.token_hex(2), name="alt")
    storage.save_object(legacy)
    assert world["a"].get(f"/api/objects/{legacy.id}").status_code == 404
    assert world["admin"].get(f"/api/objects/{legacy.id}").status_code == 200
    assert legacy.id in {x["id"] for x in world["admin"].get("/api/objects").json()}


def test_item_limit(world, monkeypatch):
    monkeypatch.setattr(storage, "MAX_ITEMS", 1)
    assert world["a"].post("/api/objects", json={"name": "zu viel"}).status_code == 409


def test_job_limit_per_user(world, monkeypatch):
    from app import jobs
    monkeypatch.setitem(jobs._jobs, "laeuft1", {"status": "running", "owner_id": world["a_id"]})
    r = world["a"].post("/api/baseplates/build", json={"drawer_x": 100, "drawer_y": 100})
    assert r.status_code == 429 and "vorige" in r.json()["detail"]


def test_stale_running_job_reported_as_error(world):
    bp = config.DATA_DIR / "baseplates" / world["jid"]
    j = json.loads((bp / "job.json").read_text())
    j["status"] = "running"
    (bp / "job.json").write_text(json.dumps(j))
    assert world["a"].get(f"/api/jobs/{world['jid']}").json()["status"] == "error"
