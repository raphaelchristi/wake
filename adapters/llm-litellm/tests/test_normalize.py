"""Tests for ``normalize_response`` across providers.

These pin the contract: Anthropic ``tool_use`` blocks, OpenAI
``tool_calls`` array and Ollama's hybrid form all collapse to the same
``NormalizedMessage`` shape.
"""

from __future__ import annotations

from wake.types import Event

from wake_llm_litellm.base import NormalizedToolCall
from wake_llm_litellm.normalize import (
    normalize_response,
    to_wake_events,
)

from ._fixtures import (
    anthropic_response,
    ollama_response,
    openai_response,
)


# ----- Anthropic ------------------------------------------------------------


def test_anthropic_text_only() -> None:
    resp = anthropic_response(text="hello")
    msg = normalize_response(resp, model="anthropic/claude-opus-4-7")
    assert msg.text == "hello"
    assert msg.tool_calls == []
    assert msg.stop_reason == "end_turn"


def test_anthropic_with_tool_use() -> None:
    resp = anthropic_response(
        text="Let me run that.",
        tool_calls=[{"id": "toolu_01", "name": "bash", "input": {"cmd": "ls"}}],
    )
    msg = normalize_response(resp, model="anthropic/claude-opus-4-7")
    assert msg.text == "Let me run that."
    assert msg.tool_calls == [
        NormalizedToolCall(id="toolu_01", name="bash", input={"cmd": "ls"})
    ]
    assert msg.stop_reason == "tool_use"
    # Usage normalised to Anthropic names.
    assert "input_tokens" in msg.usage and "output_tokens" in msg.usage
    # cache_read field preserved.
    assert msg.usage["cache_read_input_tokens"] == 80


def test_anthropic_multi_tool_calls_preserved_in_order() -> None:
    resp = anthropic_response(
        text="",
        tool_calls=[
            {"id": "toolu_a", "name": "bash", "input": {"cmd": "ls"}},
            {"id": "toolu_b", "name": "read_file", "input": {"path": "/x"}},
        ],
    )
    msg = normalize_response(resp, model="anthropic/claude-opus-4-7")
    assert [c.id for c in msg.tool_calls] == ["toolu_a", "toolu_b"]


# ----- OpenAI ---------------------------------------------------------------


def test_openai_text_only() -> None:
    resp = openai_response(text="hello there")
    msg = normalize_response(resp, model="openai/gpt-4o")
    assert msg.text == "hello there"
    assert msg.stop_reason == "end_turn"
    assert msg.tool_calls == []


def test_openai_with_tool_calls_string_arguments() -> None:
    resp = openai_response(
        text="",
        tool_calls=[{"id": "call_1", "name": "bash", "input": {"cmd": "ls -la"}}],
    )
    msg = normalize_response(resp, model="openai/gpt-4o")
    # JSON-string arguments must be parsed back into dict.
    assert msg.tool_calls == [
        NormalizedToolCall(id="call_1", name="bash", input={"cmd": "ls -la"})
    ]
    # finish_reason="tool_calls" → "tool_use".
    assert msg.stop_reason == "tool_use"


def test_openai_malformed_tool_arguments_falls_back_to_raw() -> None:
    """If a provider sends busted JSON, we must NOT crash."""
    from types import SimpleNamespace

    resp = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        {
                            "id": "call_x",
                            "type": "function",
                            "function": {"name": "bash", "arguments": "{not valid json"},
                        }
                    ],
                ),
                finish_reason="tool_calls",
            )
        ],
        usage=None,
    )
    msg = normalize_response(resp, model="openai/gpt-4o")
    assert msg.tool_calls[0].input == {"_raw": "{not valid json"}


# ----- Ollama ---------------------------------------------------------------


def test_ollama_text_only() -> None:
    resp = ollama_response(text="hi from local")
    msg = normalize_response(resp, model="ollama/qwen2.5-coder")
    assert msg.text == "hi from local"
    assert msg.stop_reason == "end_turn"


