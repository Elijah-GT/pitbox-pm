"""Tiny forward-only migrations for SQLite.

`Base.metadata.create_all()` creates missing TABLES but never alters existing
ones, so adding a column to a model leaves anyone with an existing database
broken -- the app starts and then every query mentioning that column fails.

Adding login meant three new columns on `members`, and there is already real
data in the field, so this bridges the gap: it inspects the live schema and
adds anything missing. Forward-only, idempotent, safe to run on every boot.

This is NOT a substitute for Alembic. It cannot rename, drop, change a type, or
backfill. When the schema starts moving in ways this cannot express, switch:

    pip install alembic && alembic init migrations
"""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)

# table -> column -> the DDL type/default used when adding it.
# Keep in step with models.py. Every entry must be nullable or have a default,
# because SQLite cannot add a NOT NULL column without one.
ADDITIONS: dict[str, dict[str, str]] = {
    "members": {
        "password_hash": "VARCHAR(255)",
        "is_admin": "BOOLEAN NOT NULL DEFAULT 0",
        "last_login_at": "DATETIME",
        "name_confirmed": "BOOLEAN NOT NULL DEFAULT 0",
    },
}


def run_migrations(engine: Engine) -> list[str]:
    """Add any missing columns. Returns what it did, for the log."""
    if not engine.url.drivername.startswith("sqlite"):
        # Postgres deserves real migrations, not this.
        return []

    applied: list[str] = []
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table, columns in ADDITIONS.items():
            if table not in existing_tables:
                continue  # create_all will build it complete
            present = {c["name"] for c in inspector.get_columns(table)}
            for column, ddl in columns.items():
                if column in present:
                    continue
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
                applied.append(f"{table}.{column}")

    for change in applied:
        log.info("migrated: added column %s", change)
    return applied
