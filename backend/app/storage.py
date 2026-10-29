"""Dateisystem-Persistenz: data/objects/<id>/object.json, data/inserts/<id>/insert.json.

Jedes Objekt und jede Einlage hat einen Besitzer (owner_id). Die Lade- und Listenfunktionen bekommen
den angemeldeten Nutzer und werfen KeyError (-> 404), wenn er keinen Zugriff hat; so verrät die
Antwort nicht einmal, dass es die ID gibt. Admins sehen alles, Altdaten ohne Besitzer nur Admins.

Gemeinsame Projekte: Wer an einem Projekt beteiligt ist (Besitzer oder Mitglied, Tabelle
project_members, bei einer Schublade auch alle Beteiligten ihres Schranks), sieht und bearbeitet alles, was im Projekt liegt (project_id), dazu die Werkzeuge
in den Einlagen des Projekts, sofern deren Besitzer selbst beteiligt ist. Anderes (eigene
Bibliothek, andere Projekte) bleibt privat. Löschen, Mitglieder verwalten und Archivieren darf nur,
wem der Eintrag bzw. das Projekt gehört.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import delete as sql_delete
from sqlalchemy import select

from . import config, db
from .models import ProjectMember
from .schemas import InsertSpec, ObjectSpec, ProjectSpec, color_palette

if TYPE_CHECKING:
    from .auth import Principal

MAX_ITEMS = 300          # Objekte bzw. Einlagen je Nutzer


class TooMany(RuntimeError):
    pass


def can_access(owner_id: int | None, user: Principal) -> bool:
    """Nur Besitzer (und Admins); Projektzugriff siehe can_access_insert / can_access_object."""
    return user.is_admin or (owner_id is not None and owner_id == user.id)


def _write(f: Path, text: str) -> None:
    """Atomar schreiben: gleichzeitige Leser (mehrere Bearbeiter) sehen nie eine halbe Datei."""
    tmp = f.with_name(f".{f.name}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, f)


def _visible(owner_id: int | None, user: Principal, all_: bool) -> bool:
    """Listen: eigene Einträge; Admins zusätzlich Altdaten ohne Besitzer, mit all_ alles."""
    return owner_id == user.id or (user.is_admin and (all_ or owner_id is None))


def _root(kind: str) -> Path:
    p = config.DATA_DIR / kind
    p.mkdir(parents=True, exist_ok=True)
    return p


def new_id() -> str:
    return uuid.uuid4().hex[:10]


ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


class InvalidId(KeyError):
    pass


def check_id(i: str) -> str:
    """IDs landen in Dateipfaden: nur harmlose Zeichen erlauben (kein '..', '/', '\')."""
    if not isinstance(i, str) or not ID_RE.match(i):
        raise InvalidId(i)
    return i


def object_dir(oid: str) -> Path:
    return _root("objects") / check_id(oid)


def insert_dir(iid: str) -> Path:
    return _root("inserts") / check_id(iid)


def url_for(path: Path) -> str:
    return "/api/files/" + path.relative_to(config.DATA_DIR).as_posix()


# ---- Objekte ----------------------------------------------------------------
def _read_objects() -> list[ObjectSpec]:
    out = []
    for d in sorted(_root("objects").iterdir()):
        if (d / "object.json").exists():
            out.append(ObjectSpec.model_validate_json((d / "object.json").read_text(encoding="utf-8")))
    return out


def create_object(name: str, owner: Principal, **kw) -> ObjectSpec:
    if sum(1 for o in _read_objects() if o.owner_id == owner.id) >= MAX_ITEMS:
        raise TooMany(f"Höchstens {MAX_ITEMS} Objekte je Nutzer. Bitte alte Objekte löschen.")
    oid = new_id()
    spec = ObjectSpec(id=oid, name=name, created_at=datetime.now(timezone.utc).isoformat(), owner_id=owner.id, **kw)
    object_dir(oid).mkdir(parents=True, exist_ok=True)
    save_object(spec)
    return spec


def save_object(spec: ObjectSpec) -> None:
    d = object_dir(spec.id)
    d.mkdir(parents=True, exist_ok=True)
    _write(d / "object.json", spec.model_dump_json(indent=1))


def load_object(oid: str, user: Principal | None) -> ObjectSpec:
    """user=None nur für interne Aufrufe (keine Prüfung)."""
    f = object_dir(oid) / "object.json"
    if not f.exists():
        raise KeyError(oid)
    spec = ObjectSpec.model_validate_json(f.read_text(encoding="utf-8"))
    if user is not None and not can_access_object(spec, user):
        raise KeyError(oid)
    return spec


def list_objects(user: Principal, all_: bool = False, shared: bool = False) -> list[ObjectSpec]:
    """Eigene Objekte; mit shared zusätzlich die aus gemeinsamen Projekten."""
    objs = _read_objects()
    extra: set[str] = set()
    if shared:
        part = participation()
        mine = {pid for pid, us in part.items() if user.id in us}
        extra = {o.id for o in objs if o.project_id in mine} | _shared_via_inserts(user, part, objs)
    out = [o for o in objs if _visible(o.owner_id, user, all_) or o.id in extra]
    return sorted(out, key=lambda o: o.created_at, reverse=True)


def delete_object(oid: str) -> None:
    shutil.rmtree(object_dir(oid), ignore_errors=True)


# ---- Projekte -----------------------------------------------------------------
def project_dir(pid: str) -> Path:
    return _root("projects") / check_id(pid)


def _read_projects() -> list[ProjectSpec]:
    out = []
    for d in sorted(_root("projects").iterdir()):
        if (d / "project.json").exists():
            out.append(ProjectSpec.model_validate_json((d / "project.json").read_text(encoding="utf-8")))
    return out


def create_project(spec: ProjectSpec, owner: Principal) -> ProjectSpec:
    if sum(1 for p in _read_projects() if p.owner_id == owner.id) >= MAX_ITEMS:
        raise TooMany(f"Höchstens {MAX_ITEMS} Projekte je Nutzer.")
    spec = spec.model_copy(update={"id": new_id(), "owner_id": owner.id,
                                   "created_at": datetime.now(timezone.utc).isoformat()})
    save_project(spec)
    return spec


def save_project(spec: ProjectSpec) -> None:
    d = project_dir(spec.id)
    d.mkdir(parents=True, exist_ok=True)
    _write(d / "project.json", spec.model_dump_json(indent=1))


def load_project(pid: str, user: Principal | None) -> ProjectSpec:
    f = project_dir(pid) / "project.json"
    if not f.exists():
        raise KeyError(pid)
    spec = ProjectSpec.model_validate_json(f.read_text(encoding="utf-8"))
    if user is not None and not (user.is_admin or user.id in participants(spec)):
        raise KeyError(pid)
    return spec


def cabinet_of(p: ProjectSpec) -> ProjectSpec | None:
    """Schrank einer Schublade (fehlt er oder ist es keiner: None)."""
    if not p.cabinet_id or p.kind != "drawer":
        return None
    try:
        c = load_project(p.cabinet_id, None)
    except KeyError:
        return None
    return c if c.kind == "cabinet" else None


def participants(p: ProjectSpec) -> set[int]:
    """Beteiligte: Besitzer und Mitglieder, bei einer Schublade zusätzlich die ihres Schranks."""
    out = set(member_ids(p.id)) | ({p.owner_id} if p.owner_id is not None else set())
    c = cabinet_of(p)
    return out | participants(c) if c is not None else out


def project_owners(p: ProjectSpec) -> set[int]:
    """Wer das Projekt verwaltet: sein Besitzer und (bei einer Schublade) der Besitzer des Schranks."""
    c = cabinet_of(p)
    return {o for o in (p.owner_id, c.owner_id if c else None) if o is not None}


def list_projects(user: Principal, all_: bool = False) -> list[ProjectSpec]:
    """Eigene Projekte und die, an denen der Nutzer beteiligt ist (auch über einen Schrank)."""
    part = participation()
    out = [p for p in _read_projects() if _visible(p.owner_id, user, all_) or user.id in part.get(p.id, set())]
    return sorted(out, key=lambda p: p.created_at, reverse=True)


def delete_project(pid: str) -> None:
    shutil.rmtree(project_dir(pid), ignore_errors=True)
    with db.session() as s:
        s.execute(sql_delete(ProjectMember).where(ProjectMember.project_id == pid))


# ---- Projekt-Mitglieder ---------------------------------------------------------
MAX_MEMBERS = 20


def member_ids(pid: str) -> list[int]:
    """Mitglieder (ohne Besitzer) in der Reihenfolge, in der sie dazukamen."""
    with db.session() as s:
        return list(s.scalars(select(ProjectMember.user_id).where(ProjectMember.project_id == pid)
                              .order_by(ProjectMember.added_at, ProjectMember.user_id)))


def member_projects(uid: int) -> set[str]:
    with db.session() as s:
        return set(s.scalars(select(ProjectMember.project_id).where(ProjectMember.user_id == uid)))


def participation() -> dict[str, set[int]]:
    """Projekt-ID -> beteiligte Nutzer (Besitzer und Mitglieder)."""
    with db.session() as s:
        rows = s.execute(select(ProjectMember.project_id, ProjectMember.user_id)).all()
    out: dict[str, set[int]] = {}
    for p in _read_projects():
        out[p.id] = {p.owner_id} if p.owner_id is not None else set()
    projects = {p.id: p for p in _read_projects()}
    for pid, uid in rows:
        if pid in out:
            out[pid].add(uid)
    for p in projects.values():               # Schublade: auch die Beteiligten des Schranks
        c = projects.get(p.cabinet_id or "")
        if p.kind == "drawer" and c is not None and c.kind == "cabinet":
            out[p.id] |= out[c.id]
    return out


def in_project(pid: str | None, user: Principal) -> bool:
    """Beteiligt (Besitzer oder Mitglied); Admins zählen hier nicht automatisch."""
    if not pid:
        return False
    try:
        p = load_project(pid, None)
    except KeyError:
        return False
    return user.id in participants(p)


def add_member(pid: str, uid: int, by: int) -> None:
    with db.session() as s:
        s.add(ProjectMember(project_id=pid, user_id=uid, added_by=by))


def remove_member(pid: str, uid: int) -> int:
    """Mitglied entfernen. Was es im Projekt angelegt hat (Einlagen, Werkzeuge), bleibt im Projekt und
    geht an den Projektbesitzer über. -> Anzahl übertragener Einträge."""
    with db.session() as s:
        s.execute(sql_delete(ProjectMember).where(ProjectMember.project_id == pid, ProjectMember.user_id == uid))
    owner = load_project(pid, None).owner_id
    return _transfer(pid, uid, owner) if owner is not None else 0


def _transfer(pid: str, from_uid: int, to_uid: int) -> int:
    n = 0
    for o in _read_objects():
        if o.project_id == pid and o.owner_id == from_uid:
            save_object(o.model_copy(update={"owner_id": to_uid}))
            n += 1
    for i in _read_inserts():
        if i.project_id == pid and i.owner_id == from_uid:
            save_insert(i.model_copy(update={"owner_id": to_uid}))
            n += 1
    return n


# ---- Zugriff über Projekte ---------------------------------------------------------
def can_access_insert(spec: InsertSpec, user: Principal) -> bool:
    return can_access(spec.owner_id, user) or in_project(spec.project_id, user)


def can_access_object(spec: ObjectSpec, user: Principal) -> bool:
    if can_access(spec.owner_id, user) or in_project(spec.project_id, user):
        return True
    return spec.id in _shared_via_inserts(user, None, [spec])


def _shared_via_inserts(user: Principal, part: dict[str, set[int]] | None, objs: list[ObjectSpec]) -> set[str]:
    """Werkzeuge, die in einer Einlage eines gemeinsamen Projekts liegen (z. B. aus der Bibliothek
    eines Mitglieds). Nur, wenn ihr Besitzer selbst am Projekt beteiligt ist: so kann niemand fremde
    Werkzeuge (etwa aus einem anderen Projekt) in ein Projekt hineinreichen."""
    part = participation() if part is None else part
    if not any(user.id in us for us in part.values()):
        return set()
    owners = {o.id: o.owner_id for o in objs}
    out: set[str] = set()
    for ins in _read_inserts():
        us = part.get(ins.project_id or "")
        if not us or user.id not in us:
            continue
        for pl in ins.placements:
            if pl.object_id in owners and owners[pl.object_id] in us:
                out.add(pl.object_id)
    return out


def can_delete(owner_id: int | None, project_id: str | None, user: Principal) -> bool:
    """Löschen: wem der Eintrag gehört, wem das Projekt gehört, in dem er liegt, oder Admins."""
    if can_access(owner_id, user):
        return True
    if project_id:
        try:
            return user.id in project_owners(load_project(project_id, None))
        except KeyError:
            return False
    return False


def may_move(owner_id: int | None, user: Principal) -> bool:
    """Einen Eintrag in ein (anderes) Projekt verschieben darf nur sein Besitzer (oder ein Admin):
    sonst ließe sich, was man über ein Projekt sieht, in ein anderes weiterreichen."""
    return can_access(owner_id, user)


# ---- Nutzereinstellungen ------------------------------------------------------
def _settings_file(uid: int) -> Path:
    return _root("settings") / f"user_{int(uid)}.json"


def load_settings(user: Principal) -> dict:
    f = _settings_file(user.id)
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except (OSError, ValueError):
        return {}


def save_settings(user: Principal, data: dict) -> dict:
    cur = load_settings(user)
    cur.update(data)
    _settings_file(user.id).write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
    return cur


# ---- Einlagen ---------------------------------------------------------------
def _read_inserts() -> list[InsertSpec]:
    out = []
    for d in sorted(_root("inserts").iterdir()):
        if (d / "insert.json").exists():
            out.append(InsertSpec.model_validate_json((d / "insert.json").read_text(encoding="utf-8")))
    return out


def create_insert(spec: InsertSpec, owner: Principal) -> InsertSpec:
    if sum(1 for i in _read_inserts() if i.owner_id == owner.id) >= MAX_ITEMS:
        raise TooMany(f"Höchstens {MAX_ITEMS} Einlagen je Nutzer. Bitte alte Einlagen löschen.")
    spec = spec.model_copy(update={"id": new_id(), "owner_id": owner.id,
                                   "created_at": datetime.now(timezone.utc).isoformat()})
    save_insert(spec)
    return spec


def insert_created(spec: InsertSpec) -> str:
    """Anlagezeitpunkt (ISO); ältere Einlagen ohne Angabe: letzte Änderung der Datei."""
    if spec.created_at:
        return spec.created_at
    f = insert_dir(spec.id) / "insert.json"
    t = f.stat().st_mtime if f.exists() else 0.0
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def slots_from_colors(spec: InsertSpec) -> InsertSpec:
    """Filament-Slots folgen den gewählten Farben: gleiche Farbe = gleicher Slot (Körper zuerst,
    Schriftfarben danach, siehe schemas.color_palette)."""
    order = color_palette(spec)
    out = {k: order.index(getattr(spec.color_hex, k).lower()) + 1 for k in ("body", "pocket", "grip", "compartment")}
    spec.colors = spec.colors.model_copy(update=out)
    return spec


def save_insert(spec: InsertSpec) -> None:
    slots_from_colors(spec)
    d = insert_dir(spec.id)
    d.mkdir(parents=True, exist_ok=True)
    _write(d / "insert.json", spec.model_dump_json(indent=1))


def load_insert(iid: str, user: Principal | None) -> InsertSpec:
    """user=None nur für interne Aufrufe (keine Prüfung)."""
    f = insert_dir(iid) / "insert.json"
    if not f.exists():
        raise KeyError(iid)
    spec = InsertSpec.model_validate_json(f.read_text(encoding="utf-8"))
    if user is not None and not can_access_insert(spec, user):
        raise KeyError(iid)
    return spec


def list_inserts(user: Principal, all_: bool = False, shared: bool = False) -> list[InsertSpec]:
    """Eigene Einlagen; mit shared zusätzlich die aus gemeinsamen Projekten."""
    mine: set[str] = set()
    if shared:
        mine = {pid for pid, us in participation().items() if user.id in us}
    return [i for i in _read_inserts() if _visible(i.owner_id, user, all_) or (i.project_id in mine)]


def delete_insert(iid: str) -> None:
    shutil.rmtree(insert_dir(iid), ignore_errors=True)


def objects_for(spec: InsertSpec, user: Principal | None) -> dict[str, ObjectSpec]:
    return {pl.object_id: load_object(pl.object_id, user) for pl in spec.placements}


def check_placements(spec: InsertSpec, user: Principal, keep: set[str] | frozenset = frozenset()) -> None:
    """Fremde Objekte dürfen nicht in eine Einlage (sonst ließe sich ihre Kontur abgreifen).
    Neu hineinlegen darf man eigene Werkzeuge und solche, die im selben Projekt liegen wie die
    Einlage; was schon drin war (keep), bleibt. Gelöschte Objekte sind erlaubt, das Layout meldet sie."""
    for pl in spec.placements:
        if pl.object_id in keep:
            continue
        try:
            o = load_object(pl.object_id, None)
        except KeyError:
            continue
        if can_access(o.owner_id, user):
            continue
        if spec.project_id and o.project_id == spec.project_id and in_project(spec.project_id, user):
            continue
        raise KeyError(pl.object_id)


# ---- Besitzer von Dateien ----------------------------------------------------
def can_read_path(parts: tuple[str, ...], user: Principal) -> bool:
    """Datei unter data/<bereich>/<id>/...: Zugriff wie auf das Objekt bzw. die Einlage (auch über
    ein gemeinsames Projekt); Basisplatten nur für den Besitzer."""
    if len(parts) >= 2 and parts[0] in ("objects", "inserts"):
        try:
            (load_object if parts[0] == "objects" else load_insert)(parts[1], user)
            return True
        except (KeyError, ValueError):
            return False
    found, owner = owner_of_path(parts)
    return found and can_access(owner, user)


def owner_of_path(parts: tuple[str, ...]) -> tuple[bool, int | None]:
    """(gefunden, owner_id) für data/<bereich>/<id>/...; Basisplatten über ihr job.json."""
    if len(parts) < 2:
        return False, None
    try:
        kind, i = parts[0], check_id(parts[1])
    except KeyError:
        return False, None
    if kind == "objects":
        f = object_dir(i) / "object.json"
    elif kind == "inserts":
        f = insert_dir(i) / "insert.json"
    elif kind == "baseplates":
        f = _root("baseplates") / i / "job.json"
    else:
        return False, None
    try:
        return True, json.loads(f.read_text(encoding="utf-8")).get("owner_id")
    except (OSError, ValueError):
        return False, None


def delete_user_data(user_id: int) -> int:
    """Daten eines gelöschten Nutzers. Eigene Projekte mit Mitgliedern gehen an das Mitglied über, das
    am längsten dabei ist; ohne Mitglieder werden sie gelöscht. Was der Nutzer in Projekten anderer
    angelegt hat, bleibt dort und gehört danach dem Projektbesitzer. Alles andere (Objekte, Einlagen,
    Basisplatten) wird gelöscht. -> Anzahl gelöschter Einträge."""
    n = 0
    for p in _read_projects():
        if p.owner_id == user_id:
            heirs = [u for u in member_ids(p.id) if u != user_id]
            if heirs:
                with db.session() as s:
                    s.execute(sql_delete(ProjectMember).where(ProjectMember.project_id == p.id,
                                                              ProjectMember.user_id == heirs[0]))
                save_project(p.model_copy(update={"owner_id": heirs[0]}))
                _transfer(p.id, user_id, heirs[0])
            else:
                delete_project(p.id)
                n += 1
        elif p.owner_id is not None:
            _transfer(p.id, user_id, p.owner_id)
    with db.session() as s:
        s.execute(sql_delete(ProjectMember).where(ProjectMember.user_id == user_id))
    for o in _read_objects():
        if o.owner_id == user_id:
            delete_object(o.id)
            n += 1
    for i in _read_inserts():
        if i.owner_id == user_id:
            delete_insert(i.id)
            n += 1
    for d in _root("baseplates").iterdir():
        found, owner = owner_of_path(("baseplates", d.name))
        if found and owner == user_id:
            shutil.rmtree(d, ignore_errors=True)
            n += 1
    return n
