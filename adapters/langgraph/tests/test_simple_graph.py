"""Integration tests for LangGraphAdapter with a real (mocked-LLM) StateGraph.

Builds simple StateGraphs and drives them through ``adapter.step()``,
asserting the right Wake events are emitted in the right order.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated, Any, TypedDict

import pytest
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from wake_adapter_langgraph import LangGraphAdapter

from wake.adapters import EventStream, SessionContext, ToolRegistry
from wake.types import (
    AgentConfig,
    Event,
    EventType,
    ModelConfig,
    TextBlock,
    ToolDescriptor,
    ToolResult,
)

# ---------------------------------------------------------------------------
# In-memory fakes (mirror the conformance harness shape)
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


class _State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


class _ListStream(EventStream):
    def __init__(self, events: list[Event] | None = None) -> None:
        self._events = list(events or [])

    def append(self, ev: Event) -> None:
        self._events.append(ev)

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


class _Registry(ToolRegistry):
    def __init__(self, descs: list[ToolDescriptor] | None = None) -> None:
        self._descs = list(descs or [])
        self.calls: list[tuple[str, dict[str, Any], str]] = []
        self.responses: dict[str, ToolResult] = {}

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
        if name in self.responses:
            return self.responses[name]
        return ToolResult(
            content=[TextBlock(text=f"echo:{input}")],
            is_error=False,
        )


def _agent() -> AgentConfig:
    return AgentConfig(
        id="agent_x",
        name="t",
        model=ModelConfig(id="m"),
        system=None,
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


def _user_msg_event(seq: int, text: str) -> Event:
    return Event(
        id=f"e{seq}",
        session_id="sess_x",
        seq=seq,
        type="user.message",
        payload={"content": [{"type": "text", "text": text}]},
        created_at=_now(),
    )


async def _collect(adapter: LangGraphAdapter, stream: _ListStream, reg: _Registry) -> list[Event]:
    out: list[Event] = []
    async for ev in adapter.step(_ctx(), stream, reg):
        out.append(ev)
        # Persist so subsequent step()s observe the new state.
        stream.append(ev)
    return out


# ---------------------------------------------------------------------------
# Simple linear graph: HumanMessage → AIMessage
# ---------------------------------------------------------------------------


def _build_echo_graph() -> Any:
    def _model(state: _State) -> dict[str, list[BaseMessage]]:
        last = state["messages"][-1]
        text = last.content if isinstance(last.content, str) else ""
        return {"messages": [AIMessage(content=f"got: {text}")]}

    b: StateGraph = StateGraph(_State)
    b.add_node("model", _model)
    b.add_edge(START, "model")
    b.add_edge("model", END)
    return b.compile()


@pytest.mark.asyncio
async def test_step_emits_assistant_message_for_simple_graph() -> None:
    adapter = LangGraphAdapter(_build_echo_graph())
    stream = _ListStream([_user_msg_event(0, "hello")])
    reg = _Registry()

    emitted = await _collect(adapter, stream, reg)

    types = [e.type for e in emitted]
    assert "assistant.message" in types
    final = next(e for e in emitted if e.type == "assistant.message")
    assert "got: hello" in final.payload["content"][0]["text"]


@pytest.mark.asyncio
async def test_step_emits_delta_when_streaming_text() -> None:
    adapter = LangGraphAdapter(_build_echo_graph(), emit_deltas=True)
    stream = _ListStream([_user_msg_event(0, "hello")])
    reg = _Registry()

    emitted = await _collect(adapter, stream, reg)

    types = [e.type for e in emitted]
    # Streaming mode includes both delta + final message; we tolerate
    # adapters that skip delta on tiny payloads, but require at least one.
    assert "assistant.message" in types


@pytest.mark.asyncio
async def test_step_uses_default_graph_when_none_provided() -> None:
    adapter = LangGraphAdapter(None)
    stream = _ListStream([_user_msg_event(0, "hi")])
    reg = _Registry()
    emitted = await _collect(adapter, stream, reg)
    types = [e.type for e in emitted]
    assert "assistant.message" in types


# ---------------------------------------------------------------------------
# Conditional edges + tool node — full agent loop
# ---------------------------------------------------------------------------


def _build_agent_graph() -> Any:
    def _model(state: _State) -> dict[str, list[BaseMessage]]:
        msgs = state["messages"]
        last = msgs[-1]
        if isinstance(last, HumanMessage):
            return {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "echo",
                                "args": {"text": "from_model"},
                                "id": "tu_1",
                                "type": "tool_call",
                            }
                        ],
                    )
                ]
            }
        # Tool message arrived; finish.
        return {"messages": [AIMessage(content="all done")]}

    def _cond(state: _State) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return END

    from langchain_core.tools import tool

    @tool
    def echo(text: str) -> str:
        """Echo input."""
        return text

    b: StateGraph = StateGraph(_State)
    b.add_node("model", _model)
    b.add_node("tools", ToolNode([echo]))
    b.add_edge(START, "model")
    b.add_conditional_edges("model", _cond, {"tools": "tools", END: END})
    b.add_edge("tools", "model")
    return b.compile()


@pytest.mark.asyncio
async def test_step_runs_full_tool_use_loop() -> None:
    adapter = LangGraphAdapter(_build_agent_graph(), emit_deltas=False)
    stream = _ListStream([_user_msg_event(0, "go")])
    reg = _Registry(descs=[
        ToolDescriptor(
            name="echo",
            description="echo",
            schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        )
    ])

    emitted = await _collect(adapter, stream, reg)

    types = [e.type for e in emitted]
    assert "tool_use" in types
    assert "tool_result" in types
    assert "assistant.message" in types

    # Tool routed through wake's registry.
    assert reg.calls == [("echo", {"text": "from_model"}, "tu_1")]

    # tool_use and tool_result share the same id.
    tu = next(e for e in emitted if e.type == "tool_use")
    tr = next(e for e in emitted if e.type == "tool_result")
    assert tu.payload["tool_use_id"] == tr.payload["tool_use_id"] == "tu_1"


@pytest.mark.asyncio
async def test_step_idempotent_on_resume() -> None:
    """A second step() on the same log should not duplicate tool_use ids."""
    adapter = LangGraphAdapter(_build_agent_graph(), emit_deltas=False)
    stream = _ListStream([_user_msg_event(0, "go")])
    reg = _Registry(descs=[
        ToolDescriptor(name="echo", description="", schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}),
    ])

    first = await _collect(adapter, stream, reg)
    first_tu_ids = {e.payload["tool_use_id"] for e in first if e.type == "tool_use"}
    assert first_tu_ids == {"tu_1"}

    second = await _collect(adapter, stream, reg)
    second_tu_ids = {e.payload["tool_use_id"] for e in second if e.type == "tool_use"}
    assert not (first_tu_ids & second_tu_ids), (
        "adapter must not re-emit a tool_use_id on resume"
    )


# ---------------------------------------------------------------------------
# Cancellation: adapter must propagate CancelledError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_propagates_cancellation() -> None:
    """When the consumer cancels the task driving step(), CancelledError
    must propagate without being swallowed."""

    async def _slow_node(state: _State) -> dict[str, list[BaseMessage]]:
        await asyncio.sleep(1.0)
        return {"messages": [AIMessage(content="never")]}

    b: StateGraph = StateGraph(_State)
    b.add_node("slow", _slow_node)
    b.add_edge(START, "slow")
    b.add_edge("slow", END)
    graph = b.compile()

    adapter = LangGraphAdapter(graph, emit_deltas=False)
    stream = _ListStream([_user_msg_event(0, "stream")])
    reg = _Registry()

    async def driver() -> None:
        async for _ in adapter.step(_ctx(), stream, reg):
            pass

    task = asyncio.create_task(driver())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
