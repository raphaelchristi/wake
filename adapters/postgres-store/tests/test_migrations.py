"""Alembic migration round-trip tests.

Validates ``0001_initial → 0002_tenancy_columns → 0003_rbac`` upgrade
+ downgrade trip and asserts the expected tables / columns exist at
each step. Skipped automatically when Docker / testcontainers are
unavailable.

The tests run Alembic synchronously against the test container via
``alembic.command``. We strip the ``+asyncpg`` driver suffix from the
DSN because Alembic uses a sync engine internally.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

try:
    from alembic.config import Config as AlembicConfig

    from alembic import command
except Exception:  # noqa: BLE001
    pytest.skip("alembic missing", allow_module_level=True)


_ROOT = Path(__file__).resolve().parent.parent
_ALEMBIC_INI = _ROOT / "alembic.ini"
_ALEMBIC_DIR = _ROOT / "alembic"


def _sync_dsn(async_dsn: str) -> str:
    if async_dsn.startswith("postgresql+asyncpg://"):
        return "postgresql://" + async_dsn[len("postgresql+asyncpg://") :]
    return async_dsn


def _alembic_config(dsn: str) -> AlembicConfig:
    cfg = AlembicConfig(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    os.environ["WAKE_PG_DSN"] = _sync_dsn(dsn)
    return cfg


@pytest.fixture
def empty_database(postgres_dsn: str) -> Iterator[str]:
    """Reset the test container schema to a clean slate per test.

    We DROP every wake-managed table CASCADE so the migration starts
    from zero. Restoring a fresh container per test would be the
    cleanest option but the conftest reuses the container session-wide
    for speed — TRUNCATE is not enough because we want to validate
    DDL.
    """
    from sqlalchemy import create_engine, text

    sync_dsn = _sync_dsn(postgres_dsn)
    engine = create_engine(sync_dsn, future=True)
    with engine.begin() as conn:
        for tbl in (
            "user_roles",
            "users",
            "events",
            "sessions",
            "environments",
            "agent_versions",
            "agents",
            "alembic_version",
        ):
            conn.execute(text(f"DROP TABLE IF EXISTS {tbl} CASCADE"))
        # Partitions of events (0001 migration may have created them).
        for i in range(64):
            conn.execute(text(f"DROP TABLE IF EXISTS events_p_{i:02d} CASCADE"))
    yield postgres_dsn
    # No teardown — next test will reset.


def _table_exists(dsn: str, table: str) -> bool:
    from sqlalchemy import create_engine, text

    engine = create_engine(_sync_dsn(dsn), future=True)
    with engine.connect() as conn:
        n = conn.execute(
            text(
                "SELECT to_regclass(:t)"
            ),
            {"t": table},
        ).scalar()
    return n is not None


def test_upgrade_head_creates_rbac_tables(empty_database: str) -> None:
    """0001 → 0002 → 0003 upgrade head creates users + user_roles."""
    cfg = _alembic_config(empty_database)
    command.upgrade(cfg, "head")
    assert _table_exists(empty_database, "agents")
    assert _table_exists(empty_database, "sessions")
    assert _table_exists(empty_database, "users")
    assert _table_exists(empty_database, "user_roles")


def test_downgrade_to_base_drops_rbac_tables(empty_database: str) -> None:
    """0003 → 0002 → 0001 → base downgrade drops everything cleanly."""
    cfg = _alembic_config(empty_database)
    command.upgrade(cfg, "head")
    assert _table_exists(empty_database, "users")
    # Step back one revision at a time.
    command.downgrade(cfg, "0002_tenancy_columns")
    assert not _table_exists(empty_database, "users")
    assert not _table_exists(empty_database, "user_roles")
    # Tenancy columns + base tables are still there until the next step.
    assert _table_exists(empty_database, "agents")
    command.downgrade(cfg, "base")
    assert not _table_exists(empty_database, "agents")


def test_upgrade_is_idempotent(empty_database: str) -> None:
    """Calling upgrade head twice is a no-op (migrations are idempotent)."""
    cfg = _alembic_config(empty_database)
    command.upgrade(cfg, "head")
    # Second call should not raise — alembic stamps the version table
    # so subsequent ops are skipped.
    command.upgrade(cfg, "head")
    assert _table_exists(empty_database, "users")


def test_users_table_has_workspace_id_pk(empty_database: str) -> None:
    """Schema sanity: (workspace_id, id) is the users primary key."""
    from sqlalchemy import create_engine, text

    cfg = _alembic_config(empty_database)
    command.upgrade(cfg, "head")
    engine = create_engine(_sync_dsn(empty_database), future=True)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT a.attname
                FROM   pg_index i
                JOIN   pg_attribute a
                       ON a.attrelid = i.indrelid
                      AND a.attnum   = ANY(i.indkey)
                WHERE  i.indrelid = 'users'::regclass
                  AND  i.indisprimary
                ORDER BY array_position(i.indkey, a.attnum)
                """
            )
        ).all()
    cols = [r[0] for r in rows]
    assert cols == ["workspace_id", "id"]


# The asyncio import is here to keep the module-level test discovery
# happy under pytest-asyncio mode=auto — pytest will run these as
# synchronous tests since none are coroutines.
_ = asyncio  # noqa: B018 — placeholder to suppress unused-import warnings


def _assert_no_orphan_roles(dsn: str) -> bool:
    """Defensive check used by test_user_roles_fk_cascades."""
    from sqlalchemy import create_engine, text

    engine = create_engine(_sync_dsn(dsn), future=True)
    with engine.connect() as conn:
        n = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM user_roles ur
                WHERE NOT EXISTS (
                    SELECT 1 FROM users u
                    WHERE u.workspace_id = ur.workspace_id
                      AND u.id            = ur.user_id
                )
                """
            )
        ).scalar_one()
    return n == 0


def test_user_roles_fk_cascades(empty_database: str) -> None:
    """Deleting a ``users`` row purges its ``user_roles`` siblings."""
    from sqlalchemy import create_engine, text

    cfg = _alembic_config(empty_database)
    command.upgrade(cfg, "head")
    engine = create_engine(_sync_dsn(empty_database), future=True)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO users (workspace_id, id, organization_id, created_at)
                VALUES ('w1', 'alice', 'default', now())
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO user_roles
                       (workspace_id, user_id, role, organization_id, created_at)
                VALUES ('w1', 'alice', 'admin', 'default', now())
                """
            )
        )
    # Sanity.
    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM user_roles")).scalar_one()
    assert n == 1
    # Cascade.
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = 'alice'"))
    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM user_roles")).scalar_one()
    assert n == 0
    assert _assert_no_orphan_roles(empty_database)
