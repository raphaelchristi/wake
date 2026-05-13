"""Tests for the WorkerHeartbeat lifecycle + stale detection."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from wake_store_postgres.heartbeat import HeartbeatError, WorkerHeartbeat

pytestmark = pytest.mark.asyncio


async def _create_running_session(store: Any) -> str:
    s = await store.sessions.create(agent_id="ag", agent_version=1)
    await store.sessions.update_status(s.id, "running")
    return s.id


async def test_heartbeat_start_takes_lock_and_stamps_meta(store: Any) -> None:
    sid = await _create_running_session(store)
    hb = WorkerHeartbeat(store.engine, sid, worker_id="w-1", interval_s=0.2, timeout_s=1.0)
    try:
        assert await hb.start() is True
        # First heartbeat is written synchronously inside start().
        row = await store.sessions.get(sid)
        assert row is not None
        assert "_heartbeat" in row.metadata
        assert row.metadata["_heartbeat"]["worker"] == "w-1"
    finally:
        await hb.stop()


async def test_heartbeat_double_start_raises(store: Any) -> None:
    sid = await _create_running_session(store)
    hb = WorkerHeartbeat(store.engine, sid, worker_id="w-1", interval_s=0.2)
    try:
        await hb.start()
        with pytest.raises(HeartbeatError):
            await hb.start()
    finally:
        await hb.stop()


async def test_second_worker_cannot_steal_lock(store: Any) -> None:
    sid = await _create_running_session(store)
    hb1 = WorkerHeartbeat(store.engine, sid, worker_id="w-1", interval_s=0.5)
    hb2 = WorkerHeartbeat(store.engine, sid, worker_id="w-2", interval_s=0.5)
    try:
        assert await hb1.start() is True
        # Lock held — second worker is rebuffed (no exception, returns False).
        assert await hb2.start() is False
    finally:
        await hb1.stop()
        await hb2.stop()


async def test_heartbeat_renews_periodically(store: Any) -> None:
    sid = await _create_running_session(store)
    hb = WorkerHeartbeat(store.engine, sid, worker_id="w-1", interval_s=0.1, timeout_s=1.0)
    try:
        assert await hb.start() is True
        first = (await store.sessions.get(sid)).metadata["_heartbeat"]["at"]
        # Sleep long enough that the renewal task fires twice.
        await asyncio.sleep(0.35)
        latest = (await store.sessions.get(sid)).metadata["_heartbeat"]["at"]
        assert latest != first, "heartbeat timestamp should advance"
    finally:
        await hb.stop()


async def test_detect_stale_returns_old_sessions(store: Any) -> None:
    """A session whose heartbeat is older than timeout is reported stale."""
    # Build a session with a deliberately old heartbeat.
    s = await store.sessions.create(agent_id="ag", agent_version=1)
    await store.sessions.update_status(s.id, "running")
    # Directly write an old heartbeat.
    from sqlalchemy import text

    async with store.engine.begin() as conn:
        await conn.execute(
            text(
                """
                UPDATE sessions
                SET meta = jsonb_set(meta, '{_heartbeat}',
                       '{"at":"2000-01-01T00:00:00+00:00","worker":"old"}'::jsonb,
                       true)
                WHERE id = :sid
                """
            ),
            {"sid": s.id},
        )
    stale = await WorkerHeartbeat.detect_stale(store.engine, timeout_s=1.0)
    assert s.id in stale


async def test_heartbeat_validation(store: Any) -> None:
    with pytest.raises(ValueError):
        WorkerHeartbeat(store.engine, "x", worker_id="w", interval_s=0)
    with pytest.raises(ValueError):
        WorkerHeartbeat(store.engine, "x", worker_id="w", interval_s=10, timeout_s=1)
