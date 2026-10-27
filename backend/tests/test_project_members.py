"""Gemeinsame Projekte: Mitglieder bearbeiten alles im Projekt, sonst bleibt alles privat.

A besitzt das Projekt P, B ist Mitglied, C ist fremd. Geprüft wird, was B darf (Projekt, Einlagen,
Werkzeuge, Dateien), was nicht (Mitglieder verwalten, archivieren, fremdes löschen oder in andere
Projekte verschieben, fremde Werkzeuge hineinreichen) und dass C nirgends hinkommt.
"""
import secrets

import pytest
from sqlalchemy import update

from app import auth, db, storage
from app.models import User

from .test_ownership import SPEC, make_user


def _ids(r):
    assert r.status_code == 200, r.text
    return {x["id"] for x in r.json()}


@pytest.fixture
def team(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "0")
    tag = secrets.token_hex(3)
    a, a_id = make_user(f"a{tag}@team.test")
    b, b_id = make_user(f"b{tag}@team.test")
    c, c_id = make_user(f"c{tag}@team.test")
    admin, _ = make_user(f"chef{tag}@team.test", role="admin")
    p = a.post("/api/projects", json={"name": "Werkbank", "drawer_x": 300, "drawer_y": 200}).json()
    tool = a.post("/api/objects/demo").json()                      # Werkzeug im Projekt
    a.post(f"/api/projects/{p['id']}/assign", json={"kind": "object", "id": tool["id"]})
    lib = a.post("/api/objects/demo").json()                       # aus A's Bibliothek, steckt in einer Projekt-Einlage
    private = a.post("/api/objects/demo").json()                   # bleibt privat
    ins = a.post("/api/inserts", json={**SPEC, "project_id": p["id"], "placements": [{"object_id": tool["id"]}]}).json()
    ins_lib = a.post("/api/inserts", json={**SPEC, "project_id": p["id"], "placements": [{"object_id": lib["id"]}]}).json()
    priv_ins = a.post("/api/inserts", json={**SPEC, "placements": [{"object_id": private["id"]}]}).json()
    (storage.object_dir(tool["id"]) / "top_preview.jpg").write_bytes(b"jpg")
    (storage.object_dir(private["id"]) / "top_preview.jpg").write_bytes(b"jpg")
    out = storage.insert_dir(ins["id"]) / "out" / "job1"
    out.mkdir(parents=True)
    (out / "insert.3mf").write_bytes(b"3mf")
    return {"a": a, "b": b, "c": c, "admin": admin, "a_id": a_id, "b_id": b_id, "c_id": c_id, "tag": tag,
            "p": p, "tool": tool, "lib": lib, "private": private, "ins": ins, "ins_lib": ins_lib, "priv_ins": priv_ins,
            "b_mail": f"b{tag}@team.test", "c_mail": f"c{tag}@team.test"}


def join(t, who="b"):
    r = t["a"].post(f"/api/projects/{t['p']['id']}/members", json={"email": t[f"{who}_mail"]})
    assert r.status_code == 200, r.text
    return r.json()


def project_requests(t):
    """Alles, was ein Beteiligter am Projekt P tun kann (ohne Löschen)."""
    pid, i, o = t["p"]["id"], t["ins"]["id"], t["tool"]["id"]
    return [
        ("GET", f"/api/projects/{pid}", {}), ("PUT", f"/api/projects/{pid}", {"json": t["p"]}),
        ("GET", f"/api/projects/{pid}/members", {}), ("GET", f"/api/projects/{pid}/clone", {}),
        ("POST", f"/api/projects/{pid}/arrange", {"json": {"mode": "missing"}}),
        ("POST", f"/api/projects/{pid}/generate", {"json": {"arrange": False}}),
        ("POST", f"/api/projects/{pid}/place", {"json": {"insert_id": i, "placement": None}}),
        ("GET", f"/api/inserts/{i}", {}), ("PUT", f"/api/inserts/{i}", {"json": t["ins"]}),
        ("POST", f"/api/inserts/{i}/layout", {}), ("POST", f"/api/inserts/{i}/duplicate", {}),
        ("GET", f"/api/objects/{o}", {}), ("PUT", f"/api/objects/{o}", {"json": {"name": "Spitzzange (Demo)"}}),
        ("GET", f"/api/objects/{t['lib']['id']}", {}),
        ("GET", f"/api/files/objects/{o}/top_preview.jpg", {}),
        ("GET", f"/api/files/inserts/{i}/out/job1/insert.3mf", {}),
    ]


