"""Sicherheitstests: Login, Pfad-Traversal, Datei-Auslieferung, Uploads, Wertebereiche, Header."""
import io

import pytest
from fastapi.testclient import TestClient

from app import auth, config
from app.main import app


@pytest.fixture
def secured(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "0")
    monkeypatch.setenv("APP_USER", "admin@admin.com")
    monkeypatch.setenv("APP_PASSWORD", "admin")
    auth._fails.clear()
    return TestClient(app)


@pytest.fixture
def open_client():
    return TestClient(app)


def login(c):
    return c.post("/api/auth/login", json={"email": "admin@admin.com", "password": "admin"})


# ---- Login -----------------------------------------------------------------------------
def test_api_requires_login(secured):
    assert secured.get("/api/objects").status_code == 401
    assert secured.get("/api/files/objects/x/top_preview.jpg").status_code == 401
    assert secured.get("/api/health").status_code == 200
    assert secured.get("/api/auth/me").status_code == 401


def test_login_flow_and_cookie_flags(secured):
    assert secured.post("/api/auth/login", json={"email": "admin@admin.com", "password": "falsch"}).status_code == 401
    r = login(secured)
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert secured.get("/api/objects").status_code == 200
    assert secured.get("/api/auth/me").json()["user"] == "admin@admin.com"
    secured.post("/api/auth/logout")
    secured.cookies.clear()
    assert secured.get("/api/objects").status_code == 401


def test_email_case_insensitive(secured):
    r = secured.post("/api/auth/login", json={"email": " Admin@Admin.com ", "password": "admin"})
    assert r.status_code == 200


def test_tampered_or_foreign_cookie_rejected(secured):
    tok = auth.make_token("admin@admin.com")
    payload, sig = tok.rsplit(".", 1)
    secured.cookies.set(auth.COOKIE, payload + "." + ("0" * len(sig)))
    assert secured.get("/api/objects").status_code == 401
    secured.cookies.set(auth.COOKIE, auth.make_token("someone@else.com"))
    assert secured.get("/api/objects").status_code == 401
    secured.cookies.set(auth.COOKIE, auth.make_token("admin@admin.com", now=0))   # abgelaufen
    assert secured.get("/api/objects").status_code == 401


def test_bruteforce_limited(secured, monkeypatch):
    monkeypatch.setattr(auth.time, "sleep", lambda s: None)
    for _ in range(auth.LIMIT):
        secured.post("/api/auth/login", json={"email": "admin@admin.com", "password": "x"})
    assert login(secured).status_code == 429          # auch das richtige Passwort wird jetzt geblockt


# ---- Pfade / Dateien -------------------------------------------------------------------
def test_path_traversal_in_ids(open_client):
    victim = config.DATA_DIR.parent / "gf_victim_dir"
    victim.mkdir(exist_ok=True)
    (victim / "keep.txt").write_text("x")
    for bad in ("..%2F..%2Fgf_victim_dir", "..", "a.b", "x%5C..%5C..", "%2E%2E"):
        # der Client normalisiert '../' teils schon; dann landet die Anfrage bei der Startseite (kein JSON)
        for r in (open_client.delete(f"/api/objects/{bad}"), open_client.delete(f"/api/inserts/{bad}"),
                  open_client.get(f"/api/objects/{bad}")):
            assert r.status_code in (404, 405) or not r.headers["content-type"].startswith("application/json")
    assert (victim / "keep.txt").exists()
    r = open_client.post("/api/inserts", json={"placements": [{"object_id": "../../etc"}]})
    assert r.status_code == 422


def test_files_endpoint_whitelist(open_client):
    (config.DATA_DIR / ".secret").write_text("geheim")
    o = open_client.post("/api/objects/demo").json()
    for bad in (".secret", "objects/%s/object.json" % o["id"], "../pyproject.toml", "models/sam2.1_b.pt",
                "objects/../.secret"):
        r = open_client.get(f"/api/files/{bad}")
        assert r.status_code == 404 or r.headers["content-type"].startswith("text/html"), bad
        assert b"geheim" not in r.content and b"[project]" not in r.content and b"contour_mm" not in r.content


def test_upload_rules(open_client):
    oid = open_client.post("/api/objects", json={"name": "x"}).json()["id"]
    r = open_client.post(f"/api/objects/{oid}/photos/top", files={"file": ("evil.html", b"<script>alert(1)</script>", "text/html")})
    assert r.status_code == 415
    r = open_client.post(f"/api/objects/{oid}/photos/top", files={"file": ("x.jpg", b"kein bild", "image/jpeg")})
    assert r.status_code == 422
    big = io.BytesIO(b"\0" * (40 * 1024 * 1024 + 10))
    r = open_client.post(f"/api/objects/{oid}/photos/top", files={"file": ("x.jpg", big, "image/jpeg")})
    assert r.status_code == 413
    assert open_client.post(f"/api/objects/{oid}/photos/front", files={"file": ("x.jpg", b"x", "image/jpeg")}).status_code == 422


def test_decompression_bomb_rejected(open_client):
    from PIL import Image
    oid = open_client.post("/api/objects", json={"name": "bomb"}).json()["id"]
    buf = io.BytesIO()
    Image.new("L", (12000, 12000)).save(buf, "PNG")      # 144 MPx, wenige KB
    r = open_client.post(f"/api/objects/{oid}/photos/top", files={"file": ("b.png", buf.getvalue(), "image/png")})
    assert r.status_code == 422


def test_value_ranges(open_client):
    assert open_client.post("/api/inserts", json={"grid_x": 1000}).status_code == 422
    assert open_client.post("/api/inserts", json={"placements": [{"object_id": "a"}] * 50}).status_code == 422
    assert open_client.post("/api/baseplates/build", json={"drawer_x": 1e9, "drawer_y": 100}).status_code == 422
    assert open_client.post("/api/objects", json={"name": "x" * 500}).status_code == 422


def test_security_headers(open_client):
    r = open_client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"


def test_job_id_not_glob(open_client):
    assert open_client.get("/api/jobs/*").status_code == 404
    assert open_client.get("/api/jobs/%2A%2A").status_code == 404


def test_ids_rejected_directly():
    from app import storage
    for bad in ("..", "../x", "a/b", "a\b", "", "x" * 41, "a.b"):
        with pytest.raises(KeyError):
            storage.object_dir(bad)
        with pytest.raises(KeyError):
            storage.insert_dir(bad)
