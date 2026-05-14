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
from typing import Any

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from wake.store.base import EventStore
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


def _ensure_metadata_with_key(
    metadata: dict[str, Any] | None, idempotency_key: str | None
) -> dict[str, Any] | None:
    """Mirror ``idempotency_key`` into the persisted metadata payload.

    Wake stores the dedupe signal in two places: the dedicated column
    (driving the UNIQUE index) and the ``meta`` JSONB so observability
    tools can recover the key from the event row without joining.
    The mirror is one-way: if the caller already passed
    ``metadata["idempotency_key"]`` we trust it.
    """
    if idempotency_key is None:
        return metadata
    out = dict(metadata or {})
    out.setdefault("idempotency_key", idempotency_key)
    return out


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
        *,
        idempotency_key: str | None = None,
    ) -> Event:
        """Append an event, atomically allocating ``seq``.

        We take a transaction-scoped advisory lock keyed on
        ``hashtext(session_id)`` for the duration of the append so two
        concurrent writers can't both observe the same ``MAX(seq)``.
        ``pg_advisory_xact_lock`` is released automatically on commit/
        rollback — no manual unlock needed.

        Phase 7 idempotency (Tier 1 gap #4): when ``idempotency_key``
        is set we look the key up first under the held advisory lock
        and return the existing event if a duplicate is detected. The
        UNIQUE partial index installed by migration 0004 enforces the
        invariant at the storage layer; the pre-check just lets us
        return the dedupe target without surfacing the integrity
        error to callers.
        """
        now = utcnow()
        event_id = new_ulid()
        meta = _ensure_metadata_with_key(metadata, idempotency_key)
        async with self._sessionmaker() as s, s.begin():
            # Cross-process seq serialisation. Advisory locks are cheap
            # (~µs) and don't queue on the row, so this scales to high
            # contention better than SELECT ... FOR UPDATE on a session
            # parent row.
            await s.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:sid)::bigint)"),
                {"sid": session_id},
            )
            if idempotency_key is not None:
                existing = await s.scalar(
                    select(EventRow)
                    .where(EventRow.workspace_id == workspace_id)
                    .where(EventRow.session_id == session_id)
                    .where(EventRow.idempotency_key == idempotency_key)
                    .limit(1)
                )
                if existing is not None:
                    log.debug(
                        "event.append.idempotent_dedupe",
                        session_id=session_id,
                        idempotency_key=idempotency_key,
                        existing_id=existing.id,
                    )
                    return _row_to_event(existing)
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
                meta=meta,
                idempotency_key=idempotency_key,
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
            metadata=meta,
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


__all__ = ["PostgresEventStore"]
