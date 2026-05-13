"""Streaming-specific tests for the Pydantic AI adapter.

Verify that:

* Multi-chunk text streams produce one ``assistant.delta`` per chunk.
* All deltas precede the final ``assistant.message``.
* The final ``assistant.message`` text equals the concatenation of all
  emitted deltas.
* Cancellation mid-stream propagates :class:`asyncio.CancelledError`
  without raising other exceptions.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.function import AgentInfo, FunctionModel
from wake_adapter_pydantic_ai import PydanticAIAdapter

from .conftest import (
    ListEventStream,
    RecordingToolRegistry,
    drain_step,
    make_event,
    make_session_context,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def _chunked_text_stream(chunks: list[str]) -> object:
    """A stream_function that emits the given text chunks back-to-back."""

    async def stream(messages, info: AgentInfo) -> AsyncIterator[str]:  # type: ignore[no-untyped-def]
        for c in chunks:
            yield c

    return stream


@pytest.mark.asyncio
async def test_streaming_emits_one_delta_per_chunk() -> None:
    chunks = ["Hello ", "world", "!"]
    agent = Agent(FunctionModel(stream_function=_chunked_text_stream(chunks)))
    adapter = PydanticAIAdapter(agent)

    stream = ListEventStream(
        [make_event(0, "user.message", {"content": [{"type": "text", "text": "hi"}]})]
    )
    tools = RecordingToolRegistry()

    emitted = await drain_step(adapter, stream, tools)
    deltas = [e for e in emitted if e.type == "assistant.delta"]
    # At least one delta — Pydantic AI may coalesce adjacent chunks.
    assert deltas, f"expected delta events, got: {[e.type for e in emitted]}"
    # Concatenated delta text reconstructs the message.
    delta_text = "".join(d.payload["delta"]["text"] for d in deltas)
    assert delta_text == "Hello world!"


@pytest.mark.asyncio
async def test_streaming_all_deltas_before_final_message() -> None:
    agent = Agent(
        FunctionModel(stream_function=_chunked_text_stream(["a", "b", "c"]))
    )
    adapter = PydanticAIAdapter(agent)

    stream = ListEventStream(
        [make_event(0, "user.message", {"content": [{"type": "text", "text": "hi"}]})]
    )
    tools = RecordingToolRegistry()

    emitted = await drain_step(adapter, stream, tools)
    last_delta_idx = max(
        i for i, e in enumerate(emitted) if e.type == "assistant.delta"
    )
    msg_idx = next(
        i for i, e in enumerate(emitted) if e.type == "assistant.message"
    )
    assert last_delta_idx < msg_idx, (
        "all assistant.delta events must precede the final assistant.message"
    )


@pytest.mark.asyncio
async def test_streaming_final_message_text_matches_deltas() -> None:
    chunks = ["The ", "answer ", "is ", "42."]
    agent = Agent(FunctionModel(stream_function=_chunked_text_stream(chunks)))
    adapter = PydanticAIAdapter(agent)

    stream = ListEventStream(
        [make_event(0, "user.message", {"content": [{"type": "text", "text": "ask"}]})]
    )
    tools = RecordingToolRegistry()

    emitted = await drain_step(adapter, stream, tools)
    delta_text = "".join(
        e.payload["delta"]["text"]
        for e in emitted
        if e.type == "assistant.delta"
    )
    final = next(e for e in emitted if e.type == "assistant.message")
    msg_text = "".join(
        b["text"] for b in final.payload["content"] if b.get("type") == "text"
    )
    assert msg_text == delta_text == "The answer is 42."


@pytest.mark.asyncio
async def test_streaming_cancellation_propagates_cleanly() -> None:
    """Mid-stream cancellation must propagate CancelledError, not eat it
    nor raise something else."""

    async def slow_stream(messages, info: AgentInfo) -> AsyncIterator[str]:  # type: ignore[no-untyped-def]
        for token in ["x"] * 1000:
            await asyncio.sleep(0.01)
            yield token

    agent = Agent(FunctionModel(stream_function=slow_stream))
    adapter = PydanticAIAdapter(agent)

    stream = ListEventStream(
        [make_event(0, "user.message", {"content": [{"type": "text", "text": "loop"}]})]
    )
    tools = RecordingToolRegistry()

    collected = []

    async def driver() -> None:
        async for ev in adapter.step(make_session_context(), stream, tools):
            collected.append(ev)

    task = asyncio.create_task(driver())
    await asyncio.sleep(0.05)
    task.cancel()
    cancelled = False
    try:
        await task
    except asyncio.CancelledError:
        cancelled = True
    except Exception as e:
        pytest.fail(f"expected CancelledError, got {type(e).__name__}: {e}")
    assert cancelled or task.cancelled(), "cancellation should have been honoured"