# ---- ohne Mitgliedschaft: nichts --------------------------------------------------
def test_outsiders_see_nothing(team):
    join(team)                                     # B ist drin, C nicht
    for method, url, kw in project_requests(team):
        r = team["c"].request(method, url, **kw)
        assert r.status_code == 404, (method, url, r.status_code, r.text[:200])
    pid = team["p"]["id"]
    assert pid not in _ids(team["c"].get("/api/projects"))
    assert team["ins"]["id"] not in _ids(team["c"].get("/api/inserts?shared=true"))
    assert team["tool"]["id"] not in _ids(team["c"].get("/api/objects?shared=true"))
    assert team["c"].post(f"/api/projects/{pid}/members", json={"email": team["c_mail"]}).status_code == 404
    assert team["c"].delete(f"/api/projects/{pid}/members/{team['b_id']}").status_code == 404


def test_before_joining_member_sees_nothing(team):
    for method, url, kw in project_requests(team):
        assert team["b"].request(method, url, **kw).status_code == 404, url


# ---- Mitglied: bearbeitet alles im Projekt ------------------------------------------
def test_member_can_work_on_everything_in_the_project(team):
    members = join(team)
    assert [(m["id"], m["role"]) for m in members] == [(team["a_id"], "owner"), (team["b_id"], "member")]
    b, pid = team["b"], team["p"]["id"]
    for method, url, kw in project_requests(team):
        r = b.request(method, url, **kw)
        assert r.status_code == 200, (method, url, r.status_code, r.text[:200])
    got = b.get(f"/api/projects/{pid}").json()
    assert got["access"] == {"role": "member", "owner": team["a"].get("/api/auth/me").json()["user"], "members": 1}
    assert team["a"].get(f"/api/projects/{pid}").json()["access"]["role"] == "owner"
    assert pid in _ids(b.get("/api/projects"))
    # Bibliothek bleibt getrennt, mit shared kommen die Projektsachen dazu
    assert team["tool"]["id"] not in _ids(b.get("/api/objects"))
    assert {team["tool"]["id"], team["lib"]["id"]} <= _ids(b.get("/api/objects?shared=true"))
    assert {team["ins"]["id"], team["ins_lib"]["id"]} <= _ids(b.get("/api/inserts?shared=true"))
    assert team["ins"]["id"] not in _ids(b.get("/api/inserts"))
    # Privates von A bleibt privat
    assert team["private"]["id"] not in _ids(b.get("/api/objects?shared=true"))
    assert team["priv_ins"]["id"] not in _ids(b.get("/api/inserts?shared=true"))
    for url in (f"/api/objects/{team['private']['id']}", f"/api/inserts/{team['priv_ins']['id']}",
                f"/api/files/objects/{team['private']['id']}/top_preview.jpg"):
        assert b.get(url).status_code == 404, url
    # Schubladen-Ansicht: Werkzeug aus A's Bibliothek fehlt bei B nicht
    clone = b.get(f"/api/projects/{pid}/clone").json()
    item = next(i for i in clone["inserts"] if i["id"] == team["ins_lib"]["id"])
    assert item["error"] is None and item["tools"]


def test_member_edits_reach_the_owner(team):
    join(team)
    a, b, pid = team["a"], team["b"], team["p"]["id"]
    p = b.get(f"/api/projects/{pid}").json()
    p["name"], p["template"]["height_mm"] = "Gemeinsam", 31.0
    p["owner_id"], p["archived"] = team["b_id"], True                 # wird ignoriert
    r = b.put(f"/api/projects/{pid}", json=p).json()
    assert r["owner_id"] == team["a_id"] and not r["archived"] and r["name"] == "Gemeinsam"
    assert a.get(f"/api/inserts/{team['ins']['id']}").json()["height_mm"] == 31.0    # Vorlage an alle Einlagen
    ins = b.get(f"/api/inserts/{team['ins']['id']}").json()
    r = b.put(f"/api/inserts/{ins['id']}", json={**ins, "name": "von B", "owner_id": team["b_id"]}).json()
    assert r["owner_id"] == team["a_id"] and a.get(f"/api/inserts/{ins['id']}").json()["name"] == "von B"
    plug = b.post("/api/inserts/plug", json={"project_id": pid, "text": "B"}).json()
    assert plug["owner_id"] == team["b_id"] and plug["id"] in _ids(a.get("/api/inserts?shared=true"))
    own = b.post("/api/objects/demo").json()
    assert b.post(f"/api/projects/{pid}/assign", json={"kind": "object", "id": own["id"]}).status_code == 200
    assert a.get(f"/api/objects/{own['id']}").status_code == 200


