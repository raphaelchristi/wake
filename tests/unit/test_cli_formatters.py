"""Unit tests for the CLI formatters.

We don't compare rendered text byte-for-byte (that would be brittle
across rich releases); instead we exercise the pure helpers and verify
that the high-level renderers don't raise on tricky shapes.
"""

from __future__ import annotations

import io

from rich.console import Console

from wake.cli import formatters
from wake.cli.formatters import (
    _extract_model,
    _extract_text,
    _format_tool_input,
    _summarise_payload,
    render_agents,
    render_event_line,
    render_events_table,
    render_run_event,
    render_sessions,
)


def _capture(func: object, *args: object) -> str:
    """Run ``func(*args)`` with stdout redirected to a string."""
    buffer = io.StringIO()
    real = formatters.console
    formatters.console = Console(file=buffer, force_terminal=False, width=120)
    try:
        assert callable(func)
        func(*args)
    finally:
        formatters.console = real
    return buffer.getvalue()


def test_extract_model_from_dict() -> None:
    assert _extract_model({"model": {"id": "claude-opus-4-7"}}) == "claude-opus-4-7"
    assert _extract_model({"model": "raw-string"}) == "raw-string"
    assert _extract_model({}) == "-"


def test_extract_text_handles_content_blocks() -> None:
    payload = {
        "content": [
            {"type": "text", "text": "hello"},
            {"type": "text", "text": " world"},
        ]
    }
    assert _extract_text(payload) == "hello world"


def test_extract_text_handles_delta_and_text() -> None:
    assert _extract_text({"text": "hi"}) == "hi"
    assert _extract_text({"delta": "partial"}) == "partial"
    assert _extract_text({}) == ""


def test_format_tool_input_command_shorthand() -> None:
    out = _format_tool_input({"command": "ls -la"})
    assert "ls -la" in out


def test_summarise_payload_status_transition() -> None:
    out = _summarise_payload("status", {"from": "idle", "to": "running"})
    assert "idle" in out
    assert "running" in out


def test_render_agents_table_renders_without_error() -> None:
    output = _capture(
        render_agents,
        [
            {
                "id": "agt_1",
                "name": "alpha",
                "model": {"id": "claude-opus-4-7"},
                "tools": [{"type": "bash"}, {"type": "file_read"}],
                "version": 2,
            }
        ],
    )
    assert "agt_1" in output
    assert "alpha" in output
    assert "bash" in output


def test_render_agents_table_empty() -> None:
    output = _capture(render_agents, [])
    assert "No agents" in output


def test_render_sessions_empty_message() -> None:
    output = _capture(render_sessions, [])
    assert "No sessions" in output


def test_render_events_table_with_payloads() -> None:
    events = [
        {"seq": 0, "type": "user.message", "payload": {"content": [{"type": "text", "text": "hi"}]}},
        {"seq": 1, "type": "status", "payload": {"from": "idle", "to": "running"}},
        {"seq": 2, "type": "tool_use", "payload": {"name": "bash", "input": {"command": "ls"}}},
    ]
    output = _capture(render_events_table, events)
    assert "user.message" in output
    assert "running" in output
    assert "bash" in output


def test_render_event_line_handles_unknown_type() -> None:
    # Must not raise on unrecognised event types.
    output = _capture(
        render_event_line,
        {"data": {"type": "mystery", "seq": 5, "payload": {"foo": "bar"}}},
    )
    assert "mystery" in output


def test_render_run_event_signals_end_turn() -> None:
    end = render_run_event(
        {
            "data": {
                "type": "assistant.message",
                "payload": {
                    "content": [{"type": "text", "text": "done"}],
                    "stop_reason": "end_turn",
                },
            }
        }
    )
    assert end is True


def test_render_run_event_status_terminated() -> None:
    end = render_run_event({"data": {"type": "status", "payload": {"to": "terminated"}}})
    assert end is True


def test_render_run_event_delta_does_not_terminate() -> None:
    end = render_run_event({"data": {"type": "assistant.delta", "payload": {"delta": "hi"}}})
    assert end is False
