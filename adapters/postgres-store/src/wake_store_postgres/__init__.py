"""wake-store-postgres — PostgreSQL backend for Wake.

Re-exports the public surface so callers can do::

    from wake_store_postgres import PostgresStore
"""

from __future__ import annotations

from wake_store_postgres.agents import PostgresAgentStore
from wake_store_postgres.environments import PostgresEnvironmentStore
from wake_store_postgres.events import PostgresEventStore
from wake_store_postgres.heartbeat import WorkerHeartbeat
from wake_store_postgres.locks import (
    acquire_session_lock,
    release_session_lock,
    session_lock_key,
)
from wake_store_postgres.sessions import PostgresSessionStore
from wake_store_postgres.store import PostgresStore, create_from_dsn
from wake_store_postgres.users import PostgresUserStore

__all__ = [
    "PostgresStore",
    "PostgresAgentStore",
    "PostgresEnvironmentStore",
    "PostgresEventStore",
    "PostgresSessionStore",
    "PostgresUserStore",
    "WorkerHeartbeat",
    "acquire_session_lock",
    "release_session_lock",
    "session_lock_key",
    "create_from_dsn",
]

__version__ = "0.1.0"
