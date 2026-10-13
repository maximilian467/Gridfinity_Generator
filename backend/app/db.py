"""SQLite-Datenbank (data/app.db) für Nutzer und Sitzungen.

DATABASE_URL überschreibt den Pfad (z. B. später Postgres). Das Schema verwaltet Alembic
(backend/alembic); beim ersten Zugriff wird automatisch auf den neuesten Stand migriert.
"""
from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from . import config

ALEMBIC_DIR = Path(__file__).resolve().parents[1] / "alembic"

_engine: Engine | None = None
_factory: sessionmaker[Session] | None = None
_lock = threading.Lock()


def url() -> str:
    return os.environ.get("DATABASE_URL") or f"sqlite:///{(config.DATA_DIR / 'app.db').as_posix()}"


def _sqlite_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


def migrate(engine: Engine) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")


def engine() -> Engine:
    global _engine, _factory
    if _engine is None:
        with _lock:
            if _engine is None:
                u = url()
                if u.startswith("sqlite:///"):
                    Path(u.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
                eng = create_engine(u, connect_args={"check_same_thread": False} if u.startswith("sqlite") else {})
                if u.startswith("sqlite"):
                    event.listen(eng, "connect", _sqlite_pragmas)
                migrate(eng)
                if u.startswith("sqlite:///"):              # Nutzer und Sitzungen: nur für den Besitzer lesbar
                    Path(u.removeprefix("sqlite:///")).chmod(0o600)
                _factory = sessionmaker(eng, expire_on_commit=False)
                _engine = eng
    return _engine


@contextmanager
def session() -> Iterator[Session]:
    """Kurze Transaktion: commit am Ende, rollback bei Fehler."""
    engine()
    assert _factory is not None
    s = _factory()
    try:
        yield s
        s.commit()
    except BaseException:
        s.rollback()
        raise
    finally:
        s.close()


def reset() -> None:
    """Nur für Tests: Verbindung schließen (z. B. nach Wechsel von DATABASE_URL)."""
    global _engine, _factory
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine, _factory = None, None
