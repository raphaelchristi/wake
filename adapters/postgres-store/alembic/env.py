"""Alembic environment for wake-store-postgres.

The store calls ``alembic upgrade head`` programmatically from
``PostgresStore.initialize()``. We accept the connection URL either via
the standard ``sqlalchemy.url`` config or via the ``WAKE_PG_DSN``
environment variable so the bundle can pass it through without mutating
``alembic.ini``.

Only synchronous migrations are needed (Alembic does not yet support
fully async upgrades); we open a sync ``psycopg``-style engine just to
run DDL, then return control to the async runtime.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from wake_store_postgres.models import Base

# Alembic Config object.
config = context.config

# Set up loggers if the .ini specifies a logging config.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Source of truth for autogenerate compares — also unused here because
# we ship hand-written migrations.
target_metadata = Base.metadata


def _resolve_url() -> str:
    """Return the connection URL, preferring env > ini.

    The async DSN (``postgresql+asyncpg://...``) is rewritten to the
    sync form (``postgresql+psycopg2://...`` or plain
    ``postgresql://``) because Alembic uses a sync engine for DDL.
    """
    env_url = os.environ.get("WAKE_PG_DSN")
    ini_url = config.get_main_option("sqlalchemy.url")
    url = env_url or ini_url or ""
    if not url:
        raise RuntimeError(
            "no database URL configured for Alembic; set sqlalchemy.url or "
            "WAKE_PG_DSN environment variable",
        )
    # Migrations are sync; strip async driver suffix.
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url[len("postgresql+asyncpg://") :]
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout)."""
    context.configure(
        url=_resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against a live database."""
    ini_section = config.get_section(config.config_ini_section) or {}
    ini_section["sqlalchemy.url"] = _resolve_url()
    connectable = engine_from_config(
        ini_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
