"""Tests for SessionDispatcher — adapter resolution + step execution."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

import pytest

from tests.unit.fakes import (
    InMemoryAgentStore,
    InMemoryEventStore,
    InMemorySessionStore,
)
from wake.adapters import AdapterRegistry, AdapterRegistryError, HarnessAdapter
from wake.adapters.base import LifecycleEvent
from wake.adapters.context import SessionContext
from wake.adapters.events import EventStream
from wake.adapters.tool_registry import ToolRegistry as AdapterToolRegistry
from wake.core.event_log import EventLog
from wake.runtime.dispatcher import DEFAULT_ADAPTER_NAME, SessionDispatcher
from wake.tools.registry import ToolRegistry as WakeToolsRegistry
from wake.types import Event, ModelConfig


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# A scriptable in-process adapter
# ---------------------------------------------------------------------------


class _ScriptedAdapter:
    """Minimal HarnessAdapter that emits a fixed list of events."""

    name = "scripted"
    version = "0.0.1"
    compatibility = "wake-harness-adapter@^0.1"

    def __init__(self, events: list[tuple[str, dict[str, Any]]]) -> None:
        self._scripted = events
        self.lifecycle_calls: list[LifecycleEvent] = []
        self.step_calls: list[SessionContext] = []

    async def step(  # type: ignore[no-untyped-def]
        self,
        ctx: SessionContext,
        events: EventStream,
        tools: AdapterToolRegistry,  # noqa: ARG002
    ) -> AsyncIterator[Event]:
        self.step_calls.append(ctx)
        for etype, payload in self._scripted:
            yield Event(
                id="",
                session_id=ctx.session_id,
                seq=-1,
                type=etype,  # type: ignore[arg-type]
                payload=payload,
                created_at=_now(),
            )

    async def on_lifecycle(self, ctx: SessionContext, event: LifecycleEvent) -> None:  # noqa: ARG002
        self.lifecycle_calls.append(event)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def event_log() -> EventLog:
    return EventLog(InMemoryEventStore())


@pytest.fixture
def adapter_registry() -> AdapterRegistry:
    return AdapterRegistry()


@pytest.fixture
def tools() -> WakeToolsRegistry:
    return WakeToolsRegistry()


# ---------------------------------------------------------------------------
# Adapter resolution
# ---------------------------------------------------------------------------


def test_resolve_adapter_name_default_when_no_metadata(
    adapter_registry: AdapterRegistry,
    event_log: EventLog,
    tools: WakeToolsRegistry,
) -> None:
    disp = SessionDispatcher(adapter_registry, event_log, tools)
    store = InMemoryAgentStore()

    async def _setup() -> str:
        agent = await store.create(name="a", model=ModelConfig(id="m"))
        return disp.resolve_adapter_name(agent)

    import asyncio

    name = asyncio.run(_setup())
    assert name == DEFAULT_ADAPTER_NAME


def test_resolve_adapter_name_from_agent_metadata(
    adapter_registry: AdapterRegistry,
    event_log: EventLog,
    tools: WakeToolsRegistry,
) -> None:
    disp = SessionDispatcher(adapter_registry, event_log, tools)
    store = InMemoryAgentStore()

    async def _setup() -> str:
        agent = await store.create(
            name="a",
            model=ModelConfig(id="m"),
            metadata={"harness": "langgraph"},
        )
        return disp.resolve_adapter_name(agent)

    import asyncio

    assert asyncio.run(_setup()) == "langgraph"


@pytest.mark.asyncio
async def test_unknown_adapter_raises(
    adapter_registry: AdapterRegistry,
    event_log: EventLog,
    tools: WakeToolsRegistry,
) -> None:
    """run_step propagates AdapterRegistryError when the name isn't registered."""
    disp = SessionDispatcher(adapter_registry, event_log, tools)
    agents = InMemoryAgentStore()
    sessions = InMemorySessionStore()
    agent = await agents.create(name="a", model=ModelConfig(id="m"))
    session = await sessions.create(agent_id=agent.id, agent_version=agent.version)

    with pytest.raises(AdapterRegistryError):
        await disp.run_step(session, agent)


# ---------------------------------------------------------------------------
# Run step
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_step_persists_each_emitted_event(
    adapter_registry: AdapterRegistry,
    event_log: EventLog,
    tools: WakeToolsRegistry,
) -> None:
    adapter = _ScriptedAdapter(
        [
            ("assistant.delta", {"index": 0, "delta": {"type": "text_delta", "text": "h"}}),
            ("assistant.delta", {"index": 0, "delta": {"type": "text_delta", "text": "i"}}),
            (
                "assistant.message",
                {"content": [{"type": "text", "text": "hi"}], "stop_reason": "end_turn"},
            ),
        ]
    )
    adapter_registry.register(adapter)
    disp = SessionDispatcher(
        adapter_registry, event_log, tools, default_adapter="scripted"
    )
    agents = InMemoryAgentStore()
    sessions = InMemorySessionStore()
    agent = await agents.create(name="a", model=ModelConfig(id="m"))
    session = await sessions.create(agent_id=agent.id, agent_version=agent.version)
    await event_log.append(
        session.id, "user.message", {"content": [{"type": "text", "text": "hi"}]}
    )

    await disp.run_step(session, agent)
    persisted = await event_log.get(session.id)
    types = [e.type for e in persisted]
    assert types == [
        "user.message",
        "assistant.delta",
        "assistant.delta",
        "assistant.message",
    ]
    # Dispatcher assigns sequential seqs (0..3) — placeholder seq=-1 is dropped.
    assert [e.seq for e in persisted] == [0, 1, 2, 3]
    # Dispatcher assigns real ULID ids, never empty strings.
    assert all(e.id for e in persisted)


