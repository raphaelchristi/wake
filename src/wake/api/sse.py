# ruff: noqa: B008, TC001, TC003, SIM105
"""Server-Sent Events streaming.

GET /v1/sessions/{id}/stream

Streams events for a session in real time. Supports reconnect via the
`Last-Event-ID` header (or the `since` query parameter) — clients resume by
asking for events with `seq > last_seen`.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from wake.api.dependencies import get_event_log, get_session_store, get_tenant_context
from wake.core.event_log import EventLog
from wake.store.base import SessionStore
from wake.tenancy import TenantContext
from wake.types import Event

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/v1/sessions", tags=["stream"])

# Override via WAKE_SSE_HEARTBEAT_S for tests.
HEARTBEAT_INTERVAL_S = float(os.getenv("WAKE_SSE_HEARTBEAT_S", "15.0"))


def _event_to_sse(ev: Event) -> dict[str, str]:
    return {
        "event": "event",
        "id": ev.id,
        "data": json.dumps(ev.model_dump(mode="json")),
    }


def _heartbeat() -> dict[str, str]:
    return {
        "event": "heartbeat",
        "data": json.dumps({"ts": datetime.now(UTC).isoformat()}),
    }


@router.get("/{session_id}/stream")
async def stream_session(
    session_id: str,
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    since: int | None = None,
    max_events: int | None = None,
    event_log: EventLog = Depends(get_event_log),
    session_store: SessionStore = Depends(get_session_store),
    tenant: TenantContext = Depends(get_tenant_context),
) -> EventSourceResponse:
    """Stream session events as SSE.

    Resume via either `Last-Event-ID` header or `since` query parameter.
    `max_events` (test-only convenience) closes the stream after N events have
    been yielded; production clients should rely on natural disconnection.
    """
    if await session_store.get(session_id, workspace_id=tenant.workspace_id) is None:
        raise HTTPException(status_code=404, detail="session not found")

    poll_interval = HEARTBEAT_INTERVAL_S

    async def _gen() -> AsyncIterator[dict[str, str]]:
        # Resolve resume point.
        cursor: int = since if since is not None else 0
        if last_event_id and since is None:
            history = await event_log.get(session_id, workspace_id=tenant.workspace_id)
            for ev in history:
                if ev.id == last_event_id:
                    cursor = ev.seq + 1
                    break

        emitted = 0

        # Replay anything the client missed first.
        backlog = await event_log.get(
            session_id,
            since=cursor,
            workspace_id=tenant.workspace_id,
        )
        for ev in backlog:
            yield _event_to_sse(ev)
            cursor = max(cursor, ev.seq + 1)
            emitted += 1
            if max_events is not None and emitted >= max_events:
                return

        # Live stream
        queue: asyncio.Queue[Event] = asyncio.Queue()

        async def _pump() -> None:
            try:
                subscription = await event_log.subscribe(
                    session_id,
                    workspace_id=tenant.workspace_id,
                )
                async for ev in subscription:
                    if ev.seq < cursor:
                        continue
                    await queue.put(ev)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("sse_pump_failed", session_id=session_id)

        pump_task = asyncio.create_task(_pump())
        try:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=poll_interval)
                except TimeoutError:
                    yield _heartbeat()
                    continue
                yield _event_to_sse(ev)
                cursor = max(cursor, ev.seq + 1)
                emitted += 1
                if max_events is not None and emitted >= max_events:
                    return
        except asyncio.CancelledError:
            return
        finally:
            pump_task.cancel()
            try:
                await pump_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    return EventSourceResponse(_gen())
