"""Concrete ``EventStream`` that wraps Wake's ``EventLog`` for adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING

from wake.adapters.events import EventStream
from wake.tenancy import DEFAULT_ORGANIZATION_ID, DEFAULT_WORKSPACE_ID

if TYPE_CHECKING:
    from wake.core.event_log import EventLog
    from wake.types import Event, EventType


class WakeEventStream(EventStream):
    """Read-only view scoped to a single Wake session AND tenant.

    Adapters never mutate the log directly — they yield events from
    ``step()`` and the ``SessionDispatcher`` persists them. This view
    only exposes read methods, satisfying the ``EventStream`` ABC.

    Phase 6.1 finding #2: the stream now carries
    ``organization_id`` / ``workspace_id`` so the underlying store
    filters reads by tenant. Without this, an adapter running in
    workspace A could see (or replay into) events leaked from another
    tenant via a shared ``EventLog``.
    """

    def __init__(
        self,
        event_log: EventLog,
        session_id: str,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> None:
        self._event_log = event_log
        self._session_id = session_id
        self._organization_id = organization_id
        self._workspace_id = workspace_id

    async def all(self) -> list[Event]:
        return await self._event_log.get(
            self._session_id, workspace_id=self._workspace_id
        )

    async def since(self, seq: int) -> list[Event]:
        return await self._event_log.get(
            self._session_id, since=seq, workspace_id=self._workspace_id
        )

    async def latest(self, type: EventType | None = None) -> Event | None:  # noqa: A002
        events = await self._event_log.get(
            self._session_id, workspace_id=self._workspace_id
        )
        if type is None:
            return events[-1] if events else None
        for ev in reversed(events):
            if ev.type == type:
                return ev
        return None

    async def count(self) -> int:
        return await self._event_log.count(
            self._session_id, workspace_id=self._workspace_id
        )