@pytest.mark.asyncio
async def test_run_step_builds_session_context(
    adapter_registry: AdapterRegistry,
    event_log: EventLog,
    tools: WakeToolsRegistry,
) -> None:
    adapter = _ScriptedAdapter([])
    adapter_registry.register(adapter)
    disp = SessionDispatcher(
        adapter_registry, event_log, tools, default_adapter="scripted"
    )
    agents = InMemoryAgentStore()
    sessions = InMemorySessionStore()
    agent = await agents.create(
        name="a", model=ModelConfig(id="m"), metadata={"k": "v"}
    )
    session = await sessions.create(
        agent_id=agent.id,
        agent_version=agent.version,
        environment_id="env_1",
        metadata={"user_tag": "smoke"},
    )

    await disp.run_step(session, agent)
    assert len(adapter.step_calls) == 1
    ctx = adapter.step_calls[0]
    assert ctx.session_id == session.id
    assert ctx.agent_id == agent.id
    assert ctx.agent_version == agent.version
    assert ctx.environment_id == "env_1"
    assert ctx.metadata == {"user_tag": "smoke"}


@pytest.mark.asyncio
async def test_run_step_invokes_lifecycle_created_when_empty(
    adapter_registry: AdapterRegistry,
    event_log: EventLog,
    tools: WakeToolsRegistry,
) -> None:
    adapter = _ScriptedAdapter([])
    adapter_registry.register(adapter)
    disp = SessionDispatcher(
        adapter_registry, event_log, tools, default_adapter="scripted"
    )
    agents = InMemoryAgentStore()
    sessions = InMemorySessionStore()
    agent = await agents.create(name="a", model=ModelConfig(id="m"))
    session = await sessions.create(agent_id=agent.id, agent_version=agent.version)

    await disp.run_step(session, agent)
    assert adapter.lifecycle_calls == ["created"]


@pytest.mark.asyncio
async def test_run_step_invokes_lifecycle_resumed_when_history(
    adapter_registry: AdapterRegistry,
    event_log: EventLog,
    tools: WakeToolsRegistry,
) -> None:
    adapter = _ScriptedAdapter([])
    adapter_registry.register(adapter)
    disp = SessionDispatcher(
        adapter_registry, event_log, tools, default_adapter="scripted"
    )
    agents = InMemoryAgentStore()
    sessions = InMemorySessionStore()
    agent = await agents.create(name="a", model=ModelConfig(id="m"))
    session = await sessions.create(agent_id=agent.id, agent_version=agent.version)
    # Seed the log with a previous turn so count() > 1.
    await event_log.append(
        session.id, "user.message", {"content": [{"type": "text", "text": "first"}]}
    )
    await event_log.append(
        session.id,
        "assistant.message",
        {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"},
    )
    await event_log.append(
        session.id, "user.message", {"content": [{"type": "text", "text": "again"}]}
    )

    await disp.run_step(session, agent)
    assert adapter.lifecycle_calls == ["resumed"]


@pytest.mark.asyncio
async def test_run_step_swallows_lifecycle_exception(
    adapter_registry: AdapterRegistry,
    event_log: EventLog,
    tools: WakeToolsRegistry,
) -> None:
    """A misbehaving on_lifecycle does NOT abort step()."""

    class _BadLifecycleAdapter(_ScriptedAdapter):
        async def on_lifecycle(
            self, ctx: SessionContext, event: LifecycleEvent  # noqa: ARG002
        ) -> None:
            raise RuntimeError("boom")

    adapter = _BadLifecycleAdapter(
        [("assistant.message", {"content": [], "stop_reason": "end_turn"})]
    )
    adapter_registry.register(adapter)
    disp = SessionDispatcher(
        adapter_registry, event_log, tools, default_adapter="scripted"
    )
    agents = InMemoryAgentStore()
    sessions = InMemorySessionStore()
    agent = await agents.create(name="a", model=ModelConfig(id="m"))
    session = await sessions.create(agent_id=agent.id, agent_version=agent.version)

    await disp.run_step(session, agent)
    persisted = await event_log.get(session.id)
    assert any(e.type == "assistant.message" for e in persisted)


@pytest.mark.asyncio
async def test_dispatcher_protocol_check_on_registered_adapter(
    adapter_registry: AdapterRegistry,
    event_log: EventLog,
    tools: WakeToolsRegistry,  # noqa: ARG001
) -> None:
    """Registered adapters pass the runtime-checkable Protocol check."""
    adapter = _ScriptedAdapter([])
    adapter_registry.register(adapter)
    resolved = adapter_registry.get("scripted")
    assert isinstance(resolved, HarnessAdapter)
