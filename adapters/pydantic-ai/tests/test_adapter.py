"""Core PydanticAIAdapter tests.

Exercise the adapter against ``TestModel`` (no network, deterministic).
Tests cover:

* Protocol conformance (``isinstance``, identity fields)
* Basic step() loop emits assistant.delta + assistant.message
* Idempotent resume (no re-emission when latest event is already an
  assistant.message)
* No-op when the log has no user.message
* events_to_message_history mapping (events ↔ ModelMessage)
"""

from __future__ import annotations

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.test import TestModel
from wake_adapter_pydantic_ai import (
    MAX_RECURSION,
    PydanticAIAdapter,
    events_to_message_history,
)

from wake.adapters import HarnessAdapter

from .conftest import (
    ListEventStream,
    RecordingToolRegistry,
    drain_step,
    make_event,
    make_session_context,
)

# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_adapter_implements_protocol() -> None:
    agent = Agent(TestModel())
    adapter = PydanticAIAdapter(agent)
    assert isinstance(adapter, HarnessAdapter)


def test_adapter_identity_fields() -> None:
    agent = Agent(TestModel())
    adapter = PydanticAIAdapter(agent)
    assert adapter.name == "pydantic-ai"
    assert adapter.version == "0.1.0"
    assert adapter.compatibility == "wake-harness-adapter@^0.1"


def test_max_recursion_constant_positive() -> None:
    assert MAX_RECURSION >= 1


# ---------------------------------------------------------------------------
# events_to_message_history
# ---------------------------------------------------------------------------


def test_events_to_message_history_user_and_assistant() -> None:
    events = [
        make_event(0, "user.message", {"content": [{"type": "text", "text": "hi"}]}),
        make_event(
            1, "assistant.message", {"content": [{"type": "text", "text": "yo"}]}
        ),
    ]
    history = events_to_message_history(events)
    assert len(history) == 2
    assert isinstance(history[0], ModelRequest)
    assert isinstance(history[0].parts[0], UserPromptPart)
    assert history[0].parts[0].content == "hi"
    assert isinstance(history[1], ModelResponse)
    assert isinstance(history[1].parts[0], TextPart)
    assert history[1].parts[0].content == "yo"


def test_events_to_message_history_tool_use_and_result() -> None:
    events = [
        make_event(0, "user.message", {"content": [{"type": "text", "text": "hi"}]}),
        make_event(
            1, "assistant.message", {"content": [{"type": "text", "text": "let me check"}]}
        ),
        make_event(
            2,
            "tool_use",
            {"tool_use_id": "tu1", "name": "echo", "input": {"text": "hello"}},
        ),
        make_event(
            3,
            "tool_result",
            {
                "tool_use_id": "tu1",
                "content": [{"type": "text", "text": "echo:hello"}],
                "is_error": False,
            },
        ),
    ]
    history = events_to_message_history(events)
    # We expect: ModelRequest(user), ModelResponse(text+tool_call), ModelRequest(tool_return)
    assert isinstance(history[0], ModelRequest)
    assert isinstance(history[1], ModelResponse)
    # tool_use was appended onto the existing ModelResponse:
    parts1 = list(history[1].parts)
    assert any(isinstance(p, TextPart) for p in parts1)
    assert any(isinstance(p, ToolCallPart) for p in parts1)
    tc = next(p for p in parts1 if isinstance(p, ToolCallPart))
    assert tc.tool_name == "echo"
    assert tc.tool_call_id == "tu1"
    assert tc.args == {"text": "hello"}
    # tool_result became a new ModelRequest:
    assert isinstance(history[2], ModelRequest)
    tr = history[2].parts[0]
    assert isinstance(tr, ToolReturnPart)
    assert tr.tool_call_id == "tu1"
    assert tr.tool_name == "echo"
    assert tr.outcome == "success"


