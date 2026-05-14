"""SQLite store schema sanity tests.

The SQLite reference store ships without Alembic migrations —
``SQLiteStore.initialize()`` runs ``Base.metadata.create_all`` and
relies on SQLAlchemy DDL to materialize the schema. These tests make
sure the Phase 6 additions (``users`` + ``user_roles``) land in the
``create_all`` graph and have the expected primary keys.

The full Postgres migration round-trip (0001 → 0002 → 0003 + reverse
trip) lives in ``adapters/postgres-store/tests/test_migrations.py``
where the testcontainers Postgres is available.
"""

from __future__ import annotations

import os
import tempfile

import pytest
from sqlalchemy import inspect

from wake.rbac import Role
from wake.store import SQLiteStore


@pytest.fixture
async def store() -> SQLiteStore:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="wake-migration-test-")
    os.close(fd)
    s = SQLiteStore(f"sqlite+aiosqlite:///{path}")
    await s.initialize()
    try:
        yield s
    finally:
        await s.close()
        os.unlink(path)


async def test_users_table_exists(store: SQLiteStore) -> None:
    """initialize() creates the users table with the expected PK."""

    def _inspect_sync(conn: object) -> dict[str, object]:
        ins = inspect(conn)
        return {
            "tables": set(ins.get_table_names()),
            "users_pk": ins.get_pk_constraint("users")["constrained_columns"],
            "roles_pk": ins.get_pk_constraint("user_roles")["constrained_columns"],
        }

    async with store.engine.connect() as conn:
        meta = await conn.run_sync(_inspect_sync)

    assert "users" in meta["tables"]
    assert "user_roles" in meta["tables"]
    # Composite PK ordering matters — drives partition pruning on PG
    # and lookup direction on SQLite.
    assert meta["users_pk"] == ["workspace_id", "id"]
    assert meta["roles_pk"] == ["workspace_id", "user_id", "role"]


async def test_legacy_tables_still_present(store: SQLiteStore) -> None:
    """Phase 6 additions did not drop / rename any existing table."""

    def _names(conn: object) -> set[str]:
        return set(inspect(conn).get_table_names())

    async with store.engine.connect() as conn:
        tables = await conn.run_sync(_names)

    for legacy in (
        "agents",
        "agent_versions",
        "environments",
        "sessions",
        "events",
    ):
        assert legacy in tables, f"missing legacy table {legacy!r}"


async def test_user_roles_cascade_in_python(store: SQLiteStore) -> None:
    """SQLiteUserStore.delete cascades roles (no SQL-level FK)."""
    await store.users.create("alice", workspace_id="default")
    await store.users.assign_role("alice", Role.ADMIN, workspace_id="default")
    await store.users.assign_role("alice", Role.VIEWER, workspace_id="default")
    await store.users.delete("alice", workspace_id="default")
    assert (
        await store.users.roles_for("alice", workspace_id="default")
    ) == []
