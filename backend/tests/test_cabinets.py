"""Schränke: ein Schrank fasst Schubladen zusammen; wer am Schrank beteiligt ist, ist an allen
seinen Schubladen beteiligt. A besitzt Schrank S mit Schublade D, B ist Mitglied von S, C ist fremd."""
import secrets

import pytest

from .test_ownership import SPEC, make_user


@pytest.fixture
def shop(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "0")
    tag = secrets.token_hex(3)
    a, _ = make_user(f"a{tag}@schrank.test")
    b, b_id = make_user(f"b{tag}@schrank.test")
    c, _ = make_user(f"c{tag}@schrank.test")
    s = a.post("/api/projects", json={"name": "Werkstattschrank", "kind": "cabinet"}).json()
    d = a.post("/api/projects", json={"name": "Lade 1", "drawer_x": 400, "drawer_y": 300, "cabinet_id": s["id"]}).json()
    tool = a.post("/api/objects/demo").json()
    a.post(f"/api/projects/{d['id']}/assign", json={"kind": "object", "id": tool["id"]})
    ins = a.post("/api/inserts", json={**SPEC, "project_id": d["id"], "placements": [{"object_id": tool["id"]}]}).json()
    r = a.post(f"/api/projects/{s['id']}/members", json={"email": f"b{tag}@schrank.test"})
    assert r.status_code == 200, r.text
    return {"a": a, "b": b, "c": c, "b_id": b_id, "s": s, "d": d, "tool": tool, "ins": ins}


def test_cabinet_and_drawer_created(shop):
    s, d = shop["s"], shop["d"]
    assert s["kind"] == "cabinet" and d["kind"] == "drawer" and d["cabinet_id"] == s["id"]


def test_cabinet_member_reaches_every_drawer(shop):
    b, d = shop["b"], shop["d"]
    ids = {p["id"]: p for p in b.get("/api/projects").json()}
    assert shop["s"]["id"] in ids and d["id"] in ids
    assert ids[d["id"]]["access"]["role"] == "member"
    assert b.get(f"/api/projects/{d['id']}").status_code == 200
    assert b.get(f"/api/inserts/{shop['ins']['id']}").status_code == 200
    assert b.get(f"/api/objects/{shop['tool']['id']}").status_code == 200
    d2 = b.post("/api/projects", json={"name": "Lade 2", "cabinet_id": shop["s"]["id"]})    # Mitglied legt Schublade an
    assert d2.status_code == 200 and d2.json()["cabinet_id"] == shop["s"]["id"]
    assert shop["a"].get(f"/api/projects/{d2.json()['id']}").status_code == 200           # Schrankbesitzer sieht sie


def test_stranger_sees_nothing(shop):
    c = shop["c"]
    assert c.get(f"/api/projects/{shop['d']['id']}").status_code == 404
    assert c.get(f"/api/inserts/{shop['ins']['id']}").status_code == 404
    assert c.post("/api/projects", json={"name": "x", "cabinet_id": shop["s"]["id"]}).status_code == 404


def test_removing_cabinet_member_ends_drawer_access(shop):
    a, b, d = shop["a"], shop["b"], shop["d"]
    assert a.delete(f"/api/projects/{shop['s']['id']}/members/{shop['b_id']}").status_code == 200
    assert b.get(f"/api/projects/{d['id']}").status_code == 404


def test_move_drawer_only_into_own_cabinet(shop):
    a, b, d = shop["a"], shop["b"], shop["d"]
    other = b.post("/api/projects", json={"name": "B-Schrank", "kind": "cabinet"}).json()
    mine = b.post("/api/projects", json={"name": "B-Lade"}).json()
    # B verwaltet D nicht (nur Mitglied über den Schrank)
    assert b.post(f"/api/projects/{d['id']}/cabinet", json={"cabinet_id": other["id"]}).status_code == 403
    # B darf die eigene Schublade nicht in A's Schrank stellen (A's Leute bekämen Zugriff, ohne dass A gefragt wurde)
    assert b.post(f"/api/projects/{mine['id']}/cabinet", json={"cabinet_id": shop["s"]["id"]}).status_code == 403
    assert b.post(f"/api/projects/{mine['id']}/cabinet", json={"cabinet_id": other["id"]}).json()["cabinet_id"] == other["id"]
    r = a.post(f"/api/projects/{d['id']}/cabinet", json={"cabinet_id": None})
    assert r.status_code == 200 and r.json()["cabinet_id"] is None
    assert b.get(f"/api/projects/{d['id']}").status_code == 404                           # nicht mehr im Schrank


def test_put_cannot_change_kind_or_cabinet(shop):
    a, d = shop["a"], shop["d"]
    r = a.put(f"/api/projects/{d['id']}", json={**d, "kind": "cabinet", "cabinet_id": None})
    assert r.json()["kind"] == "drawer" and r.json()["cabinet_id"] == shop["s"]["id"]


def test_cabinet_owner_manages_member_drawer(shop):
    """Schublade eines Mitglieds im Schrank: der Schrankbesitzer verwaltet sie mit (Mitglieder, Archiv)."""
    a, b = shop["a"], shop["b"]
    d2 = b.post("/api/projects", json={"name": "Lade B", "cabinet_id": shop["s"]["id"]}).json()
    assert a.delete(f"/api/projects/{d2['id']}").status_code == 200


def test_no_items_directly_in_cabinet(shop):
    a = shop["a"]
    tool = a.post("/api/objects/demo").json()
    r = a.post(f"/api/projects/{shop['s']['id']}/assign", json={"kind": "object", "id": tool["id"]})
    assert r.status_code == 422
