# STUB: foundation agent will replace this during merge
"""Stub thin wrapper around EventStore.

Foundation agent provides the real implementation.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from wake.store.base import EventStore
from wake.types import Event, EventType


class EventLog:
    """Thin facade over an EventStore for in-process callers.

    Final implementation owned by foundation agent.
    """

    def __init__(self, store: EventStore) -> None:
        self._store = store

    async def append(
        self,
        session_id: str,
        event_type: EventType,
        payload: dict[str, Any],
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Event:
        return await self._store.append(
            session_id, event_type, payload, parent_id=parent_id, metadata=metadata
        )

    async def get(self, session_id: str, since: int = 0) -> list[Event]:
        return await self._store.get(session_id, since=since)

    def subscribe(self, session_id: str) -> AsyncIterator[Event]:
        return self._store.subscribe(session_id)

    async def count(self, session_id: str) -> int:
        return await self._store.count(session_id)
