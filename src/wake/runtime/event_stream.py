"""Concrete ``EventStream`` that wraps Wake's ``EventLog`` for adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING

from wake.adapters.events import EventStream

if TYPE_CHECKING:
    from wake.core.event_log import EventLog
    from wake.types import Event, EventType


class WakeEventStream(EventStream):
    """Read-only view scoped to a single Wake session.

    Adapters never mutate the log directly — they yield events from
    ``step()`` and the ``SessionDispatcher`` persists them. This view
    only exposes read methods, satisfying the ``EventStream`` ABC.
    """

    def __init__(self, event_log: EventLog, session_id: str) -> None:
        self._event_log = event_log
        self._session_id = session_id

    async def all(self) -> list[Event]:
        return await self._event_log.get(self._session_id)

    async def since(self, seq: int) -> list[Event]:
        return await self._event_log.get(self._session_id, since=seq)

    async def latest(self, type: EventType | None = None) -> Event | None:  # noqa: A002
        events = await self._event_log.get(self._session_id)
        if type is None:
            return events[-1] if events else None
        for ev in reversed(events):
            if ev.type == type:
                return ev
        return None

    async def count(self) -> int:
        return await self._event_log.count(self._session_id)
