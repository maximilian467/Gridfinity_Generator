"""Nutzerverwaltung (nur Admins): freischalten, sperren, Rolle ändern, löschen, Protokoll."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select

from .. import auth, db, storage
from ..auth import Principal, require_admin
from ..models import AuditLog, User, utcnow

router = APIRouter(prefix="/admin", tags=["admin"])

ORDER = {"pending": 0, "active": 1, "disabled": 2}


def _out(u: User, counts: dict[int, list[int]]) -> dict:
    c = counts.get(u.id, [0, 0, 0])
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "status": u.status,
            "google": u.google_sub is not None, "created_at": u.created_at, "last_login_at": u.last_login_at,
            "approved_at": u.approved_at, "objects": c[0], "inserts": c[1], "projects": c[2]}


def _counts() -> dict[int, list[int]]:
    """Je Nutzer: [Objekte, Einlagen, beteiligte Projekte (eigene und als Mitglied)]."""
    counts: dict[int, list[int]] = {}
    for us in storage.participation().values():
        for uid in us:
            counts.setdefault(uid, [0, 0, 0])[2] += 1
    for o in storage._read_objects():
        if o.owner_id is not None:
            counts.setdefault(o.owner_id, [0, 0, 0])[0] += 1
    for i in storage._read_inserts():
        if i.owner_id is not None:
            counts.setdefault(i.owner_id, [0, 0, 0])[1] += 1
    return counts


@router.get("/users")
def list_users(_: Principal = Depends(require_admin)) -> list[dict]:
    counts = _counts()
    with db.session() as s:
        users = s.scalars(select(User)).all()
        return [_out(u, counts) for u in sorted(users, key=lambda u: (ORDER.get(u.status, 3), u.email))]


class UserChange(BaseModel):
    status: Literal["active", "disabled"] | None = None
    role: Literal["admin", "user"] | None = None


def _other_active_admins(s, uid: int) -> int:
    return s.scalar(select(func.count()).select_from(User).where(
        User.role == "admin", User.status == "active", User.id != uid))


@router.put("/users/{uid}")
def change_user(uid: int, body: UserChange, request: Request, me: Principal = Depends(require_admin)) -> dict:
    with db.session() as s:
        u = s.get(User, uid)
        if u is None:
            raise HTTPException(404, "Nutzer nicht gefunden")
        if uid == me.id and body.status == "disabled":
            raise HTTPException(409, "Du kannst dich nicht selbst sperren")
        loses_admin = (body.role == "user" or body.status == "disabled") and u.role == "admin"
        if loses_admin and _other_active_admins(s, uid) == 0:
            raise HTTPException(409, "Es muss mindestens ein aktiver Admin bleiben")
        actions = []
        if body.status and body.status != u.status:
            if body.status == "active" and u.approved_at is None:
                u.approved_at = utcnow()
            actions.append({"active": "approve" if u.status == "pending" else "enable", "disabled": "disable"}[body.status])
            u.status = body.status
        if body.role and body.role != u.role:
            actions.append(f"role_{body.role}")
            u.role = body.role
        for a in actions:
            s.add(AuditLog(action=a, target=u.email, actor_id=me.id, ip=auth.client_ip(request)))
        out = _out(u, _counts())
    if body.status == "disabled":
        auth.revoke_all(uid)              # gesperrt: sofort raus (die Rolle gilt ohnehin ab der nächsten Anfrage)
    return out


@router.delete("/users/{uid}")
def delete_user(uid: int, request: Request, me: Principal = Depends(require_admin)) -> dict:
    if uid == me.id:
        raise HTTPException(409, "Du kannst dein eigenes Konto nicht löschen")
    with db.session() as s:
        u = s.get(User, uid)
        if u is None:
            raise HTTPException(404, "Nutzer nicht gefunden")
        if u.role == "admin" and u.status == "active" and _other_active_admins(s, uid) == 0:
            raise HTTPException(409, "Es muss mindestens ein aktiver Admin bleiben")
        email = u.email
        s.delete(u)                       # Sitzungen verschwinden mit (ON DELETE CASCADE)
    removed = storage.delete_user_data(uid)
    auth.audit("delete_user", f"{email} ({removed} Einträge)", me.id, auth.client_ip(request))
    return {"ok": True, "removed": removed}


@router.get("/users/{uid}/projects")
def user_projects(uid: int, _: Principal = Depends(require_admin)) -> list[dict]:
    """Projekte, an denen der Nutzer beteiligt ist (Besitzer oder Mitglied). Hinzufügen und Entfernen
    laufen über /projects/{pid}/members (Admins dürfen dort bei jedem Projekt)."""
    mine = storage.member_projects(uid)
    names = {p.id: p.name for p in storage._read_projects()}
    out = []
    for p in storage._read_projects():
        if p.owner_id == uid or p.id in mine:
            out.append({"id": p.id, "name": p.name, "role": "owner" if p.owner_id == uid else "member",
                        "archived": p.archived, "kind": p.kind,
                        "cabinet": names.get(p.cabinet_id or "") if p.kind == "drawer" else None})
    return sorted(out, key=lambda p: (p["archived"], p["role"] != "owner", p["name"].lower()))


@router.get("/audit")
def audit_log(limit: int = Query(100, ge=1, le=500), _: Principal = Depends(require_admin)) -> list[dict]:
    with db.session() as s:
        rows = s.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)).all()
        emails = dict(s.execute(select(User.id, User.email)).all())
        return [{"ts": r.ts, "actor": emails.get(r.actor_id, "") if r.actor_id else "", "action": r.action,
                 "target": r.target, "ip": r.ip} for r in rows]
