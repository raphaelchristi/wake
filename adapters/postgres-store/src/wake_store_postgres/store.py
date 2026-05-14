"""PostgresStore — bundle of the four Postgres-backed stores.

Mirrors ``wake.store.sqlite.SQLiteStore``: one engine, one sessionmaker,
four facades exposed as ``.events``, ``.agents``, ``.environments``,
``.sessions``.

``initialize()`` is idempotent: it runs Alembic to head, so calling it
twice is a no-op once the schema is current. The migration installs the
HASH-partitioned ``events`` table, BRIN indexes and the NOTIFY trigger.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import structlog
from alembic.config import Config as AlembicConfig
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from wake_store_postgres._helpers import normalise_dsn, to_sync_dsn
from wake_store_postgres.agents import PostgresAgentStore
from wake_store_postgres.environments import PostgresEnvironmentStore
from wake_store_postgres.events import PostgresEventStore
from wake_store_postgres.sessions import PostgresSessionStore
from wake_store_postgres.users import PostgresUserStore

log = structlog.get_logger(__name__)


# Absolute path to the alembic directory shipped with this package.
# Resolved at import time so the migration is reachable regardless of
# the CWD when ``initialize()`` is called.
_ALEMBIC_DIR = Path(__file__).resolve().parent.parent.parent / "alembic"
_ALEMBIC_INI = _ALEMBIC_DIR.parent / "alembic.ini"


class PostgresStore:
    """Bundle of the four Postgres-backed stores sharing one engine.

    Usage::

        store = PostgresStore("postgresql+asyncpg://user:pw@host/db")
        await store.initialize()  # runs Alembic
        ...
        await store.close()
    """

    def __init__(
        self,
        dsn: str,
        *,
        engine_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.dsn = normalise_dsn(dsn)
        # ``pool_pre_ping=True`` is essential for long-running services
        # behind a connection pooler (PgBouncer, Pgpool). Default to
        # True; callers may override via ``engine_kwargs``.
        default_kwargs: dict[str, Any] = {
            "future": True,
            "pool_pre_ping": True,
        }
        if engine_kwargs:
            default_kwargs.update(engine_kwargs)
        self.engine: AsyncEngine = create_async_engine(self.dsn, **default_kwargs)
        self._sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False
        )
        self.events: PostgresEventStore = PostgresEventStore(self._sessionmaker, self.engine)
        self.agents: PostgresAgentStore = PostgresAgentStore(self._sessionmaker)
        self.environments: PostgresEnvironmentStore = PostgresEnvironmentStore(self._sessionmaker)
        self.sessions: PostgresSessionStore = PostgresSessionStore(self._sessionmaker)
        self.users: PostgresUserStore = PostgresUserStore(self._sessionmaker)

    async def initialize(self) -> None:
        """Run Alembic to head.

        Alembic is sync; we run it in a thread to avoid blocking the
        asyncio event loop. The migration is idempotent so calling
        initialize() repeatedly is safe.
        """
        import asyncio

        def _run() -> None:
            cfg = AlembicConfig(str(_ALEMBIC_INI))
            cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
            # Alembic's env.py picks the DSN up from this env var;
            # avoids mutating the .ini on disk.
            os.environ["WAKE_PG_DSN"] = self.dsn
            command.upgrade(cfg, "head")

        await asyncio.to_thread(_run)
        # Quick sanity check — we logged "initialised" but never
        # surface DSN credentials (substring before the @ is masked).
        log.info("postgres_store.initialised", db=_redact(self.dsn))

    async def close(self) -> None:
        """Dispose the engine pool. Idempotent."""
        await self.engine.dispose()


def _redact(dsn: str) -> str:
    """Return a DSN with the password component replaced by ``***``.

    Used only for logging — credentials never appear in log output.
    """
    try:
        # Split off scheme.
        scheme, rest = dsn.split("://", 1)
    except ValueError:
        return "***"
    if "@" not in rest:
        return f"{scheme}://{rest}"
    creds, host = rest.rsplit("@", 1)
    if ":" in creds:
        user, _ = creds.split(":", 1)
        return f"{scheme}://{user}:***@{host}"
    return f"{scheme}://{creds}@{host}"


def create_from_dsn(dsn: str) -> PostgresStore:
    """Entry-point factory: ``wake.stores`` → ``PostgresStore``.

    Used by ``wake.runtime.registry.StoreRegistry`` to instantiate a
    Postgres backend from a DSN string.
    """
    return PostgresStore(dsn)


# Re-export DSN helpers for tooling.
to_sync_dsn = to_sync_dsn  # noqa: PLW0127 — explicit re-export


__all__ = ["PostgresStore", "create_from_dsn", "to_sync_dsn"]