def test_member_may_add_own_and_project_tools_only(team):
    join(team)
    b, pid, ins = team["b"], team["p"]["id"], team["ins"]
    with_ = lambda *oids: {**ins, "placements": [{"object_id": o} for o in oids]}  # noqa: E731
    own = b.post("/api/objects/demo").json()                        # B's Bibliothek: darf hinein
    assert b.put(f"/api/inserts/{ins['id']}", json=with_(team["tool"]["id"], own["id"])).status_code == 200
    assert team["a"].get(f"/api/objects/{own['id']}").status_code == 200     # A sieht es jetzt über die Einlage
    assert b.put(f"/api/inserts/{ins['id']}", json=with_(team["private"]["id"])).status_code == 404
    foreign = team["c"].post("/api/objects/demo").json()
    assert b.put(f"/api/inserts/{ins['id']}", json=with_(foreign["id"])).status_code == 404
    # Projektwerkzeuge nicht in eine private Einlage ziehen
    assert b.post("/api/inserts", json={**SPEC, "placements": [{"object_id": team["tool"]["id"]}]}).status_code == 404
    assert b.post("/api/inserts", json={**SPEC, "project_id": pid,
                                        "placements": [{"object_id": team["tool"]["id"]}]}).status_code == 200


def test_nothing_leaks_from_one_shared_project_into_another(team):
    """B ist in P (von A) und in S (von C). Was B über S sieht, darf nicht nach P."""
    join(team)
    c, b = team["c"], team["b"]
    s = c.post("/api/projects", json={"name": "S"}).json()
    c.post(f"/api/projects/{s['id']}/members", json={"email": team["b_mail"]})
    z = c.post("/api/objects/demo").json()                                     # C's Bibliothek
    s_tool = c.post("/api/objects/demo").json()
    c.post(f"/api/projects/{s['id']}/assign", json={"kind": "object", "id": s_tool["id"]})
    s_ins = c.post("/api/inserts", json={**SPEC, "project_id": s["id"], "placements": [{"object_id": z["id"]}]}).json()
    assert b.get(f"/api/objects/{z['id']}").status_code == 200                 # über S sichtbar
    ins = team["ins"]
    for oid in (z["id"], s_tool["id"]):
        r = b.put(f"/api/inserts/{ins['id']}", json={**ins, "placements": [{"object_id": oid}]})
        assert r.status_code == 404, oid
    # Einlage oder Werkzeug aus S nach P verschieben: nur der Besitzer
    assert b.post(f"/api/projects/{team['p']['id']}/assign", json={"kind": "insert", "id": s_ins["id"]}).status_code == 403
    assert b.post(f"/api/projects/{team['p']['id']}/assign", json={"kind": "object", "id": s_tool["id"]}).status_code == 403
    assert b.put(f"/api/inserts/{s_ins['id']}", json={**s_ins, "project_id": team["p"]["id"]}).status_code == 403
    assert b.post(f"/api/projects/{team['p']['id']}/generate", json={"object_ids": [s_tool["id"]]}).status_code == 403
    assert team["a"].get(f"/api/objects/{z['id']}").status_code == 404
    assert team["a"].get(f"/api/objects/{s_tool['id']}").status_code == 404


def test_member_limits(team):
    join(team)
    a, b, pid = team["a"], team["b"], team["p"]["id"]
    # Mitglieder verwalten, archivieren, wiederherstellen: nur der Besitzer
    assert b.post(f"/api/projects/{pid}/members", json={"email": team["c_mail"]}).status_code == 403
    assert b.delete(f"/api/projects/{pid}/members/{team['a_id']}").status_code == 403
    assert b.delete(f"/api/projects/{pid}").status_code == 403
    assert b.post(f"/api/projects/{pid}/restore").status_code == 403
    # Fremdes löschen nein, Eigenes ja; der Projektbesitzer darf alles im Projekt löschen
    assert b.delete(f"/api/inserts/{team['ins']['id']}").status_code == 403
    assert b.delete(f"/api/objects/{team['tool']['id']}").status_code == 403
    mine = b.post("/api/inserts/plug", json={"project_id": pid}).json()
    theirs = b.post("/api/inserts/plug", json={"project_id": pid}).json()
    assert b.delete(f"/api/inserts/{mine['id']}").status_code == 200
    assert a.delete(f"/api/inserts/{theirs['id']}").status_code == 200
    # aus dem Projekt in ein eigenes verschieben: nur der Besitzer der Einlage
    r = b.put(f"/api/inserts/{team['ins']['id']}", json={**team["ins"], "project_id": None})
    assert r.status_code == 403
    own_p = b.post("/api/projects", json={"name": "Meins"}).json()
    assert b.post(f"/api/projects/{own_p['id']}/assign", json={"kind": "insert", "id": team["ins"]["id"]}).status_code == 403
    assert a.get(f"/api/inserts/{team['ins']['id']}").json()["project_id"] == pid
    # herausnehmen nur, was im Projekt liegt
    assert b.post(f"/api/projects/{pid}/assign",
                  json={"kind": "object", "id": team["lib"]["id"], "member": False}).status_code == 422


