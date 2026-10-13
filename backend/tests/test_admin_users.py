"""Nutzerverwaltung: nur Admins, freischalten, sperren (wirft raus), letzter Admin bleibt, löschen mit Daten."""
import pytest
from sqlalchemy import select

from app import db
from app.models import User
from tests.test_ownership import make_user


@pytest.fixture
def people(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "0")
    admin, admin_id = make_user("chef@users.test", role="admin")
    user, user_id = make_user("nutzer@users.test")
    with db.session() as s:
        others = s.scalars(select(User).where(User.role == "admin", User.status == "active",
                                              User.email != "chef@users.test")).all()
        other_ids = [u.id for u in others]
        for u in others:
            u.status = "disabled"           # nur ein aktiver Admin für die Tests zum letzten Admin
        p = s.scalar(select(User).where(User.email == "wartet@users.test"))
        if p is None:
            p = User(email="wartet@users.test", status="pending")
            s.add(p)
        p.status = "pending"
        s.flush()
        pending_id = p.id
    yield {"admin": admin, "admin_id": admin_id, "user": user, "user_id": user_id, "pending_id": pending_id}
    with db.session() as s:
        for uid in other_ids:
            s.get(User, uid).status = "active"


def test_only_admins(people):
    assert people["user"].get("/api/admin/users").status_code == 403
    assert people["user"].put(f"/api/admin/users/{people['user_id']}", json={"role": "admin"}).status_code == 403
    assert people["user"].get("/api/admin/audit").status_code == 403


def test_list_pending_first(people):
    users = people["admin"].get("/api/admin/users").json()
    assert users[0]["status"] == "pending"
    assert {"chef@users.test", "nutzer@users.test", "wartet@users.test"} <= {u["email"] for u in users}


def test_approve(people):
    r = people["admin"].put(f"/api/admin/users/{people['pending_id']}", json={"status": "active"})
    assert r.status_code == 200 and r.json()["status"] == "active" and r.json()["approved_at"]
    log = people["admin"].get("/api/admin/audit").json()
    assert log[0]["action"] == "approve" and log[0]["actor"] == "chef@users.test"


def test_disable_logs_out_immediately(people):
    assert people["user"].get("/api/objects").status_code == 200
    people["admin"].put(f"/api/admin/users/{people['user_id']}", json={"status": "disabled"})
    assert people["user"].get("/api/objects").status_code == 401


def test_role_change_takes_effect(people):
    people["admin"].put(f"/api/admin/users/{people['user_id']}", json={"role": "admin"})
    assert people["user"].get("/api/admin/users").status_code == 200
    people["admin"].put(f"/api/admin/users/{people['user_id']}", json={"role": "user"})
    assert people["user"].get("/api/admin/users").status_code == 403


def test_last_admin_protected(people):
    a = people["admin"]
    assert a.put(f"/api/admin/users/{people['admin_id']}", json={"role": "user"}).status_code == 409
    assert a.put(f"/api/admin/users/{people['admin_id']}", json={"status": "disabled"}).status_code == 409
    assert a.delete(f"/api/admin/users/{people['admin_id']}").status_code == 409
    a.put(f"/api/admin/users/{people['user_id']}", json={"role": "admin"})
    assert a.put(f"/api/admin/users/{people['admin_id']}", json={"role": "user"}).status_code == 200


def test_delete_user_with_data(people):
    u = people["user"]
    oid = u.post("/api/objects", json={"name": "weg"}).json()["id"]
    iid = u.post("/api/inserts", json={"name": "weg"}).json()["id"]
    r = people["admin"].delete(f"/api/admin/users/{people['user_id']}")
    assert r.status_code == 200 and r.json()["removed"] == 2
    assert people["admin"].get(f"/api/objects/{oid}").status_code == 404
    assert people["admin"].get(f"/api/inserts/{iid}").status_code == 404
    assert u.get("/api/objects").status_code == 401
    assert people["admin"].delete(f"/api/admin/users/{people['user_id']}").status_code == 404
