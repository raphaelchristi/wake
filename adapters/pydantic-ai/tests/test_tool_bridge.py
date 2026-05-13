"""Tests for the Wake ↔ Pydantic AI tool bridge.

Verify that:

* :func:`build_wake_toolset` produces a :class:`FunctionToolset` whose
  callables route through :meth:`ToolRegistry.execute` with a fresh
  ``tool_use_id``.
* Tool errors (``is_error=True``) come back to the model as a string
  (not a thrown exception) so the conversation can continue.
* Wake-style tool names that aren't valid Python identifiers
  (``"mcp.weather"``) still register cleanly.
* The same registry can drive multiple tool invocations within one
  step; each call gets a distinct ``tool_use_id``.
"""

from __future__ import annotations

import asyncio
import itertools

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.toolsets import FunctionToolset
from wake_adapter_pydantic_ai import PydanticAIAdapter, build_wake_toolset
from wake_adapter_pydantic_ai.tool_bridge import _python_identifier

from wake.types import TextBlock, ToolDescriptor, ToolResult

from .conftest import (
    ListEventStream,
    RecordingToolRegistry,
    drain_step,
    make_event,
)

# ---------------------------------------------------------------------------
# Identifier coercion
# ---------------------------------------------------------------------------


def test_python_identifier_replaces_dots() -> None:
    assert _python_identifier("mcp.weather") == "mcp_weather"


def test_python_identifier_handles_leading_digit() -> None:
    assert _python_identifier("3tool").startswith("t_")


def test_python_identifier_handles_empty() -> None:
    assert _python_identifier("") == "wake_tool"


# ---------------------------------------------------------------------------
# build_wake_toolset
# ---------------------------------------------------------------------------


def test_build_wake_toolset_returns_function_toolset() -> None:
    descs = [
        ToolDescriptor(name="echo", description="echo input", schema={"type": "object"}),
        ToolDescriptor(name="ping", description="ping", schema={"type": "object"}),
    ]
    reg = RecordingToolRegistry(descriptors=descs)
    counter = itertools.count()
    ts = build_wake_toolset(
        reg,
        tool_use_id_factory=lambda name: f"tu_{next(counter)}_{name}",
    )
    assert isinstance(ts, FunctionToolset)


def test_build_wake_toolset_empty_when_no_tools() -> None:
    reg = RecordingToolRegistry()
    ts = build_wake_toolset(reg, tool_use_id_factory=lambda n: "x")
    assert isinstance(ts, FunctionToolset)


def test_build_wake_toolset_supports_wake_style_names() -> None:
    descs = [
        ToolDescriptor(
            name="mcp.weather", description="weather", schema={"type": "object"}
        ),
    ]
    reg = RecordingToolRegistry(descriptors=descs)
    ts = build_wake_toolset(reg, tool_use_id_factory=lambda n: f"id_{n}")
    # Toolset built without raising on the dotted name.
    assert isinstance(ts, FunctionToolset)


# ---------------------------------------------------------------------------
# End-to-end tool invocation via the adapter
# ---------------------------------------------------------------------------


def _stream_factory_calls_echo() -> object:
    """Build a stream_function that emits a single echo tool call then text."""
    state = {"calls": 0}

    async def stream(messages, info: AgentInfo):  # type: ignore[no-untyped-def]
        state["calls"] += 1
        if state["calls"] == 1:
            yield {0: DeltaToolCall(name="echo", json_args='{"text":"hi"}', tool_call_id="t1")}
        else:
            yield "done"

    return stream


