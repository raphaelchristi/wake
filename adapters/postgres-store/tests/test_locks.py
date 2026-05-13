"""Tests for Postgres advisory-lock helpers (locks.py).

Contention semantics:
- ``acquire_session_lock`` on a fresh connection succeeds.
- A second acquisition on a *different* connection fails (returns False).
- Releasing on the original connection lets the second one through.
"""

from __future__ import annotations

from typing import Any

import pytest

from wake_store_postgres.locks import (
    acquire_session_lock,
    release_session_lock,
    session_lock_key,
)

# pytest-asyncio is in AUTO mode (set in pyproject.toml) so async test
# functions are detected automatically; no module-scoped marker needed.
_ = pytest  # kept for the `pytest.raises` calls below


def test_session_lock_key_is_stable() -> None:
    a = session_lock_key("01HSAMEID00000000000000ABCD")
    b = session_lock_key("01HSAMEID00000000000000ABCD")
    c = session_lock_key("01HOTHER00000000000000ABCD")
    assert a == b
    assert a != c


async def test_acquire_and_release_on_same_connection(store: Any) -> None:
    sid = "01HLOCK0000000000000000ABCD"
    async with store.engine.connect() as conn:
        assert await acquire_session_lock(store.engine, sid, connection=conn) is True
        assert await release_session_lock(store.engine, sid, connection=conn) is True


async def test_lock_is_contested_across_connections(store: Any) -> None:
    sid = "01HLOCK2000000000000000ABCD"
    conn1 = await store.engine.connect()
    conn2 = await store.engine.connect()
    try:
        # First connection takes the lock.
        assert await acquire_session_lock(store.engine, sid, connection=conn1) is True
        # Second connection cannot acquire — returns False.
        assert await acquire_session_lock(store.engine, sid, connection=conn2) is False
        # Release on conn1 — conn2 can now grab it.
        assert await release_session_lock(store.engine, sid, connection=conn1) is True
        assert await acquire_session_lock(store.engine, sid, connection=conn2) is True
        await release_session_lock(store.engine, sid, connection=conn2)
    finally:
        await conn1.close()
        await conn2.close()


async def test_release_without_acquire_returns_false(store: Any) -> None:
    sid = "01HLOCK3000000000000000ABCD"
    async with store.engine.connect() as conn:
        # We never acquired, so release returns False.
        assert await release_session_lock(store.engine, sid, connection=conn) is False