# ---- Mitglieder verwalten ----------------------------------------------------------
def test_add_member_validation(team, monkeypatch):
    a, pid = team["a"], team["p"]["id"]
    url = f"/api/projects/{pid}/members"
    r = a.post(url, json={"email": f"  {team['b_mail'].upper()} "})          # Groß/Klein, Leerzeichen egal
    assert r.status_code == 200 and team["b_id"] in [m["id"] for m in r.json()]
    assert a.post(url, json={"email": team["b_mail"]}).status_code == 409    # schon dabei
    me = a.get("/api/auth/me").json()["user"]
    assert a.post(url, json={"email": me}).status_code == 409                # Besitzer
    assert a.post(url, json={"email": "niemand@team.test"}).status_code == 404
    assert a.post(url, json={"email": "x"}).status_code == 422
    with db.session() as s:
        s.execute(update(User).where(User.id == team["c_id"]).values(status="disabled"))
    assert a.post(url, json={"email": team["c_mail"]}).status_code == 404     # gesperrt = nicht vorhanden
    monkeypatch.setattr(storage, "MAX_MEMBERS", 1)
    with db.session() as s:
        s.execute(update(User).where(User.id == team["c_id"]).values(status="active"))
    assert a.post(url, json={"email": team["c_mail"]}).status_code == 409    # voll


def test_add_member_is_rate_limited(team):
    a, url = team["a"], f"/api/projects/{team['p']['id']}/members"
    for k in range(auth.LIMIT):
        assert a.post(url, json={"email": f"raten{k}@team.test"}).status_code == 404
    assert a.post(url, json={"email": team["b_mail"]}).status_code == 429
    auth._fails.pop(f"member:{team['a_id']}", None)
    assert a.post(url, json={"email": team["b_mail"]}).status_code == 200


def test_pending_user_can_be_added_but_has_no_access_until_approved(team):
    with db.session() as s:
        s.execute(update(User).where(User.id == team["b_id"]).values(status="pending"))
    members = join(team)
    assert next(m for m in members if m["id"] == team["b_id"])["status"] == "pending"
    assert team["b"].get(f"/api/projects/{team['p']['id']}").status_code == 401


def test_removed_member_loses_access_and_work_stays(team):
    join(team)
    a, b, pid = team["a"], team["b"], team["p"]["id"]
    plug = b.post("/api/inserts/plug", json={"project_id": pid}).json()
    tool = b.post("/api/objects/demo").json()
    b.post(f"/api/projects/{pid}/assign", json={"kind": "object", "id": tool["id"]})
    private = b.post("/api/objects/demo").json()
    r = a.delete(f"/api/projects/{pid}/members/{team['b_id']}")
    assert r.status_code == 200 and r.json()["transferred"] == 2
    for url in (f"/api/projects/{pid}", f"/api/inserts/{plug['id']}", f"/api/objects/{tool['id']}",
                f"/api/inserts/{team['ins']['id']}", f"/api/objects/{team['tool']['id']}"):
        assert b.get(url).status_code == 404, url
    assert pid not in _ids(b.get("/api/projects"))
    assert a.get(f"/api/inserts/{plug['id']}").json()["owner_id"] == team["a_id"]
    assert a.get(f"/api/objects/{tool['id']}").json()["owner_id"] == team["a_id"]
    assert b.get(f"/api/objects/{private['id']}").status_code == 200           # Privates bleibt bei B
    assert a.get(f"/api/objects/{private['id']}").status_code == 404
    assert a.delete(f"/api/projects/{pid}/members/{team['b_id']}").status_code == 404


