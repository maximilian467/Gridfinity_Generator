"""Alembic-Umgebung: läuft nur programmatisch über app.db.migrate (Verbindung kommt von dort)."""
from alembic import context

from app.models import Base

connection = context.config.attributes["connection"]
context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
with context.begin_transaction():
    context.run_migrations()
