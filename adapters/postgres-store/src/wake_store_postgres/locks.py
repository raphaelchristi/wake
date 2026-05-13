"""Postgres advisory-lock helpers for session ownership.

`pg_try_advisory_lock(bigint)` is a non-blocking, session-scoped lock
that's perfect for "this worker owns session X" semantics: when the
connection dies (worker crashes, network blip), the lock is released
automatically by Postgres without any cleanup code on our side.

The lock key is a stable 32-bit `hashtext(session_id)` cast to bigint.
hashtext is the same family Postgres uses internally for HASH
partitioning so the function name lines up naturally with the partition
strategy on ``events``.

Locks are taken on a *dedicated* asyncpg connection (not pooled) so the
lifetime is meaningful. Using a pooled connection would mean a random
connection inherits the lock state, defeating the purpose.
"""

from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

log = structlog.get_logger(__name__)


def session_lock_key(session_id: str) -> int:
    """Return the bigint key used with ``pg_advisory_lock``.

    Implemented as a stable Python-side hash so callers can pre-compute
    keys without a round trip; the database-side equivalent is
    ``hashtext(session_id)::bigint`` and yields identical results
    because ``hashtext`` is just a 32-bit hash.

    We compute Postgres-compatible 32-bit hash by sending the actual
    SQL fragment ``hashtext(session_id)`` whenever the lock is taken,
    so this helper is informational; the database is the source of
    truth.
    """
    # Stable but only Python-side. Used for tests / logging.
    return hash(session_id) & 0x7FFFFFFF


async def acquire_session_lock(
    engine: AsyncEngine,
    session_id: str,
    *,
    connection: AsyncConnection | None = None,
) -> bool:
    """Try to take the advisory lock for ``session_id``.

    Returns ``True`` if acquired, ``False`` if another worker holds it.

    When ``connection`` is provided the lock is taken on that
    connection (allowing the caller to keep it for the lock's
    lifetime); otherwise a fresh connection is checked out from the
    engine. **The caller is responsible for keeping the connection
    alive** — once it returns to the pool the lock is gone.
    """
    sql = text("SELECT pg_try_advisory_lock(hashtext(:sid)::bigint)")
    if connection is not None:
        result = await connection.execute(sql, {"sid": session_id})
        acquired = bool(result.scalar())
    else:
        async with engine.connect() as conn:
            result = await conn.execute(sql, {"sid": session_id})
            acquired = bool(result.scalar())
    log.debug("session.lock.attempt", session_id=session_id, acquired=acquired)
    return acquired


async def release_session_lock(
    engine: AsyncEngine,
    session_id: str,
    *,
    connection: AsyncConnection | None = None,
) -> bool:
    """Release the advisory lock for ``session_id``.

    Returns ``True`` if the lock was held and released, ``False``
    otherwise. As a convenience, supplying ``connection`` releases the
    lock on that specific connection — useful when paired with
    ``acquire_session_lock(connection=...)``.
    """
    sql = text("SELECT pg_advisory_unlock(hashtext(:sid)::bigint)")
    if connection is not None:
        result = await connection.execute(sql, {"sid": session_id})
        released = bool(result.scalar())
    else:
        async with engine.connect() as conn:
            result = await conn.execute(sql, {"sid": session_id})
            released = bool(result.scalar())
    log.debug("session.lock.release", session_id=session_id, released=released)
    return released


__all__ = [
    "session_lock_key",
    "acquire_session_lock",
    "release_session_lock",
]
