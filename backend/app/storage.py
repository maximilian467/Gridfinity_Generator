"""Dateisystem-Persistenz: data/objects/<id>/object.json, data/inserts/<id>/insert.json."""
from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .schemas import InsertSpec, ObjectSpec


def _root(kind: str) -> Path:
    p = config.DATA_DIR / kind
    p.mkdir(parents=True, exist_ok=True)
    return p


def new_id() -> str:
    return uuid.uuid4().hex[:10]


def object_dir(oid: str) -> Path:
    return _root("objects") / oid


def insert_dir(iid: str) -> Path:
    return _root("inserts") / iid


def url_for(path: Path) -> str:
    return "/api/files/" + path.relative_to(config.DATA_DIR).as_posix()


# ---- Objekte ----------------------------------------------------------------
def create_object(name: str, **kw) -> ObjectSpec:
    oid = new_id()
    spec = ObjectSpec(id=oid, name=name, created_at=datetime.now(timezone.utc).isoformat(), **kw)
    object_dir(oid).mkdir(parents=True, exist_ok=True)
    save_object(spec)
    return spec


def save_object(spec: ObjectSpec) -> None:
    d = object_dir(spec.id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "object.json").write_text(spec.model_dump_json(indent=1), encoding="utf-8")


def load_object(oid: str) -> ObjectSpec:
    f = object_dir(oid) / "object.json"
    if not f.exists():
        raise KeyError(oid)
    return ObjectSpec.model_validate_json(f.read_text(encoding="utf-8"))


def list_objects() -> list[ObjectSpec]:
    out = []
    for d in sorted(_root("objects").iterdir()):
        if (d / "object.json").exists():
            out.append(ObjectSpec.model_validate_json((d / "object.json").read_text(encoding="utf-8")))
    return sorted(out, key=lambda o: o.created_at, reverse=True)


def delete_object(oid: str) -> None:
    shutil.rmtree(object_dir(oid), ignore_errors=True)


# ---- Einlagen ---------------------------------------------------------------
def create_insert(spec: InsertSpec) -> InsertSpec:
    spec = spec.model_copy(update={"id": new_id()})
    save_insert(spec)
    return spec


def save_insert(spec: InsertSpec) -> None:
    d = insert_dir(spec.id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "insert.json").write_text(spec.model_dump_json(indent=1), encoding="utf-8")


def load_insert(iid: str) -> InsertSpec:
    f = insert_dir(iid) / "insert.json"
    if not f.exists():
        raise KeyError(iid)
    return InsertSpec.model_validate_json(f.read_text(encoding="utf-8"))


def list_inserts() -> list[InsertSpec]:
    out = []
    for d in sorted(_root("inserts").iterdir()):
        if (d / "insert.json").exists():
            out.append(InsertSpec.model_validate_json((d / "insert.json").read_text(encoding="utf-8")))
    return out


def delete_insert(iid: str) -> None:
    shutil.rmtree(insert_dir(iid), ignore_errors=True)


def objects_for(spec: InsertSpec) -> dict[str, ObjectSpec]:
    return {pl.object_id: load_object(pl.object_id) for pl in spec.placements}
