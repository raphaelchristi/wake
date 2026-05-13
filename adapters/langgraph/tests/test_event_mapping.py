"""Tests for ``event_mapping`` (Wake events ↔ LangChain messages)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from wake_adapter_langgraph.event_mapping import (
    events_to_state,
    message_to_wake_events,
)

from wake.types import Event, EventType


def _now() -> datetime:
    return datetime.now(UTC)


def _ev(seq: int, etype: EventType, payload: dict[str, Any]) -> Event:
    return Event(
        id=f"e{seq}",
        session_id="s",
        seq=seq,
        type=etype,
        payload=payload,
        created_at=_now(),
    )


# ---------------------------------------------------------------------------
# events_to_state
# ---------------------------------------------------------------------------


def test_events_to_state_user_and_assistant() -> None:
    events = [
        _ev(0, "user.message", {"content": [{"type": "text", "text": "hi"}]}),
        _ev(1, "assistant.message", {"content": [{"type": "text", "text": "yo"}]}),
    ]
    state = events_to_state(events)
    msgs = state["messages"]
    assert len(msgs) == 2
    assert isinstance(msgs[0], HumanMessage)
    assert msgs[0].content == "hi"
    assert isinstance(msgs[1], AIMessage)
    assert msgs[1].content == "yo"


def test_events_to_state_includes_system_when_provided() -> None:
    events = [
        _ev(0, "user.message", {"content": [{"type": "text", "text": "hi"}]}),
    ]
    state = events_to_state(events, system="be brief")
    msgs = state["messages"]
    assert isinstance(msgs[0], SystemMessage)
    assert msgs[0].content == "be brief"
    assert isinstance(msgs[1], HumanMessage)


def test_events_to_state_tool_use_attaches_to_trailing_assistant() -> None:
    events = [
        _ev(0, "user.message", {"content": [{"type": "text", "text": "hi"}]}),
        _ev(1, "assistant.message", {"content": [{"type": "text", "text": "calling..."}]}),
        _ev(
            2,
            "tool_use",
            {"tool_use_id": "tu_1", "name": "echo", "input": {"text": "x"}},
        ),
    ]
    state = events_to_state(events)
    msgs = state["messages"]
    # Last message is still AIMessage but with a tool_call attached.
    assert isinstance(msgs[-1], AIMessage)
    assert len(msgs[-1].tool_calls) == 1
    assert msgs[-1].tool_calls[0]["name"] == "echo"
    assert msgs[-1].tool_calls[0]["id"] == "tu_1"
    assert msgs[-1].tool_calls[0]["args"] == {"text": "x"}


def test_events_to_state_tool_use_creates_new_assistant_if_needed() -> None:
    events = [
        _ev(0, "user.message", {"content": [{"type": "text", "text": "hi"}]}),
        _ev(
            1,
            "tool_use",
            {"tool_use_id": "tu_1", "name": "echo", "input": {"text": "x"}},
        ),
    ]
    state = events_to_state(events)
    msgs = state["messages"]
    # Adapter created a placeholder AIMessage to host the tool_call.
    assert isinstance(msgs[-1], AIMessage)
    assert msgs[-1].tool_calls[0]["id"] == "tu_1"


def test_events_to_state_tool_result_becomes_toolmessage() -> None:
    events = [
        _ev(0, "user.message", {"content": [{"type": "text", "text": "hi"}]}),
        _ev(1, "assistant.message", {"content": []}),
        _ev(
            2,
            "tool_use",
            {"tool_use_id": "tu_1", "name": "echo", "input": {}},
        ),
        _ev(
            3,
            "tool_result",
            {
                "tool_use_id": "tu_1",
                "content": [{"type": "text", "text": "result"}],
                "is_error": False,
            },
        ),
    ]
    state = events_to_state(events)
    msgs = state["messages"]
    assert isinstance(msgs[-1], ToolMessage)
    assert msgs[-1].content == "result"
    assert msgs[-1].tool_call_id == "tu_1"


def test_events_to_state_skips_unknown_types() -> None:
    events = [
        _ev(0, "user.message", {"content": [{"type": "text", "text": "hi"}]}),
        _ev(1, "status", {"from": "idle", "to": "running"}),
        _ev(2, "assistant.delta", {"index": 0, "delta": {"type": "text_delta", "text": "x"}}),
    ]
    state = events_to_state(events)
    # Only the user.message becomes a message.
    assert len(state["messages"]) == 1


def test_events_to_state_assistant_message_with_embedded_tool_use_blocks() -> None:
    events = [
        _ev(0, "user.message", {"content": [{"type": "text", "text": "hi"}]}),
        _ev(
            1,
            "assistant.message",
            {
                "content": [
                    {"type": "text", "text": "calling tools"},
                    {"type": "tool_use", "id": "tu_a", "name": "a", "input": {}},
                ]
            },
        ),
    ]
    state = events_to_state(events)
    ai = state["messages"][-1]
    assert isinstance(ai, AIMessage)
    assert ai.content == "calling tools"
    assert len(ai.tool_calls) == 1
    assert ai.tool_calls[0]["id"] == "tu_a"


def test_events_to_state_custom_state_key() -> None:
    events = [
        _ev(0, "user.message", {"content": [{"type": "text", "text": "hi"}]}),
    ]
    state = events_to_state(events, state_key="chat")
    assert "chat" in state
    assert "messages" not in state


# ---------------------------------------------------------------------------
# message_to_wake_events
# ---------------------------------------------------------------------------


def test_message_to_wake_events_human_is_skipped() -> None:
    out = list(message_to_wake_events(HumanMessage(content="hi"), session_id="s"))
    assert out == []


def test_message_to_wake_events_system_is_skipped() -> None:
    out = list(message_to_wake_events(SystemMessage(content="prompt"), session_id="s"))
    assert out == []


def test_message_to_wake_events_ai_text_only() -> None:
    out = list(message_to_wake_events(AIMessage(content="hello"), session_id="s"))
    assert len(out) == 1
    assert out[0].type == "assistant.message"
    assert out[0].payload["content"][0]["text"] == "hello"
    assert out[0].payload["stop_reason"] == "end_turn"


def test_message_to_wake_events_ai_with_tool_calls() -> None:
    msg = AIMessage(
        content="thinking",
        tool_calls=[
            {"id": "tu_1", "name": "echo", "args": {"text": "x"}, "type": "tool_call"},
        ],
    )
    out = list(message_to_wake_events(msg, session_id="s"))
    # tool_use yielded before the aggregate assistant.message.
    assert [e.type for e in out] == ["tool_use", "assistant.message"]
    assert out[0].payload["tool_use_id"] == "tu_1"
    assert out[0].payload["name"] == "echo"
    assert out[0].payload["input"] == {"text": "x"}
    assert out[1].payload["stop_reason"] == "tool_use"
    # assistant.message content includes both the text and the tool_use block.
    blocks = out[1].payload["content"]
    types = [b["type"] for b in blocks]
    assert "text" in types
    assert "tool_use" in types


def test_message_to_wake_events_tool_message_becomes_tool_result() -> None:
    msg = ToolMessage(content="result", tool_call_id="tu_1", name="echo")
    out = list(message_to_wake_events(msg, session_id="s"))
    assert len(out) == 1
    assert out[0].type == "tool_result"
    assert out[0].payload["tool_use_id"] == "tu_1"
    assert out[0].payload["content"][0]["text"] == "result"
    assert out[0].payload["is_error"] is False


def test_message_to_wake_events_tool_message_with_error_status() -> None:
    msg = ToolMessage(
        content="boom",
        tool_call_id="tu_1",
        name="echo",
        status="error",
    )
    out = list(message_to_wake_events(msg, session_id="s"))
    assert out[0].payload["is_error"] is True


def test_message_to_wake_events_placeholder_ids() -> None:
    out = list(message_to_wake_events(AIMessage(content="hi"), session_id="abc"))
    assert out[0].id == ""
    assert out[0].seq == -1
    assert out[0].session_id == "abc"