def test_events_to_message_history_skips_non_canonical() -> None:
    events = [
        make_event(0, "user.message", {"content": [{"type": "text", "text": "hi"}]}),
        make_event(1, "status", {"from": "idle", "to": "running"}),
        make_event(
            2,
            "assistant.delta",
            {"delta": {"type": "text_delta", "text": "x"}},
        ),
    ]
    history = events_to_message_history(events)
    assert len(history) == 1
    assert isinstance(history[0], ModelRequest)


def test_events_to_message_history_error_outcome() -> None:
    events = [
        make_event(
            0,
            "tool_use",
            {"tool_use_id": "tu_err", "name": "broken", "input": {}},
        ),
        make_event(
            1,
            "tool_result",
            {
                "tool_use_id": "tu_err",
                "content": [{"type": "text", "text": "boom"}],
                "is_error": True,
            },
        ),
    ]
    history = events_to_message_history(events)
    # Two messages: the tool_use is rolled into a ModelResponse, then
    # the tool_result is its own ModelRequest.
    tr = history[-1].parts[0]
    assert isinstance(tr, ToolReturnPart)
    assert tr.outcome == "failed"


# ---------------------------------------------------------------------------
# step() with no user input
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_no_user_message_emits_nothing() -> None:
    agent = Agent(TestModel(custom_output_text="should not run"))
    adapter = PydanticAIAdapter(agent)
    stream = ListEventStream()
    tools = RecordingToolRegistry()

    emitted = await drain_step(adapter, stream, tools)
    assert emitted == []


# ---------------------------------------------------------------------------
# step() basic flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_basic_emits_delta_and_assistant_message() -> None:
    agent = Agent(TestModel(custom_output_text="ok"))
    adapter = PydanticAIAdapter(agent)
    stream = ListEventStream(
        [make_event(0, "user.message", {"content": [{"type": "text", "text": "say ok"}]})]
    )
    tools = RecordingToolRegistry()

    emitted = await drain_step(adapter, stream, tools)
    types = [e.type for e in emitted]

    assert "assistant.delta" in types
    assert types[-1] == "assistant.message"
    final = next(e for e in emitted if e.type == "assistant.message")
    assert any(b.get("type") == "text" for b in final.payload["content"])
    text = "".join(b["text"] for b in final.payload["content"] if b.get("type") == "text")
    assert "ok" in text.lower()


# ---------------------------------------------------------------------------
# Idempotent resume
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_idempotent_when_already_answered() -> None:
    agent = Agent(TestModel(custom_output_text="ok"))
    adapter = PydanticAIAdapter(agent)
    stream = ListEventStream(
        [make_event(0, "user.message", {"content": [{"type": "text", "text": "say ok"}]})]
    )
    tools = RecordingToolRegistry()

    first = await drain_step(adapter, stream, tools)
    assert any(e.type == "assistant.message" for e in first)

    # Second call: latest event is already assistant.message — no work to do.
    second = await drain_step(adapter, stream, tools)
    assert second == [], (
        f"resume should be idempotent; got {[e.type for e in second]}"
    )


# ---------------------------------------------------------------------------
# Step uses ctx (no crash w/ system prompt etc.)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_ignores_status_events_in_history() -> None:
    agent = Agent(TestModel(custom_output_text="ok"))
    adapter = PydanticAIAdapter(agent)
    stream = ListEventStream(
        [
            make_event(0, "status", {"from": "idle", "to": "running"}),
            make_event(
                1, "user.message", {"content": [{"type": "text", "text": "hello"}]}
            ),
        ]
    )
    tools = RecordingToolRegistry()
    emitted = await drain_step(adapter, stream, tools)
    assert any(e.type == "assistant.message" for e in emitted)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_lifecycle_is_noop() -> None:
    agent = Agent(TestModel())
    adapter = PydanticAIAdapter(agent)
    ctx = make_session_context()
    for lc in ("created", "resumed", "interrupted", "terminated"):
        assert await adapter.on_lifecycle(ctx, lc) is None  # type: ignore[arg-type]
