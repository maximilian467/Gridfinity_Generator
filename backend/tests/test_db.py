"""Datenbank: Migration legt die Tabellen an und passt zu den Modellen."""
from sqlalchemy import inspect

from app import db, models


def test_migration_creates_tables():
    names = set(inspect(db.engine()).get_table_names())
    assert {"users", "sessions", "audit_log", "alembic_version"} <= names


def test_schema_matches_models():
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    with db.engine().connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), models.Base.metadata)
    assert diff == []


def test_utc_roundtrip_and_cascade():
    from datetime import timedelta
    with db.session() as s:
        u = models.User(email="db@test.de", status="active")
        s.add(u)
        s.flush()
        s.add(models.Session(token_hash="h" * 64, user_id=u.id, expires_at=models.utcnow() + timedelta(days=1)))
        uid = u.id
    with db.session() as s:
        sess = s.get(models.Session, "h" * 64)
        assert sess.expires_at.tzinfo is not None and sess.expires_at > models.utcnow()
        s.delete(s.get(models.User, uid))
    with db.session() as s:
        assert s.get(models.Session, "h" * 64) is None          # Sitzungen verschwinden mit dem Nutzer
