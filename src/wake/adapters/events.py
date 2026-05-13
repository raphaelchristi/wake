"""EventStream — read-only view over the session's event log for adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wake.types import Event, EventType


class EventStream(ABC):
    """Read-only access to the session's event log.

    The adapter never mutates the log directly; it emits events via
    ``step()`` return values and the runtime appends them.
    """

    @abstractmethod
    async def all(self) -> list[Event]:
        """Return all events in the session, in seq order."""
        ...

    @abstractmethod
    async def since(self, seq: int) -> list[Event]:
        """Return events with seq >= the given value."""
        ...

    @abstractmethod
    async def latest(
        self,
        type: EventType | None = None,  # noqa: A002 — matches docs/SPEC-HARNESS-ADAPTER.md
    ) -> Event | None:
        """Return the latest event of the given type, or the latest overall."""
        ...

    @abstractmethod
    async def count(self) -> int:
        """Return the total number of events in the session."""
        ...
