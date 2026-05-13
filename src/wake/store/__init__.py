"""Wake storage layer.

Provides abstract storage interfaces (`base`) and a default SQLite
implementation (`sqlite`). All persistence in Wake goes through these
interfaces so the backend can be swapped (Postgres, in-memory, etc.).
"""

from wake.store.base import (
    AgentStore,
    EnvironmentStore,
    EventStore,
    SessionStore,
    StoreError,
)
from wake.store.sqlite import (
    SQLiteAgentStore,
    SQLiteEnvironmentStore,
    SQLiteEventStore,
    SQLiteSessionStore,
    SQLiteStore,
)

__all__ = [
    # Interfaces
    "EventStore",
    "AgentStore",
    "EnvironmentStore",
    "SessionStore",
    "StoreError",
    # SQLite default implementations
    "SQLiteStore",
    "SQLiteAgentStore",
    "SQLiteEnvironmentStore",
    "SQLiteEventStore",
    "SQLiteSessionStore",
]
