"""Test fixtures: in-memory ``EventStream`` and ``ToolRegistry`` shared across
the adapter test modules.

We re-implement the fakes locally rather than importing from
``wake_test_conformance.harness`` so unit tests stay focused on the
adapter contract and don't depend on the conformance harness's
seeding logic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from wake.adapters import EventStream, SessionContext, ToolRegistry
from wake.types import (
    AgentConfig,
    Event,
    EventType,
    ModelConfig,
    TextBlock,
    ToolDescriptor,
    ToolResult,
)


def _now() -> datetime:
    return datetime.now(UTC)


class ListEventStream(EventStream):
    """``EventStream`` backed by a plain Python list (test only)."""

    def __init__(self, events: list[Event] | None = None) -> None:
        self._events: list[Event] = list(events or [])

    def append(self, event: Event) -> None:
        self._events.append(event)

    async def all(self) -> list[Event]:
        return list(self._events)

    async def since(self, seq: int) -> list[Event]:
        return [e for e in self._events if e.seq >= seq]

    async def latest(self, type: EventType | None = None) -> Event | None:  # noqa: A002
        if type is None:
            return self._events[-1] if self._events else None
        for e in reversed(self._events):
            if e.type == type:
                return e
        return None

    async def count(self) -> int:
        return len(self._events)


class RecordingToolRegistry(ToolRegistry):
    """Fake ToolRegistry that records every execute() call.

    Supports configurable per-tool responses; defaults to an echo-style
    body so tests don't have to provide responses for the happy path.
    """

    def __init__(
        self,
        descriptors: list[ToolDescriptor] | None = None,
        *,
        responses: dict[str, ToolResult] | None = None,
    ) -> None:
        self._descs: list[ToolDescriptor] = list(descriptors or [])
        self._responses: dict[str, ToolResult] = responses or {}
        self.calls: list[dict[str, Any]] = []

    def list(self) -> list[ToolDescriptor]:
        return list(self._descs)

    def get(self, name: str) -> ToolDescriptor:
        for d in self._descs:
            if d.name == name:
                return d
        raise KeyError(name)

    async def execute(
        self,
        name: str,
        input: dict[str, Any],  # noqa: A002
        *,
        tool_use_id: str,
    ) -> ToolResult:
        self.calls.append(
            {"name": name, "input": dict(input), "tool_use_id": tool_use_id}
        )
        if name in self._responses:
            return self._responses[name]
        return ToolResult(
            content=[TextBlock(text=f"echo:{input}")],
            is_error=False,
        )


def make_event(
    seq: int,
    etype: EventType,
    payload: dict[str, Any],
    *,
    session_id: str = "sess_test",
) -> Event:
    return Event(
        id=f"e{seq}",
        session_id=session_id,
        seq=seq,
        type=etype,
        payload=payload,
        created_at=_now(),
    )


def make_agent_config() -> AgentConfig:
    return AgentConfig(
        id="agent_test",
        name="test-agent",
        model=ModelConfig(id="pydantic-ai-test", provider="test"),
        system="You are a test agent.",
        created_at=_now(),
        updated_at=_now(),
    )


def make_session_context() -> SessionContext:
    return SessionContext(
        session_id="sess_test",
        agent_id="agent_test",
        agent_version=1,
        agent_config=make_agent_config(),
    )


async def drain_step(adapter: Any, stream: ListEventStream, tools: ToolRegistry) -> list[Event]:
    """Drive ``adapter.step`` to completion. Persists each emitted event
    back into the stream so subsequent step() calls see the new state
    (matches the runtime dispatcher's behaviour)."""
    emitted: list[Event] = []
    async for ev in adapter.step(make_session_context(), stream, tools):
        # Reassign seq to mimic the runtime appending into the log.
        new_ev = Event(
            id=f"e{await stream.count()}",
            session_id=ev.session_id,
            seq=await stream.count(),
            type=ev.type,
            payload=ev.payload,
            parent_id=ev.parent_id,
            metadata=ev.metadata,
            created_at=ev.created_at,
        )
        stream.append(new_ev)
        emitted.append(new_ev)
    return emitted
