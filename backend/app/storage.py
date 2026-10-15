"""Dateisystem-Persistenz: data/objects/<id>/object.json, data/inserts/<id>/insert.json.

Jedes Objekt und jede Einlage hat einen Besitzer (owner_id). Die Lade- und Listenfunktionen bekommen
den angemeldeten Nutzer und werfen KeyError (-> 404), wenn er keinen Zugriff hat; so verrät die
Antwort nicht einmal, dass es die ID gibt. Admins sehen alles, Altdaten ohne Besitzer nur Admins.
"""
from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from . import config
from .schemas import InsertSpec, ObjectSpec, ProjectSpec

if TYPE_CHECKING:
    from .auth import Principal

MAX_ITEMS = 300          # Objekte bzw. Einlagen je Nutzer


class TooMany(RuntimeError):
    pass


def can_access(owner_id: int | None, user: Principal) -> bool:
    return user.is_admin or (owner_id is not None and owner_id == user.id)


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
    (d / "object.json").write_text(spec.model_dump_json(indent=1), encoding="utf-8")


def load_object(oid: str, user: Principal | None) -> ObjectSpec:
    """user=None nur für interne Aufrufe (keine Prüfung)."""
    f = object_dir(oid) / "object.json"
    if not f.exists():
        raise KeyError(oid)
    spec = ObjectSpec.model_validate_json(f.read_text(encoding="utf-8"))
    if user is not None and not can_access(spec.owner_id, user):
        raise KeyError(oid)
    return spec


def list_objects(user: Principal, all_: bool = False) -> list[ObjectSpec]:
    out = [o for o in _read_objects() if _visible(o.owner_id, user, all_)]
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
    (d / "project.json").write_text(spec.model_dump_json(indent=1), encoding="utf-8")


def load_project(pid: str, user: Principal | None) -> ProjectSpec:
    f = project_dir(pid) / "project.json"
    if not f.exists():
        raise KeyError(pid)
    spec = ProjectSpec.model_validate_json(f.read_text(encoding="utf-8"))
    if user is not None and not can_access(spec.owner_id, user):
        raise KeyError(pid)
    return spec


def list_projects(user: Principal, all_: bool = False) -> list[ProjectSpec]:
    out = [p for p in _read_projects() if _visible(p.owner_id, user, all_)]
    return sorted(out, key=lambda p: p.created_at, reverse=True)


def delete_project(pid: str) -> None:
    shutil.rmtree(project_dir(pid), ignore_errors=True)


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
    """Filament-Slots folgen den gewählten Farben: gleiche Farbe = gleicher Slot (Körper zuerst)."""
    order: list[str] = []
    out = {}
    for k in ("body", "pocket", "grip", "compartment"):
        h = getattr(spec.color_hex, k).lower()
        if h not in order:
            order.append(h)
        out[k] = order.index(h) + 1
    spec.colors = spec.colors.model_copy(update=out)
    return spec


def save_insert(spec: InsertSpec) -> None:
    slots_from_colors(spec)
    d = insert_dir(spec.id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "insert.json").write_text(spec.model_dump_json(indent=1), encoding="utf-8")


def load_insert(iid: str, user: Principal | None) -> InsertSpec:
    """user=None nur für interne Aufrufe (keine Prüfung)."""
    f = insert_dir(iid) / "insert.json"
    if not f.exists():
        raise KeyError(iid)
    spec = InsertSpec.model_validate_json(f.read_text(encoding="utf-8"))
    if user is not None and not can_access(spec.owner_id, user):
        raise KeyError(iid)
    return spec


def list_inserts(user: Principal, all_: bool = False) -> list[InsertSpec]:
    return [i for i in _read_inserts() if _visible(i.owner_id, user, all_)]


def delete_insert(iid: str) -> None:
    shutil.rmtree(insert_dir(iid), ignore_errors=True)


def objects_for(spec: InsertSpec, user: Principal | None) -> dict[str, ObjectSpec]:
    return {pl.object_id: load_object(pl.object_id, user) for pl in spec.placements}


def check_placements(spec: InsertSpec, user: Principal) -> None:
    """Fremde Objekte dürfen nicht in eine Einlage (sonst ließe sich ihre Kontur abgreifen).
    Gelöschte Objekte sind erlaubt, das Layout meldet sie dann."""
    for pl in spec.placements:
        try:
            o = load_object(pl.object_id, None)
        except KeyError:
            continue
        if not can_access(o.owner_id, user):
            raise KeyError(pl.object_id)


# ---- Besitzer von Dateien ----------------------------------------------------
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
    """Alle Objekte, Einlagen und Basisplatten eines Nutzers löschen. -> Anzahl."""
    n = 0
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
