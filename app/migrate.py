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

import json
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


def retire_dead_statuses(engine: Engine) -> dict[str, int]:
    """Move nodes off statuses that no longer exist. Returns {old: rows moved}.

    Removing a value from models.STATUSES is not a safe edit on its own. The API
    validates `status` against a Literal on the way OUT as well as in, so one
    surviving row with a retired value turns GET /api/projects/{id}/tree into a
    500 -- the whole tree, not just that node. This drains them on every boot,
    so an instance that has been running for a season heals itself on deploy
    rather than breaking for whoever opens it first.

    The previous value is kept in Node.extra["former_status"]. "This was
    scrapped" is real information somebody entered on purpose, and a change to
    the vocabulary should not quietly bin it -- see RETIRED_STATUSES in
    models.py for what maps to what, and why the targets understate progress.

    Idempotent: once no rows carry a retired status there is nothing to do, and
    a node that already has former_status keeps its ORIGINAL value rather than
    having it overwritten by a later hop.
    """
    from .models import RETIRED_STATUSES  # local import; models imports nothing from here

    moved: dict[str, int] = {}
    with engine.begin() as conn:
        present = {c["name"] for c in inspect(engine).get_columns("nodes")} \
            if "nodes" in set(inspect(engine).get_table_names()) else set()
        if "status" not in present:
            return {}  # fresh database; create_all will build it correct

        for old, new in RETIRED_STATUSES.items():
            rows = conn.execute(
                text("SELECT id, extra FROM nodes WHERE status = :old"), {"old": old}
            ).fetchall()
            if not rows:
                continue
            for node_id, extra_json in rows:
                try:
                    extra = json.loads(extra_json) if extra_json else {}
                    if not isinstance(extra, dict):
                        extra = {}
                except (TypeError, ValueError):
                    extra = {}
                # setdefault, not assignment: if this node was already moved
                # once, the first value is the true one.
                extra.setdefault("former_status", old)
                conn.execute(
                    text("UPDATE nodes SET status = :new, extra = :extra WHERE id = :id"),
                    {"new": new, "extra": json.dumps(extra), "id": node_id},
                )
            moved[old] = len(rows)

    for old, count in moved.items():
        log.warning(
            "migrated: %d node(s) moved off retired status %r to %r "
            "(previous value kept in extra.former_status)",
            count, old, RETIRED_STATUSES[old],
        )
    return moved
