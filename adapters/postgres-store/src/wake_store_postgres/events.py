"""PostgresEventStore — append-only event log with LISTEN/NOTIFY.

Behaviourally identical to ``SQLiteEventStore`` (same seq allocation,
same ordering guarantees) but with two production-grade upgrades:

* ``append`` uses a serializable transaction + per-session advisory
  lock to serialise ``seq`` allocation across processes. SQLite gets
  away with an in-process asyncio lock; we need cross-process safety.
* ``subscribe`` uses LISTEN/NOTIFY on a dedicated asyncpg connection,
  falling back to the poll-based loop from SQLite if the channel goes
  away (e.g. connection drop, server restart). The polling fallback
  guarantees at-least-as-good semantics as the reference store.
"""

# Public method parameter ``id`` matches the ABC contract.
# ruff: noqa: A002

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from wake.store.base import EventStore, PurgeResult
from wake.tenancy import DEFAULT_ORGANIZATION_ID, DEFAULT_WORKSPACE_ID
from wake.types import Event, EventType

from wake_store_postgres._helpers import new_ulid, utcnow
from wake_store_postgres.models import EventRow

log = structlog.get_logger(__name__)


def _channel_name(session_id: str) -> str:
    """Compute the pg_notify channel name for a session.

    Postgres NAMEDATALEN caps channel names at 63 bytes. We use a
    deterministic 12-char prefix of the session_id (lowercased so
    LISTEN/NOTIFY case folding is a no-op). The trigger installed by
    the initial migration uses the same convention.
    """
    return "events_" + session_id[:12].lower()


def _row_to_event(row: EventRow) -> Event:
    return Event(
        id=row.id,
        organization_id=row.organization_id,
        workspace_id=row.workspace_id,
        session_id=row.session_id,
        seq=row.seq,
        type=row.type,  # type: ignore[arg-type]
        payload=row.payload,
        parent_id=row.parent_id,
        metadata=row.meta,
        created_at=row.created_at,
    )