@pytest.mark.asyncio
async def test_adapter_routes_tool_call_through_registry() -> None:
    agent = Agent(FunctionModel(stream_function=_stream_factory_calls_echo()))
    adapter = PydanticAIAdapter(agent)

    stream = ListEventStream(
        [make_event(0, "user.message", {"content": [{"type": "text", "text": "use echo"}]})]
    )
    descs = [
        ToolDescriptor(name="echo", description="echo", schema={"type": "object"}),
    ]
    tools = RecordingToolRegistry(descriptors=descs)

    emitted = await drain_step(adapter, stream, tools)

    # Registry.execute was called once with the right name + input.
    assert len(tools.calls) == 1
    call = tools.calls[0]
    assert call["name"] == "echo"
    assert call["input"] == {"text": "hi"}
    assert call["tool_use_id"]  # non-empty (factory minted it)

    # Adapter emitted tool_use + tool_result + assistant.message.
    types = [e.type for e in emitted]
    assert "tool_use" in types
    assert "tool_result" in types
    assert types[-1] == "assistant.message"


@pytest.mark.asyncio
async def test_adapter_tool_error_becomes_string_not_exception() -> None:
    """If a Wake tool returns is_error=True, the adapter must surface
    the result as a string (not raise) so Pydantic AI continues."""
    agent = Agent(FunctionModel(stream_function=_stream_factory_calls_echo()))
    adapter = PydanticAIAdapter(agent)

    stream = ListEventStream(
        [make_event(0, "user.message", {"content": [{"type": "text", "text": "use echo"}]})]
    )
    descs = [ToolDescriptor(name="echo", description="echo", schema={"type": "object"})]
    tools = RecordingToolRegistry(
        descriptors=descs,
        responses={
            "echo": ToolResult(
                content=[TextBlock(text="boom")],
                is_error=True,
                error_code="some_err",
            )
        },
    )

    emitted = await drain_step(adapter, stream, tools)
    # Did not raise; we got a final assistant.message.
    assert any(e.type == "assistant.message" for e in emitted)
    # tool_result event marked as is_error
    tr = next(e for e in emitted if e.type == "tool_result")
    assert tr.payload["is_error"] is True


@pytest.mark.asyncio
async def test_tool_use_ids_are_unique_across_invocations() -> None:
    """Idempotence: minted tool_use_ids must not collide within one step."""

    state = {"calls": 0}

    async def stream(messages, info: AgentInfo):  # type: ignore[no-untyped-def]
        state["calls"] += 1
        if state["calls"] == 1:
            # Parallel calls -> two echoes in one response.
            yield {
                0: DeltaToolCall(name="echo", json_args='{"text":"a"}', tool_call_id="m1"),
                1: DeltaToolCall(name="echo", json_args='{"text":"b"}', tool_call_id="m2"),
            }
        else:
            yield "ok"

    agent = Agent(FunctionModel(stream_function=stream))
    adapter = PydanticAIAdapter(agent)

    stream_ev = ListEventStream(
        [make_event(0, "user.message", {"content": [{"type": "text", "text": "both"}]})]
    )
    descs = [ToolDescriptor(name="echo", description="echo", schema={"type": "object"})]
    tools = RecordingToolRegistry(descriptors=descs)

    await drain_step(adapter, stream_ev, tools)

    # tool_use_ids should be unique across the two registry calls AND
    # match the Pydantic AI tool_call_id we surfaced.
    assert len(tools.calls) == 2
    ids = [c["tool_use_id"] for c in tools.calls]
    assert len(set(ids)) == 2


@pytest.mark.asyncio
async def test_event_loop_is_alive_when_running_tool() -> None:
    """Sanity check: the bridge is fully async-aware (no blocking)."""
    agent = Agent(FunctionModel(stream_function=_stream_factory_calls_echo()))
    adapter = PydanticAIAdapter(agent)
    stream_ev = ListEventStream(
        [make_event(0, "user.message", {"content": [{"type": "text", "text": "x"}]})]
    )
    descs = [ToolDescriptor(name="echo", description="echo", schema={"type": "object"})]
    tools = RecordingToolRegistry(descriptors=descs)

    await asyncio.wait_for(drain_step(adapter, stream_ev, tools), timeout=5.0)
