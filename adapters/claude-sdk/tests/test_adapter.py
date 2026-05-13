"""Standalone tests for ClaudeSDKAdapter.

The adapter is exercised against a scripted mock Anthropic client and a
minimal in-memory EventStream/ToolRegistry. No network, no Wake runtime —
this is the package-level contract.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

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
from wake_adapter_claude_sdk import (
    MAX_RECURSION,
    ClaudeSDKAdapter,
    events_to_messages,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def ns(**kw: Any) -> SimpleNamespace:
    return SimpleNamespace(**kw)


# ---------------------------------------------------------------------------
# Mock Anthropic streaming client
# ---------------------------------------------------------------------------


class _ScriptedStream:
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
# In-memory EventStream / ToolRegistry fakes
# ---------------------------------------------------------------------------


class _ListEventStream(EventStream):
    """EventStream backed by a Python list (test-only)."""

    def __init__(self, events: list[Event] | None = None) -> None:
        self._events = list(events or [])

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


class _EchoToolRegistry(ToolRegistry):
    """ToolRegistry with one configurable echo-like tool (test-only)."""

    def __init__(
        self,
        descriptors: list[ToolDescriptor] | None = None,
        *,
        responses: dict[str, ToolResult] | None = None,
    ) -> None:
        self._descs = list(descriptors or [])
        self._responses = responses or {}
        self.calls: list[tuple[str, dict[str, Any], str]] = []

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
        self.calls.append((name, input, tool_use_id))
        if name in self._responses:
            return self._responses[name]
        return ToolResult(
            content=[TextBlock(text=str(input.get("text", "?")))],
            is_error=False,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agent() -> AgentConfig:
    return AgentConfig(
        id="agent_x",
        name="t",
        model=ModelConfig(id="claude-test"),
        system="be brief",
        created_at=_now(),
        updated_at=_now(),
    )


def _ctx() -> SessionContext:
    return SessionContext(
        session_id="sess_x",
        agent_id="agent_x",
        agent_version=1,
        agent_config=_agent(),
    )


def _text_only_script(text: str) -> list[SimpleNamespace]:
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


async def _collect(adapter: ClaudeSDKAdapter, events: _ListEventStream, tools: ToolRegistry) -> list[Event]:
    out: list[Event] = []
    async for ev in adapter.step(_ctx(), events, tools):
        # Mimic the runtime dispatcher: persist each event into the
        # backing stream so the recursive ``await events.all()`` sees it.
        events.append(ev)
        out.append(ev)
    return out


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_adapter_implements_protocol() -> None:
    """ClaudeSDKAdapter satisfies the runtime-checkable HarnessAdapter Protocol."""
    adapter = ClaudeSDKAdapter(client=_MockClient([]))
    assert isinstance(adapter, HarnessAdapter)


def test_adapter_identity_fields() -> None:
    adapter = ClaudeSDKAdapter(client=_MockClient([]))
    assert adapter.name == "claude-sdk"
    assert adapter.version == "0.1.0"
    assert adapter.compatibility == "wake-harness-adapter@^0.1"


def test_max_recursion_constant() -> None:
    assert MAX_RECURSION >= 1


# ---------------------------------------------------------------------------
# events_to_messages mapping
# ---------------------------------------------------------------------------


def _ev(seq: int, etype: EventType, payload: dict[str, Any]) -> Event:
    return Event(
        id=f"e{seq}",
        session_id="s",
        seq=seq,
        type=etype,
        payload=payload,
        created_at=_now(),
    )


def test_events_to_messages_user_assistant() -> None:
    events = [
        _ev(0, "user.message", {"content": [{"type": "text", "text": "hi"}]}),
        _ev(1, "assistant.message", {"content": [{"type": "text", "text": "yo"}]}),
    ]
    msgs = events_to_messages(events)
    assert msgs[0] == {"role": "user", "content": [{"type": "text", "text": "hi"}]}
    assert msgs[1] == {"role": "assistant", "content": [{"type": "text", "text": "yo"}]}


def test_events_to_messages_tool_use_and_result() -> None:
    events = [
        _ev(0, "user.message", {"content": [{"type": "text", "text": "hi"}]}),
        _ev(1, "assistant.message", {"content": []}),
        _ev(
            2,
            "tool_use",
            {"tool_use_id": "tu1", "name": "bash", "input": {"command": "ls"}},
        ),
        _ev(
            3,
            "tool_result",
            {
                "tool_use_id": "tu1",
                "content": [{"type": "text", "text": "files"}],
                "is_error": False,
            },
        ),
    ]
    msgs = events_to_messages(events)
    assert msgs[1]["role"] == "assistant"
    assert any(b.get("type") == "tool_use" for b in msgs[1]["content"])
    assert msgs[2]["role"] == "user"
    assert msgs[2]["content"][0]["type"] == "tool_result"


def test_events_to_messages_skips_status_and_delta() -> None:
    events = [
        _ev(0, "user.message", {"content": [{"type": "text", "text": "hi"}]}),
        _ev(1, "status", {"from": "idle", "to": "running"}),
        _ev(
            2,
            "assistant.delta",
            {"index": 0, "delta": {"type": "text_delta", "text": "x"}},
        ),
    ]
    msgs = events_to_messages(events)
    assert len(msgs) == 1


# ---------------------------------------------------------------------------
# Streaming + end_turn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_emits_delta_and_message_on_end_turn() -> None:
    client = _MockClient([_text_only_script("Hello!")])
    adapter = ClaudeSDKAdapter(client=client)
    stream = _ListEventStream(
        [_ev(0, "user.message", {"content": [{"type": "text", "text": "hi"}]})]
    )
    tools = _EchoToolRegistry()

    emitted = await _collect(adapter, stream, tools)

    types = [e.type for e in emitted]
    assert "assistant.delta" in types
    assert "assistant.message" in types
    final = next(e for e in emitted if e.type == "assistant.message")
    assert final.payload["content"] == [{"type": "text", "text": "Hello!"}]
    assert final.payload["stop_reason"] == "end_turn"


@pytest.mark.asyncio
async def test_step_passes_system_and_model_to_api() -> None:
    client = _MockClient([_text_only_script("ok")])
    adapter = ClaudeSDKAdapter(client=client)
    stream = _ListEventStream(
        [_ev(0, "user.message", {"content": [{"type": "text", "text": "x"}]})]
    )
    tools = _EchoToolRegistry()
    await _collect(adapter, stream, tools)

    call = client.messages.calls[0]
    assert call["system"] == "be brief"
    assert call["model"] == "claude-test"
    assert "tools" not in call


@pytest.mark.asyncio
async def test_step_renders_tools_for_messages_api() -> None:
    descs = [
        ToolDescriptor(
            name="echo",
            description="echo",
            schema={"type": "object"},
            requires_sandbox=False,
        ),
    ]
    client = _MockClient([_text_only_script("ok")])
    adapter = ClaudeSDKAdapter(client=client)
    stream = _ListEventStream(
        [_ev(0, "user.message", {"content": [{"type": "text", "text": "x"}]})]
    )
    tools = _EchoToolRegistry(descriptors=descs)

    await _collect(adapter, stream, tools)

    call = client.messages.calls[0]
    assert call["tools"] == [
        {
            "name": "echo",
            "description": "echo",
            "input_schema": {"type": "object"},
        }
    ]


# ---------------------------------------------------------------------------
# tool_use → tool_result → recurse
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_tool_use_then_end_turn() -> None:
    scripts = _tool_use_then_end(
        tool_id="tu_1",
        tool_name="echo",
        tool_input_json='{"text": "from_model"}',
        final_text="done",
    )
    client = _MockClient(scripts)
    adapter = ClaudeSDKAdapter(client=client)
    stream = _ListEventStream(
        [_ev(0, "user.message", {"content": [{"type": "text", "text": "echo"}]})]
    )
    tools = _EchoToolRegistry(
        descriptors=[
            ToolDescriptor(
                name="echo",
                description="echo",
                schema={"type": "object"},
            )
        ]
    )

    emitted = await _collect(adapter, stream, tools)
    types = [e.type for e in emitted]
    assert "tool_use" in types
    assert "tool_result" in types
    # Two assistant.message events: one per round.
    assert types.count("assistant.message") == 2
    # Adapter recursed → mock was called twice.
    assert len(client.messages.calls) == 2
    # Tool was actually invoked through ``tools.execute``.
    assert tools.calls == [("echo", {"text": "from_model"}, "tu_1")]


@pytest.mark.asyncio
async def test_step_tool_result_payload_carries_is_error_and_content() -> None:
    scripts = _tool_use_then_end("tu_1", "echo", '{"text":"x"}', "done")
    client = _MockClient(scripts)
    adapter = ClaudeSDKAdapter(client=client)
    stream = _ListEventStream(
        [_ev(0, "user.message", {"content": [{"type": "text", "text": "x"}]})]
    )
    tools = _EchoToolRegistry(
        descriptors=[ToolDescriptor(name="echo", description="", schema={})],
        responses={
            "echo": ToolResult(
                content=[TextBlock(text="oops")],
                is_error=True,
                error_code="bad_input",
            )
        },
    )

    emitted = await _collect(adapter, stream, tools)
    tr = next(e for e in emitted if e.type == "tool_result")
    assert tr.payload["tool_use_id"] == "tu_1"
    assert tr.payload["is_error"] is True
    assert tr.payload["error_code"] == "bad_input"
    assert tr.payload["content"][0]["text"] == "oops"


@pytest.mark.asyncio
async def test_step_unknown_tool_returns_not_found_result() -> None:
    scripts = _tool_use_then_end("tu_x", "missing", "{}", "ok")
    client = _MockClient(scripts)
    adapter = ClaudeSDKAdapter(client=client)
    stream = _ListEventStream(
        [_ev(0, "user.message", {"content": [{"type": "text", "text": "x"}]})]
    )
    # No matching descriptor and our echo registry returns a default echo, so
    # we tighten the assertion by configuring an explicit not_found response.
    tools = _EchoToolRegistry(
        responses={
            "missing": ToolResult(
                content=[TextBlock(text="unknown tool: missing")],
                is_error=True,
                error_code="not_found",
            )
        }
    )
    emitted = await _collect(adapter, stream, tools)
    tr = next(e for e in emitted if e.type == "tool_result")
    assert tr.payload["is_error"] is True
    assert tr.payload["error_code"] == "not_found"


# ---------------------------------------------------------------------------
# Recursion safety
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_max_recursion_guard_emits_error() -> None:
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
    client = _MockClient([one, one, one, one])
    adapter = ClaudeSDKAdapter(client=client, max_recursion=2)
    stream = _ListEventStream(
        [_ev(0, "user.message", {"content": [{"type": "text", "text": "go"}]})]
    )
    tools = _EchoToolRegistry(
        descriptors=[ToolDescriptor(name="echo", description="", schema={})]
    )

    emitted = await _collect(adapter, stream, tools)
    assert any(
        e.type == "error" and e.payload.get("error_type") == "max_recursion"
        for e in emitted
    )


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_lifecycle_is_noop() -> None:
    adapter = ClaudeSDKAdapter(client=_MockClient([]))
    # Should not raise and should return None for every lifecycle value.
    for lc in ("created", "resumed", "interrupted", "terminated"):
        assert await adapter.on_lifecycle(_ctx(), lc) is None  # type: ignore[arg-type]