class PostgresEventStore(EventStore):
    """Postgres-backed append-only event log."""

    # Polling fallback interval — used when LISTEN connection fails or
    # when the subscriber wakes up between NOTIFY arrivals.
    poll_interval_s: float = 0.1

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        engine: AsyncEngine,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._engine = engine

    async def append(
        self,
        session_id: str,
        event_type: EventType,
        payload: dict[str, Any],
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> Event:
        """Append an event, atomically allocating ``seq``.

        We take a transaction-scoped advisory lock keyed on
        ``hashtext(session_id)`` for the duration of the append so two
        concurrent writers can't both observe the same ``MAX(seq)``.
        ``pg_advisory_xact_lock`` is released automatically on commit/
        rollback — no manual unlock needed.
        """
        now = utcnow()
        event_id = new_ulid()
        async with self._sessionmaker() as s, s.begin():
            # Cross-process seq serialisation. Advisory locks are cheap
            # (~µs) and don't queue on the row, so this scales to high
            # contention better than SELECT ... FOR UPDATE on a session
            # parent row.
            await s.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:sid)::bigint)"),
                {"sid": session_id},
            )
            current_max = await s.scalar(
                select(func.max(EventRow.seq))
                .where(EventRow.session_id == session_id)
                .where(EventRow.workspace_id == workspace_id)
            )
            next_seq = 0 if current_max is None else int(current_max) + 1
            row = EventRow(
                id=event_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
                session_id=session_id,
                seq=next_seq,
                type=event_type,
                payload=payload,
                parent_id=parent_id,
                meta=metadata,
                created_at=now,
            )
            s.add(row)
        log.debug(
            "event.appended",
            session_id=session_id,
            event_id=event_id,
            seq=next_seq,
            event_type=event_type,
        )
        return Event(
            id=event_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
            session_id=session_id,
            seq=next_seq,
            type=event_type,
            payload=payload,
            parent_id=parent_id,
            metadata=metadata,
            created_at=now,
        )

    async def get(
        self,
        session_id: str,
        since: int = 0,
        *,
        workspace_id: str | None = None,
    ) -> list[Event]:
        async with self._sessionmaker() as s:
            stmt = (
                select(EventRow)
                .where(EventRow.session_id == session_id)
                .where(EventRow.seq >= since)
            )
            if workspace_id is not None:
                stmt = stmt.where(EventRow.workspace_id == workspace_id)
            rows = (await s.execute(stmt.order_by(EventRow.seq))).scalars().all()
        return [_row_to_event(r) for r in rows]

    async def get_one(self, event_id: str, *, workspace_id: str | None = None) -> Event | None:
        # Without the session_id we'd have to scan every partition.
        # ULIDs are globally unique so we just hit each partition via
        # the ``id`` column; the planner uses the per-partition btree.
        async with self._sessionmaker() as s:
            stmt = select(EventRow).where(EventRow.id == event_id)
            if workspace_id is not None:
                stmt = stmt.where(EventRow.workspace_id == workspace_id)
            row = (await s.execute(stmt)).scalar_one_or_none()
        return _row_to_event(row) if row else None

    async def subscribe(
        self,
        session_id: str,
        since: int = 0,
        *,
        workspace_id: str | None = None,
    ) -> AsyncIterator[Event]:
        return self._subscribe_impl(session_id, since, workspace_id=workspace_id)

    async def _subscribe_impl(
        self, session_id: str, since: int, *, workspace_id: str | None
    ) -> AsyncIterator[Event]:
        """LISTEN/NOTIFY-driven subscriber with a polling fallback.

        Yields backlog (``seq >= since``) first, then live events. If
        the dedicated LISTEN connection fails for any reason we drop
        back to polling — which is exactly how the SQLite reference
        store works.
        """
        cursor = since
        listen_queue: asyncio.Queue[str] = asyncio.Queue()
        listen_task = asyncio.create_task(self._listen_loop(session_id, listen_queue))
        try:
            while True:
                backlog = await self.get(
                    session_id,
                    since=cursor,
                    workspace_id=workspace_id,
                )
                for ev in backlog:
                    yield ev
                    cursor = ev.seq + 1
                # Wait for the NOTIFY queue (or poll-interval timeout).
                try:
                    await asyncio.wait_for(listen_queue.get(), timeout=self.poll_interval_s)
                except TimeoutError:
                    continue
        finally:
            listen_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await listen_task

    async def _listen_loop(self, session_id: str, queue: asyncio.Queue[str]) -> None:
        """Maintain a LISTEN connection and feed the polling subscriber.

        On any error we silently exit — the subscriber's outer loop
        keeps polling so this is a pure performance optimisation.
        """
        channel = _channel_name(session_id)
        try:
            # Reach into asyncpg directly: SQLAlchemy doesn't surface
            # connection.add_listener(). We borrow a connection from
            # the engine's raw pool.
            raw_conn = await self._engine.raw_connection()
            try:
                asyncpg_conn = raw_conn.driver_connection
                if asyncpg_conn is None:
                    return

                def _on_notify(_conn: Any, _pid: int, _channel: str, payload: str) -> None:
                    # Subscriber will catch up via the polling fallback
                    # if the queue is full — drop the notification.
                    with contextlib.suppress(asyncio.QueueFull):
                        queue.put_nowait(payload)

                await asyncpg_conn.add_listener(channel, _on_notify)
                try:
                    # Park here until cancelled.
                    while True:
                        await asyncio.sleep(3600)
                finally:
                    with contextlib.suppress(Exception):
                        await asyncpg_conn.remove_listener(channel, _on_notify)
            finally:
                # Release the raw connection back to the pool. SQLAlchemy
                # wraps it as PoolProxiedConnection.
                with contextlib.suppress(Exception):
                    raw_conn.close()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.debug(
                "subscribe.listen.failed_falling_back_to_poll",
                session_id=session_id,
                error=str(e),
            )

    async def count(self, session_id: str, *, workspace_id: str | None = None) -> int:
        async with self._sessionmaker() as s:
            stmt = (
                select(func.count()).select_from(EventRow).where(EventRow.session_id == session_id)
            )
            if workspace_id is not None:
                stmt = stmt.where(EventRow.workspace_id == workspace_id)
            n = await s.scalar(stmt)
        return int(n or 0)

    # ------------------------------------------------------------------
    # Retention helpers (Phase 7 — gap #5)
    # ------------------------------------------------------------------

    async def _delete_events(
        self,
        event_ids: list[str],
        *,
        workspace_id: str | None = None,
    ) -> int:
        if not event_ids:
            return 0
        async with self._sessionmaker() as s, s.begin():
            stmt = delete(EventRow).where(EventRow.id.in_(event_ids))
            if workspace_id is not None:
                stmt = stmt.where(EventRow.workspace_id == workspace_id)
            result = await s.execute(stmt)
        return int(result.rowcount or 0)

    async def iter_for_archive(
        self,
        cutoff: datetime,
        *,
        workspace_id: str | None = None,
        batch_size: int = 1000,
    ) -> AsyncIterator[list[Event]]:
        return self._iter_for_archive_impl(
            cutoff, workspace_id=workspace_id, batch_size=batch_size
        )

    async def _iter_for_archive_impl(
        self,
        cutoff: datetime,
        *,
        workspace_id: str | None,
        batch_size: int,
    ) -> AsyncIterator[list[Event]]:
        offset = 0
        while True:
            async with self._sessionmaker() as s:
                stmt = (
                    select(EventRow)
                    .where(EventRow.created_at < cutoff)
                    .order_by(EventRow.session_id, EventRow.seq)
                    .limit(batch_size)
                    .offset(offset)
                )
                if workspace_id is not None:
                    stmt = stmt.where(EventRow.workspace_id == workspace_id)
                rows = (await s.execute(stmt)).scalars().all()
            if not rows:
                return
            yield [_row_to_event(r) for r in rows]
            if len(rows) < batch_size:
                return
            offset += len(rows)

    async def purge_before(
        self,
        cutoff: datetime,
        *,
        workspace_id: str | None = None,
        dry_run: bool = False,
        batch_size: int = 1000,
    ) -> PurgeResult:
        async with self._sessionmaker() as s:
            count_stmt = select(func.count()).select_from(EventRow).where(
                EventRow.created_at < cutoff
            )
            if workspace_id is not None:
                count_stmt = count_stmt.where(EventRow.workspace_id == workspace_id)
            total = int(await s.scalar(count_stmt) or 0)
        if dry_run or total == 0:
            return PurgeResult(deleted=total, dry_run=dry_run)
        deleted = 0
        while deleted < total:
            async with self._sessionmaker() as s, s.begin():
                # Postgres supports DELETE ... USING but with hash
                # partitioning we just use a CTE: select ids first,
                # delete by id-in. Keeps the plan obvious + portable.
                id_stmt = (
                    select(EventRow.id)
                    .where(EventRow.created_at < cutoff)
                    .limit(batch_size)
                )
                if workspace_id is not None:
                    id_stmt = id_stmt.where(EventRow.workspace_id == workspace_id)
                ids = (await s.execute(id_stmt)).scalars().all()
                if not ids:
                    break
                del_stmt = delete(EventRow).where(EventRow.id.in_(list(ids)))
                if workspace_id is not None:
                    del_stmt = del_stmt.where(EventRow.workspace_id == workspace_id)
                result = await s.execute(del_stmt)
                deleted += int(result.rowcount or 0)
        return PurgeResult(deleted=deleted, dry_run=False)


__all__ = ["PostgresEventStore"]
