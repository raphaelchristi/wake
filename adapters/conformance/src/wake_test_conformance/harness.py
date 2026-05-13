"""TestHarness — builds an in-memory environment for a HarnessAdapter.

Scenarios use this harness to:

- seed a session with synthetic user/tool events
- expose a ``SessionContext`` with a fake AgentConfig
- expose an ``EventStream`` view over an in-memory event store
- expose a ``ToolRegistry`` with pre-registered fake tools
- drive ``adapter.step()`` and collect emissions

Everything is in-memory, fully deterministic, and zero network. Adapters
under test are responsible for being deterministic on their own end (e.g.
a fake LLM client, or an echo-style adapter).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from ulid import ULID
from wake.adapters import (
    EventStream,
    HarnessAdapter,
    SessionContext,
    ToolRegistry,
)
from wake.types import (
    AgentConfig,
    Event,
    EventType,
    ModelConfig,
    TextBlock,
    ToolDescriptor,
    ToolResult,
)

ToolImpl = Callable[[dict[str, Any]], Awaitable[ToolResult]]
"""Async callable that takes a tool input dict and returns a ToolResult."""


def _now() -> datetime:
    return datetime.now(UTC)


def _make_agent_config(
    *,
    name: str = "conformance-test-agent",
    system: str | None = "You are a test agent.",
    metadata: dict[str, str] | None = None,
) -> AgentConfig:
    return AgentConfig(
        id=f"agent_{ULID()}",
        name=name,
        model=ModelConfig(id="claude-test", speed="standard", provider="anthropic"),
        system=system,
        tools=[],
        mcp_servers=[],
        skills=[],
        description="conformance-test fake agent",
        metadata=metadata or {},
        version=1,
        created_at=_now(),
        updated_at=_now(),
    )


class InMemoryEventStore:
    """Minimal append-only event store, scoped to a single session.

    This is intentionally NOT the foundation's EventStore — the conformance
    package ships its own minimal copy to avoid coupling to test helpers
    that live outside the installable package.
    """

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._events: list[Event] = []

    async def append(
        self,
        type: EventType,
        payload: dict[str, Any],
        *,
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Event:
        ev = Event(
            id=str(ULID()),
            session_id=self.session_id,
            seq=len(self._events),
            type=type,
            payload=payload,
            parent_id=parent_id,
            metadata=metadata,
            created_at=_now(),
        )
        self._events.append(ev)
        return ev

    @property
    def events(self) -> list[Event]:
        return list(self._events)


class _StreamView(EventStream):  # type: ignore[misc]
    """Read-only view of an InMemoryEventStore."""

    def __init__(self, store: InMemoryEventStore) -> None:
        self._store = store

    async def all(self) -> list[Event]:
        return self._store.events

    async def since(self, seq: int) -> list[Event]:
        return [e for e in self._store.events if e.seq >= seq]

    async def latest(self, type: EventType | None = None) -> Event | None:
        events = self._store.events
        if type is None:
            return events[-1] if events else None
        for e in reversed(events):
            if e.type == type:
                return e
        return None

    async def count(self) -> int:
        return len(self._store.events)


class InMemoryToolRegistry(ToolRegistry):  # type: ignore[misc]
    """Registry of fake tools. Records every execute() call for assertions."""

    def __init__(self) -> None:
        self._tools: dict[str, tuple[ToolDescriptor, ToolImpl]] = {}
        self.calls: list[dict[str, Any]] = []
        """Append-only log of (name, input, tool_use_id) for assertions."""

    def add(
        self,
        name: str,
        impl: ToolImpl,
        *,
        description: str = "fake tool",
        schema: dict[str, Any] | None = None,
        requires_sandbox: bool = False,
    ) -> ToolDescriptor:
        desc = ToolDescriptor(
            name=name,
            description=description,
            schema=schema or {"type": "object", "properties": {}},
            requires_sandbox=requires_sandbox,
        )
        self._tools[name] = (desc, impl)
        return desc

    def list(self) -> list[ToolDescriptor]:
        return [d for d, _ in self._tools.values()]

    def get(self, name: str) -> ToolDescriptor:
        try:
            return self._tools[name][0]
        except KeyError as e:
            raise KeyError(f"tool not registered: {name!r}") from e

    async def execute(
        self,
        name: str,
        input: dict[str, Any],
        *,
        tool_use_id: str,
    ) -> ToolResult:
        self.calls.append(
            {"name": name, "input": input, "tool_use_id": tool_use_id}
        )
        if name not in self._tools:
            return ToolResult(
                content=[TextBlock(text=f"tool {name!r} not found")],
                is_error=True,
                error_code="not_found",
            )
        _, impl = self._tools[name]
        return await impl(input)


class TestHarness:
    """Sets up everything needed to invoke a HarnessAdapter step.

    Typical scenario flow::

        harness = TestHarness()
        await harness.inject_user_message("say ok")
        events = await harness.run_step(adapter)
        assert any(e.type == "assistant.message" for e in events)
    """

    def __init__(
        self,
        *,
        session_id: str | None = None,
        agent_config: AgentConfig | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        self.session_id = session_id or f"sess_{ULID()}"
        self.agent_config = agent_config or _make_agent_config()
        self.store = InMemoryEventStore(self.session_id)
        self.events: EventStream = _StreamView(self.store)
        self.tools = InMemoryToolRegistry()
        self.context = SessionContext(
            session_id=self.session_id,
            agent_id=self.agent_config.id,
            agent_version=self.agent_config.version,
            agent_config=self.agent_config,
            environment_id=None,
            sandbox=None,
            vault_id=None,
            metadata=metadata or {},
        )

    # ------------------------------------------------------------------
    # event seeding
    # ------------------------------------------------------------------

    async def inject_user_message(self, text: str) -> Event:
        """Append a `user.message` with a single text block to the log."""
        return await self.store.append(
            "user.message",
            {"content": [{"type": "text", "text": text}]},
        )

    async def inject_event(
        self,
        type: EventType,
        payload: dict[str, Any],
        *,
        parent_id: str | None = None,
    ) -> Event:
        """Append an arbitrary event (e.g. tool_use, tool_result) to the log."""
        return await self.store.append(type, payload, parent_id=parent_id)

    # ------------------------------------------------------------------
    # adapter invocation
    # ------------------------------------------------------------------

    async def run_step(
        self,
        adapter: HarnessAdapter,
        *,
        timeout: float = 5.0,
        persist: bool = True,
    ) -> list[Event]:
        """Drain ``adapter.step()`` to completion. Returns emitted events.

        Each emitted event is appended to the event store (simulating
        runtime persistence) so subsequent ``step()`` calls see them via
        the EventStream — matching the production contract.
        """
        emitted: list[Event] = []

        async def _drain() -> None:
            async for ev in adapter.step(self.context, self.events, self.tools):
                emitted.append(ev)
                if persist:
                    # Re-emit into our store so that further step() calls
                    # observe the new log state.
                    await self.store.append(
                        ev.type,
                        ev.payload,
                        parent_id=ev.parent_id,
                        metadata=ev.metadata,
                    )

        await asyncio.wait_for(_drain(), timeout=timeout)
        return emitted

    async def stream_step(
        self,
        adapter: HarnessAdapter,
    ) -> AsyncIterator[Event]:
        """Yield events from ``adapter.step()`` as they arrive (no persistence).

        Useful for scenarios that need to react to events mid-stream
        (e.g. cancellation).
        """
        async for ev in adapter.step(self.context, self.events, self.tools):
            yield ev