def test_member_can_leave_owner_cannot(team):
    join(team)
    pid = team["p"]["id"]
    assert team["a"].delete(f"/api/projects/{pid}/members/{team['a_id']}").status_code == 409
    assert team["b"].delete(f"/api/projects/{pid}/members/{team['b_id']}").status_code == 200
    assert team["b"].get(f"/api/projects/{pid}").status_code == 404
    assert team["a"].delete(f"/api/projects/{pid}/members/99999999999").status_code == 422


def test_admin_manages_members_of_any_project(team):
    pid = team["p"]["id"]
    r = team["admin"].post(f"/api/projects/{pid}/members", json={"email": team["c_mail"]})
    assert r.status_code == 200
    assert team["admin"].get(f"/api/projects/{pid}").json()["access"]["role"] == "admin"
    assert team["c"].get(f"/api/projects/{pid}").status_code == 200
    assert team["admin"].delete(f"/api/projects/{pid}/members/{team['c_id']}").status_code == 200


# ---- Nutzer löschen ----------------------------------------------------------------
def test_deleting_owner_hands_project_to_member(team):
    join(team)
    pid, b = team["p"]["id"], team["b"]
    solo = team["a"].post("/api/projects", json={"name": "allein"}).json()
    assert team["admin"].delete(f"/api/admin/users/{team['a_id']}").status_code == 200
    p = b.get(f"/api/projects/{pid}").json()
    assert p["owner_id"] == team["b_id"] and p["access"]["role"] == "owner" and p["access"]["members"] == 0
    assert b.get(f"/api/inserts/{team['ins']['id']}").json()["owner_id"] == team["b_id"]
    assert b.get(f"/api/objects/{team['tool']['id']}").json()["owner_id"] == team["b_id"]
    assert team["admin"].get(f"/api/objects/{team['private']['id']}").status_code == 404    # gelöscht
    assert team["admin"].get(f"/api/projects/{solo['id']}").status_code == 404              # ohne Mitglieder: gelöscht


def test_deleting_member_keeps_their_project_work(team):
    join(team)
    pid = team["p"]["id"]
    plug = team["b"].post("/api/inserts/plug", json={"project_id": pid}).json()
    private = team["b"].post("/api/objects/demo").json()
    assert team["admin"].delete(f"/api/admin/users/{team['b_id']}").status_code == 200
    assert team["a"].get(f"/api/inserts/{plug['id']}").json()["owner_id"] == team["a_id"]
    assert team["admin"].get(f"/api/objects/{private['id']}").status_code == 404
    assert team["a"].get(f"/api/projects/{pid}/members").json()[1:] == []


def test_member_cannot_build_with_tools_from_elsewhere(team):
    """Bauen mit ungespeicherter Spec: Ausgaben liegen bei der Einlage, also gleiche Regel wie beim Speichern."""
    join(team)
    b, ins = team["b"], team["ins"]
    foreign = team["c"].post("/api/objects/demo").json()
    r = b.post(f"/api/inserts/{ins['id']}/build", json={**ins, "placements": [{"object_id": team["private"]["id"]}]})
    assert r.status_code == 404
    r = b.post(f"/api/inserts/{ins['id']}/build", json={**ins, "placements": [{"object_id": foreign["id"]}]})
    assert r.status_code == 404


def test_admin_sees_and_assigns_projects_of_a_user(team):
    admin, pid = team["admin"], team["p"]["id"]
    assert admin.get(f"/api/admin/users/{team['c_id']}/projects").json() == []
    assert admin.post(f"/api/projects/{pid}/members", json={"email": team["c_mail"]}).status_code == 200
    got = admin.get(f"/api/admin/users/{team['c_id']}/projects").json()
    assert [(p["id"], p["role"]) for p in got] == [(pid, "member")]
    owner = admin.get(f"/api/admin/users/{team['a_id']}/projects").json()
    assert (pid, "owner") in [(p["id"], p["role"]) for p in owner]
    users = {u["id"]: u for u in admin.get("/api/admin/users").json()}
    assert users[team["c_id"]]["projects"] == 1
    assert team["a"].get(f"/api/admin/users/{team['c_id']}/projects").status_code == 403
    assert admin.delete(f"/api/projects/{pid}/members/{team['c_id']}").status_code == 200
    assert admin.get(f"/api/admin/users/{team['c_id']}/projects").json() == []
