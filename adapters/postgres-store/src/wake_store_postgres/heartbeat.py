"""WorkerHeartbeat — renewable session lease backed by advisory locks.

Multi-worker scheduling story
-----------------------------

When a worker picks up a session it must:

1. Take ``pg_try_advisory_lock(hashtext(session_id))`` on a dedicated
   connection (``locks.acquire_session_lock``).
2. Periodically write ``_heartbeat`` (a UTC timestamp) into
   ``sessions.meta`` so other workers can observe liveness without
   touching the lock itself.

If the worker crashes the connection drops and Postgres releases the
lock automatically (no cleanup needed). Other workers can then retry
the advisory lock and resume the session.

The 30 s watchdog requirement is satisfied by two layers:

* Advisory-lock acquisition itself is sub-millisecond and instantly
  detects a freed lock (no waiting period).
* ``WorkerHeartbeat.detect_stale`` scans ``sessions.meta`` for
  heartbeats older than the configured timeout — useful when a worker
  is *hung* (connection still alive but unable to make progress).
  Operators can use it as a kill-switch input.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from wake_store_postgres.locks import (
    acquire_session_lock,
    release_session_lock,
)

log = structlog.get_logger(__name__)


_DEFAULT_INTERVAL_S = float(os.environ.get("WAKE_PG_HEARTBEAT_INTERVAL_S", "10"))
_DEFAULT_TIMEOUT_S = float(os.environ.get("WAKE_PG_HEARTBEAT_TIMEOUT_S", "30"))


class HeartbeatError(Exception):
    """Raised when the heartbeat task fails to start or sustain itself."""


class WorkerHeartbeat:
    """Background task that keeps a session lock alive.

    Usage::

        hb = WorkerHeartbeat(engine, session_id, worker_id)
        await hb.start()
        try:
            ...  # do work
        finally:
            await hb.stop()
    """

    def __init__(
        self,
        engine: AsyncEngine,
        session_id: str,
        worker_id: str,
        *,
        interval_s: float = _DEFAULT_INTERVAL_S,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        if interval_s <= 0:
            raise ValueError("interval_s must be positive")
        if timeout_s < interval_s:
            raise ValueError("timeout_s must be >= interval_s")
        self.engine = engine
        self.session_id = session_id
        self.worker_id = worker_id
        self.interval_s = interval_s
        self.timeout_s = timeout_s
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._conn: Any = None
        self._acquired = False

    async def start(self) -> bool:
        """Acquire the lock + start the renewal task.

        Returns ``True`` on success, ``False`` if the lock is held by
        another worker (caller may retry later).
        """
        if self._task is not None:
            raise HeartbeatError("heartbeat already started")
        # Open a dedicated connection so the advisory lock stays put.
        self._conn = await self.engine.connect()
        acquired = await acquire_session_lock(self.engine, self.session_id, connection=self._conn)
        if not acquired:
            await self._conn.close()
            self._conn = None
            log.info(
                "heartbeat.start.contested",
                session_id=self.session_id,
                worker_id=self.worker_id,
            )
            return False
        self._acquired = True
        # First heartbeat row before kicking off the loop so peers see a
        # non-stale value immediately.
        await self._write_heartbeat()
        self._stop.clear()
        self._task = asyncio.create_task(self._run())
        log.info(
            "heartbeat.start.ok",
            session_id=self.session_id,
            worker_id=self.worker_id,
            interval_s=self.interval_s,
        )
        return True

    async def stop(self) -> None:
        """Stop the renewal task + release the lock."""
        if self._task is None:
            return
        self._stop.set()
        try:
            await asyncio.wait_for(self._task, timeout=self.interval_s + 5)
        except TimeoutError:
            self._task.cancel()
        self._task = None
        if self._conn is not None and self._acquired:
            try:
                await release_session_lock(self.engine, self.session_id, connection=self._conn)
            except Exception as e:
                log.warning(
                    "heartbeat.release.failed",
                    session_id=self.session_id,
                    error=str(e),
                )
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
        self._acquired = False
        log.info(
            "heartbeat.stop",
            session_id=self.session_id,
            worker_id=self.worker_id,
        )

    async def _run(self) -> None:
        """Background renewal loop."""
        while not self._stop.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_s)
            if self._stop.is_set():
                break
            try:
                await self._write_heartbeat()
            except Exception as e:
                log.warning(
                    "heartbeat.renew.failed",
                    session_id=self.session_id,
                    worker_id=self.worker_id,
                    error=str(e),
                )

    async def _write_heartbeat(self) -> None:
        """Stamp ``sessions.meta`` with the current UTC timestamp.

        We don't use the per-worker connection for the update so the
        write happens against the pool — keeping the long-lived
        connection idle (and the lock unbothered) most of the time.
        """
        now = datetime.now(UTC).isoformat()
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    UPDATE sessions
                    SET meta = jsonb_set(
                            COALESCE(meta, '{}'::jsonb),
                            '{_heartbeat}',
                            to_jsonb(:hb)::jsonb,
                            true
                        ),
                        updated_at = NOW()
                    WHERE id = :sid
                    """
                ),
                {"hb": {"at": now, "worker": self.worker_id}, "sid": self.session_id},
            )

    # ------------------------------------------------------------------ static

    @staticmethod
    async def detect_stale(
        engine: AsyncEngine,
        *,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> list[str]:
        """Return session ids whose last heartbeat is older than ``timeout_s``.

        Useful for a periodic watchdog task: any session that no
        worker has heartbeat'd within the timeout is a candidate for
        reschedule. Returns an empty list if nothing's stale.
        """
        cutoff = (datetime.now(UTC) - timedelta(seconds=timeout_s)).isoformat()
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT id
                    FROM sessions
                    WHERE meta ? '_heartbeat'
                      AND (meta->'_heartbeat'->>'at') < :cutoff
                      AND status IN ('running', 'rescheduling')
                    ORDER BY (meta->'_heartbeat'->>'at')
                    """
                ),
                {"cutoff": cutoff},
            )
            return [row[0] for row in result.fetchall()]


__all__ = ["WorkerHeartbeat", "HeartbeatError"]
