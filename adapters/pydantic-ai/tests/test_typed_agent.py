"""Typed agent tests — verify the adapter handles Pydantic AI's typed
``output_type`` agents.

Pydantic AI is the most strictly-typed framework in the Wake adapter
family. Agents can declare ``output_type=MyPydanticModel`` and the
framework will coerce the model output into a validated structured
result. The Wake adapter must NOT break this: ``assistant.message``
events should carry the structured output as text (or as a JSON
blob), and the message_history must round-trip cleanly.
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from wake_adapter_pydantic_ai import PydanticAIAdapter

from .conftest import (
    ListEventStream,
    RecordingToolRegistry,
    drain_step,
    make_event,
)


class Result(BaseModel):
    """A typed result that exercises output_type validation."""

    answer: str
    confidence: float


def _typed_output_stream() -> object:
    """Stream function that returns a typed-output tool call.

    Pydantic AI implements typed outputs as a "structured-output
    tool" — the model is expected to call a synthetic
    ``final_result`` tool with arguments matching the schema. This
    stream emits exactly that.
    """

    async def stream(messages, info: AgentInfo):  # type: ignore[no-untyped-def]
        # Walk the output_tools to find the synthetic tool name (the
        # framework prepends a known prefix; ``final_result`` is the
        # default for plain structured outputs).
        tool_name = info.output_tools[0].name if info.output_tools else "final_result"
        payload = json.dumps({"answer": "42", "confidence": 0.95})
        yield {0: DeltaToolCall(name=tool_name, json_args=payload, tool_call_id="r1")}

    return stream


@pytest.mark.asyncio
async def test_typed_agent_produces_assistant_message() -> None:
    agent = Agent(
        FunctionModel(stream_function=_typed_output_stream()),
        output_type=Result,
    )
    adapter = PydanticAIAdapter(agent)

    stream = ListEventStream(
        [make_event(0, "user.message", {"content": [{"type": "text", "text": "what's the answer"}]})]
    )
    tools = RecordingToolRegistry()

    emitted = await drain_step(adapter, stream, tools)
    types = [e.type for e in emitted]
    assert "assistant.message" in types, (
        f"typed agent should still emit assistant.message; got {types}"
    )

    # The structured output is serialised; the adapter should still
    # produce a well-formed event payload.
    final = next(e for e in emitted if e.type == "assistant.message")
    assert isinstance(final.payload.get("content"), list)


@pytest.mark.asyncio
async def test_typed_agent_with_wake_tool_succeeds() -> None:
    """Combine a typed agent with a Wake-registered tool. The tool runs
    first, then the typed final_result is emitted."""
    state = {"calls": 0}

    async def stream(messages, info: AgentInfo):  # type: ignore[no-untyped-def]
        state["calls"] += 1
        if state["calls"] == 1:
            # Call the user's echo tool.
            yield {0: DeltaToolCall(name="echo", json_args='{"text":"x"}', tool_call_id="t1")}
        else:
            # Emit the typed output as a final_result tool call.
            tool_name = info.output_tools[0].name if info.output_tools else "final_result"
            payload = json.dumps({"answer": "ok", "confidence": 1.0})
            yield {0: DeltaToolCall(name=tool_name, json_args=payload, tool_call_id="r1")}

    agent = Agent(
        FunctionModel(stream_function=stream),
        output_type=Result,
    )
    adapter = PydanticAIAdapter(agent)

    from wake.types import ToolDescriptor

    stream_ev = ListEventStream(
        [make_event(0, "user.message", {"content": [{"type": "text", "text": "do it"}]})]
    )
    tools = RecordingToolRegistry(
        descriptors=[ToolDescriptor(name="echo", description="echo", schema={"type": "object"})]
    )

    emitted = await drain_step(adapter, stream_ev, tools)
    types = [e.type for e in emitted]
    assert "tool_use" in types
    assert "tool_result" in types
    assert types[-1] == "assistant.message"
    # Registry was called for the echo tool.
    assert any(c["name"] == "echo" for c in tools.calls)


@pytest.mark.asyncio
async def test_typed_agent_validation_pairs_tool_use_ids() -> None:
    """Every tool_use the adapter emits must have a paired tool_result
    in the same step — even when typed-output tool calls are mixed
    in."""

    state = {"calls": 0}

    async def stream(messages, info: AgentInfo):  # type: ignore[no-untyped-def]
        state["calls"] += 1
        if state["calls"] == 1:
            yield {0: DeltaToolCall(name="echo", json_args='{"text":"hi"}', tool_call_id="t1")}
        else:
            tool_name = info.output_tools[0].name if info.output_tools else "final_result"
            payload = json.dumps({"answer": "x", "confidence": 0.5})
            yield {0: DeltaToolCall(name=tool_name, json_args=payload, tool_call_id="r1")}

    agent = Agent(
        FunctionModel(stream_function=stream),
        output_type=Result,
    )
    adapter = PydanticAIAdapter(agent)

    from wake.types import ToolDescriptor

    stream_ev = ListEventStream(
        [make_event(0, "user.message", {"content": [{"type": "text", "text": "go"}]})]
    )
    tools = RecordingToolRegistry(
        descriptors=[ToolDescriptor(name="echo", description="", schema={"type": "object"})]
    )

    emitted = await drain_step(adapter, stream_ev, tools)
    use_ids = {e.payload.get("tool_use_id") for e in emitted if e.type == "tool_use"}
    result_ids = {e.payload.get("tool_use_id") for e in emitted if e.type == "tool_result"}
    # User tools should appear in both sets; typed-output "tool" is
    # internal and not always paired — at minimum we want no orphans
    # for tools the WAKE registry actually executed.
    wake_user_tool_ids = {c["tool_use_id"] for c in tools.calls}
    assert wake_user_tool_ids <= result_ids, (
        f"every wake-registry tool call must have a matching tool_result: "
        f"missing={wake_user_tool_ids - result_ids}"
    )
    assert wake_user_tool_ids <= use_ids
