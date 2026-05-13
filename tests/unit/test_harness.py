"""Tests for the AnthropicHarness loop.

We mock the Anthropic streaming client. The test fixtures simulate the SDK's
event stream (content_block_*, message_delta with stop_reason, etc.).
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from tests.unit.fakes import (
    InMemoryAgentStore,
    InMemoryEventStore,
    InMemorySessionStore,
)
from wake.core.event_log import EventLog
from wake.harness.anthropic import AnthropicHarness, events_to_messages
from wake.tools.base import Tool
from wake.tools.registry import ToolRegistry
from wake.types import (
    AgentConfig,
    ModelConfig,
    SandboxHandle,
    Session,
    TextBlock,
    ToolDescriptor,
    ToolResult,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Mock Anthropic streaming client
# ---------------------------------------------------------------------------


def ns(**kw: Any) -> SimpleNamespace:
    return SimpleNamespace(**kw)


class _ScriptedStream:
    """Async context manager + async iterator over scripted SDK events."""

    def __init__(self, events: list[SimpleNamespace]) -> None:
        self._events = events

    async def __aenter__(self) -> "_ScriptedStream":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    def __aiter__(self) -> "_ScriptedStream":
        self._iter = iter(self._events)
        return self

    async def __anext__(self) -> SimpleNamespace:
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class _MockMessages:
    def __init__(self, scripts: list[list[SimpleNamespace]]) -> None:
        # `scripts` is a list of event-lists, one per call to `stream()`.
        self._scripts = list(scripts)
        self.calls: list[dict[str, Any]] = []

    def stream(self, **kwargs: Any) -> _ScriptedStream:
        self.calls.append(kwargs)
        events = self._scripts.pop(0) if self._scripts else []
        return _ScriptedStream(events)


class _MockClient:
    def __init__(self, scripts: list[list[SimpleNamespace]]) -> None:
        self.messages = _MockMessages(scripts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text_only_script(text: str) -> list[SimpleNamespace]:
    """A single text-only assistant response ending with end_turn."""
    return [
        ns(type="content_block_start", index=0, content_block=ns(type="text", text="")),
        ns(
            type="content_block_delta",
            index=0,
            delta=ns(type="text_delta", text=text),
        ),
        ns(type="content_block_stop", index=0),
        ns(type="message_delta", delta=ns(stop_reason="end_turn"), usage=None),
        ns(type="message_stop"),
    ]


def _tool_use_then_end(
    tool_id: str,
    tool_name: str,
    tool_input_json: str,
    final_text: str,
) -> list[list[SimpleNamespace]]:
    """Script that emits one tool_use then, on recursion, a final text + end_turn."""
    first = [
        ns(
            type="content_block_start",
            index=0,
            content_block=ns(type="tool_use", id=tool_id, name=tool_name, input={}),
        ),
        ns(
            type="content_block_delta",
            index=0,
            delta=ns(type="input_json_delta", partial_json=tool_input_json),
        ),
        ns(type="content_block_stop", index=0),
        ns(type="message_delta", delta=ns(stop_reason="tool_use"), usage=None),
        ns(type="message_stop"),
    ]
    second = _text_only_script(final_text)
    return [first, second]


async def _setup(scripts: list[list[SimpleNamespace]]) -> tuple[
    AnthropicHarness, EventLog, AgentConfig, Session, InMemoryEventStore
]:
    event_store = InMemoryEventStore()
    log = EventLog(event_store)
    sess_store = InMemorySessionStore()
    agent_store = InMemoryAgentStore()
    reg = ToolRegistry()

    agent = await agent_store.create(name="t", model=ModelConfig(id="claude-test"), system="be brief")
    session = await sess_store.create(agent_id=agent.id, agent_version=agent.version)

    client = _MockClient(scripts)
    harness = AnthropicHarness(event_log=log, tool_registry=reg, client=client)
    return harness, log, agent, session, event_store


# ---------------------------------------------------------------------------
# events_to_messages mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_events_to_messages_user_assistant() -> None:
    store = InMemoryEventStore()
    log = EventLog(store)
    await log.append("s", "user.message", {"content": [{"type": "text", "text": "hi"}]})
    await log.append("s", "assistant.message", {"content": [{"type": "text", "text": "yo"}]})
    events = await log.get("s")
    msgs = events_to_messages(events)
    assert msgs[0] == {"role": "user", "content": [{"type": "text", "text": "hi"}]}
    assert msgs[1] == {"role": "assistant", "content": [{"type": "text", "text": "yo"}]}


@pytest.mark.asyncio
async def test_events_to_messages_tool_use_and_result() -> None:
    store = InMemoryEventStore()
    log = EventLog(store)
    await log.append("s", "user.message", {"content": [{"type": "text", "text": "hi"}]})
    await log.append("s", "assistant.message", {"content": []})
    await log.append("s", "tool_use", {"tool_use_id": "tu1", "name": "bash", "input": {"command": "ls"}})
    await log.append(
        "s",
        "tool_result",
        {
            "tool_use_id": "tu1",
            "content": [{"type": "text", "text": "files"}],
            "is_error": False,
        },
    )
    msgs = events_to_messages(await log.get("s"))
    # Last assistant message contains the tool_use block
    assert msgs[1]["role"] == "assistant"
    assert any(b.get("type") == "tool_use" for b in msgs[1]["content"])
    # Next message is the tool_result wrapped as a user message
    assert msgs[2]["role"] == "user"
    assert msgs[2]["content"][0]["type"] == "tool_result"


@pytest.mark.asyncio
async def test_events_to_messages_skips_status_and_delta() -> None:
    store = InMemoryEventStore()
    log = EventLog(store)
    await log.append("s", "user.message", {"content": [{"type": "text", "text": "hi"}]})
    await log.append("s", "status", {"from": "idle", "to": "running"})
    await log.append("s", "assistant.delta", {"index": 0, "delta": {"type": "text_delta", "text": "x"}})
    msgs = events_to_messages(await log.get("s"))
    assert len(msgs) == 1


# ---------------------------------------------------------------------------
# Harness end_turn path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_step_end_turn_emits_message() -> None:
    harness, log, agent, sess, store = await _setup([_text_only_script("Hello!")])
    await log.append(sess.id, "user.message", {"content": [{"type": "text", "text": "hi"}]})
    await harness.run_step(sess, agent)

    events = await log.get(sess.id)
    types = [e.type for e in events]
    assert "assistant.delta" in types
    assert "assistant.message" in types
    final = [e for e in events if e.type == "assistant.message"][-1]
    assert final.payload["content"] == [{"type": "text", "text": "Hello!"}]
    assert final.payload["stop_reason"] == "end_turn"


@pytest.mark.asyncio
async def test_run_step_passes_system_and_tools_to_api() -> None:
    harness, log, agent, sess, store = await _setup([_text_only_script("yo")])
    await log.append(sess.id, "user.message", {"content": [{"type": "text", "text": "hi"}]})
    await harness.run_step(sess, agent)
    call = harness._client.messages.calls[0]
    assert call["system"] == "be brief"
    assert call["model"] == "claude-test"
    assert "tools" not in call  # registry is empty


# ---------------------------------------------------------------------------
# Harness tool_use → tool_result → recurse path
# ---------------------------------------------------------------------------


class _StubEcho(Tool):
    @property
    def descriptor(self) -> ToolDescriptor:
        return ToolDescriptor(
            name="echo",
            description="echo",
            schema={"type": "object", "properties": {"text": {"type": "string"}}},
            requires_sandbox=False,
        )

    async def execute(self, input: dict[str, Any], sandbox: SandboxHandle | None) -> ToolResult:
        return ToolResult(content=[TextBlock(text=str(input.get("text", "?")))])


@pytest.mark.asyncio
async def test_run_step_tool_use_then_end() -> None:
    scripts = _tool_use_then_end(
        tool_id="tu_1",
        tool_name="echo",
        tool_input_json='{"text": "from_model"}',
        final_text="done",
    )
    harness, log, agent, sess, store = await _setup(scripts)
    harness._tools.register(_StubEcho())
    await log.append(sess.id, "user.message", {"content": [{"type": "text", "text": "use echo"}]})

    await harness.run_step(sess, agent)

    events = await log.get(sess.id)
    types = [e.type for e in events]
    # Order: user, assistant.delta?, assistant.message, tool_use, tool_result, assistant.delta, assistant.message
    assert "tool_use" in types
    assert "tool_result" in types
    # Two assistant.message events (one per LLM round)
    assert types.count("assistant.message") == 2
    # Recursion happened (2 calls)
    assert len(harness._client.messages.calls) == 2

    tool_use_events = [e for e in events if e.type == "tool_use"]
    assert tool_use_events[0].payload == {"tool_use_id": "tu_1", "name": "echo", "input": {"text": "from_model"}}
    tool_result_events = [e for e in events if e.type == "tool_result"]
    assert tool_result_events[0].payload["tool_use_id"] == "tu_1"
    assert tool_result_events[0].payload["content"][0]["text"] == "from_model"


@pytest.mark.asyncio
async def test_run_step_tool_use_unknown_tool_returns_error_result() -> None:
    scripts = _tool_use_then_end("tu_x", "missing_tool", "{}", "ok")
    harness, log, agent, sess, store = await _setup(scripts)
    await log.append(sess.id, "user.message", {"content": [{"type": "text", "text": "x"}]})

    await harness.run_step(sess, agent)
    events = await log.get(sess.id)
    tr = [e for e in events if e.type == "tool_result"]
    assert len(tr) == 1
    assert tr[0].payload["is_error"]
    assert tr[0].payload.get("error_code") == "not_found"


@pytest.mark.asyncio
async def test_run_step_max_recursion_guard() -> None:
    # Each script is a "tool_use" round that triggers another. We'll only
    # supply 3 scripts and use max_recursion=2 so the harness halts.
    one = [
        ns(
            type="content_block_start",
            index=0,
            content_block=ns(type="tool_use", id="tu_loop", name="echo", input={}),
        ),
        ns(
            type="content_block_delta",
            index=0,
            delta=ns(type="input_json_delta", partial_json='{"text":"x"}'),
        ),
        ns(type="content_block_stop", index=0),
        ns(type="message_delta", delta=ns(stop_reason="tool_use"), usage=None),
        ns(type="message_stop"),
    ]

    event_store = InMemoryEventStore()
    log = EventLog(event_store)
    sess_store = InMemorySessionStore()
    agent_store = InMemoryAgentStore()
    reg = ToolRegistry()
    reg.register(_StubEcho())

    agent = await agent_store.create(name="t", model=ModelConfig(id="claude-test"))
    session = await sess_store.create(agent_id=agent.id, agent_version=agent.version)

    client = _MockClient([one, one, one, one])
    harness = AnthropicHarness(event_log=log, tool_registry=reg, client=client, max_recursion=2)
    await log.append(session.id, "user.message", {"content": [{"type": "text", "text": "go"}]})

    await harness.run_step(session, agent)
    events = await log.get(session.id)
    # Should bail with error after 2 rounds
    assert any(e.type == "error" and e.payload.get("error_type") == "max_recursion" for e in events)