def test_ollama_with_tool_calls_dict_arguments() -> None:
    resp = ollama_response(
        tool_calls=[{"id": "fn_1", "name": "weather", "input": {"city": "Recife"}}],
    )
    msg = normalize_response(resp, model="ollama/qwen2.5-coder")
    assert msg.tool_calls[0].input == {"city": "Recife"}


def test_ollama_no_cost_reported() -> None:
    resp = ollama_response(text="local")
    msg = normalize_response(resp, model="ollama/qwen2.5-coder")
    assert msg.cost_usd is None


# ----- usage / cost ---------------------------------------------------------


def test_cost_propagated_when_provider_reports_it() -> None:
    resp = anthropic_response(text="x", cost_usd=0.0042)
    msg = normalize_response(resp, model="anthropic/claude-opus-4-7")
    assert msg.cost_usd == 0.0042


def test_empty_choices_returns_error_stop() -> None:
    from types import SimpleNamespace

    resp = SimpleNamespace(choices=[], usage=None)
    msg = normalize_response(resp, model="anthropic/claude-opus-4-7")
    assert msg.stop_reason == "error"
    assert msg.text == ""


def test_finish_reason_mapping() -> None:
    # length → max_tokens.
    resp = anthropic_response(text="…", finish_reason="length")
    msg = normalize_response(resp, model="anthropic/claude-opus-4-7")
    assert msg.stop_reason == "max_tokens"


# ----- Event conversion -----------------------------------------------------


def test_to_wake_events_text_only() -> None:
    resp = anthropic_response(text="hello")
    msg = normalize_response(resp, model="anthropic/claude-opus-4-7")
    events = to_wake_events(msg, session_id="sess_42")

    assert len(events) == 1
    ev = events[0]
    assert isinstance(ev, Event)
    assert ev.type == "assistant.message"
    assert ev.session_id == "sess_42"
    assert ev.payload["content"] == [{"type": "text", "text": "hello"}]
    assert ev.payload["stop_reason"] == "end_turn"
    # Placeholder fields the dispatcher fills.
    assert ev.id == "" and ev.seq == -1


def test_to_wake_events_with_tool_calls_emits_tool_use_events() -> None:
    resp = anthropic_response(
        text="Let me check.",
        tool_calls=[{"id": "toolu_1", "name": "bash", "input": {"cmd": "ls"}}],
    )
    msg = normalize_response(resp, model="anthropic/claude-opus-4-7")
    events = to_wake_events(msg, session_id="sess_42")

    assert len(events) == 2
    assistant_msg, tool_use = events
    assert assistant_msg.type == "assistant.message"
    # Tool blocks embedded in the assistant message content.
    types = [b["type"] for b in assistant_msg.payload["content"]]
    assert "text" in types and "tool_use" in types
    # Discrete tool_use event for the dispatcher to act on.
    assert tool_use.type == "tool_use"
    assert tool_use.payload == {
        "tool_use_id": "toolu_1",
        "name": "bash",
        "input": {"cmd": "ls"},
    }


def test_to_wake_events_includes_cost_metadata_when_present() -> None:
    resp = anthropic_response(text="hi", cost_usd=0.001)
    msg = normalize_response(resp, model="anthropic/claude-opus-4-7")
    events = to_wake_events(msg, session_id="s")
    assert events[0].metadata == {"cost_usd": 0.001}


def test_provider_detection_falls_back_to_shape() -> None:
    """A response without ``_wake_provider_hint`` and a generic model
    name should still pick the right extractor."""
    from types import SimpleNamespace

    # List-of-blocks content → looks Anthropic-shaped.
    resp = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=[{"type": "text", "text": "hi"}]),
                finish_reason="stop",
            )
        ],
        usage=None,
    )
    msg = normalize_response(resp, model="some-other-model")
    assert msg.text == "hi"
