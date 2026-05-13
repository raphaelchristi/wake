"""Tests for ``tool_injection`` — Wake tools → LangGraph tool node."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from wake_adapter_langgraph.tool_injection import (
    WakeToolWrapper,
    inject_wake_tools,
    wake_tool_node,
    wake_tools_for_langchain,
)

from wake.adapters import ToolRegistry
from wake.types import TextBlock, ToolDescriptor, ToolResult


class _FakeRegistry(ToolRegistry):
    def __init__(self, descs: list[ToolDescriptor]) -> None:
        self._descs = descs
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
            content=[TextBlock(text=f"ok:{input}")],
            is_error=False,
        )


def _desc(name: str, schema: dict[str, Any] | None = None) -> ToolDescriptor:
    return ToolDescriptor(
        name=name,
        description=f"tool {name}",
        schema=schema or {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )


# ---------------------------------------------------------------------------
# wake_tools_for_langchain — wrapper construction
# ---------------------------------------------------------------------------


def test_wake_tools_for_langchain_wraps_each_descriptor() -> None:
    reg = _FakeRegistry([_desc("a"), _desc("b")])
    wrapped = wake_tools_for_langchain(reg)
    assert len(wrapped) == 2
    assert {t.name for t in wrapped} == {"a", "b"}
    for t in wrapped:
        assert isinstance(t, BaseTool)
        assert isinstance(t, WakeToolWrapper)


@pytest.mark.asyncio
async def test_wake_tool_wrapper_arun_calls_registry() -> None:
    reg = _FakeRegistry([_desc("echo")])
    wrapped = wake_tools_for_langchain(reg)[0]
    text = await wrapped._arun(text="hello")
    assert "ok" in text
    assert reg.calls[0][0] == "echo"
    assert reg.calls[0][1] == {"text": "hello"}


def test_wake_tool_wrapper_sync_run_raises() -> None:
    reg = _FakeRegistry([_desc("echo")])
    wrapped = wake_tools_for_langchain(reg)[0]
    with pytest.raises(NotImplementedError):
        wrapped._run(text="x")


def test_wake_tool_wrapper_args_schema_with_empty_properties() -> None:
    reg = _FakeRegistry([_desc("noargs", schema={"type": "object", "properties": {}})])
    wrapped = wake_tools_for_langchain(reg)[0]
    assert wrapped.args_schema is not None


# ---------------------------------------------------------------------------
# wake_tool_node — replacement for ToolNode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wake_tool_node_executes_tool_calls_via_registry() -> None:
    reg = _FakeRegistry([_desc("echo")])
    node = wake_tool_node(reg)
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "echo",
                        "args": {"text": "hello"},
                        "id": "tu_1",
                        "type": "tool_call",
                    }
                ],
            )
        ]
    }
    out = await node(state)
    assert "messages" in out
    assert len(out["messages"]) == 1
    tm = out["messages"][0]
    assert isinstance(tm, ToolMessage)
    assert tm.tool_call_id == "tu_1"
    assert reg.calls == [("echo", {"text": "hello"}, "tu_1")]


@pytest.mark.asyncio
async def test_wake_tool_node_no_op_when_last_is_not_aimessage() -> None:
    reg = _FakeRegistry([_desc("echo")])
    node = wake_tool_node(reg)
    out = await node({"messages": [HumanMessage(content="hi")]})
    assert out["messages"] == []


@pytest.mark.asyncio
async def test_wake_tool_node_handles_multiple_parallel_calls() -> None:
    reg = _FakeRegistry([_desc("a"), _desc("b")])
    node = wake_tool_node(reg)
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "a", "args": {"text": "1"}, "id": "tu_a", "type": "tool_call"},
                    {"name": "b", "args": {"text": "2"}, "id": "tu_b", "type": "tool_call"},
                ],
            )
        ]
    }
    out = await node(state)
    assert len(out["messages"]) == 2
    ids = {m.tool_call_id for m in out["messages"]}
    assert ids == {"tu_a", "tu_b"}
    assert {c[0] for c in reg.calls} == {"a", "b"}


@pytest.mark.asyncio
async def test_wake_tool_node_marks_error_results_with_status_error() -> None:
    reg = _FakeRegistry([_desc("bad")])
    reg.responses["bad"] = ToolResult(
        content=[TextBlock(text="oops")],
        is_error=True,
        error_code="boom",
    )
    node = wake_tool_node(reg)
    out = await node({
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "bad", "args": {}, "id": "tu", "type": "tool_call"}],
            )
        ]
    })
    tm = out["messages"][0]
    assert tm.status == "error"
    assert tm.content == "oops"


@pytest.mark.asyncio
async def test_wake_tool_node_handles_exception() -> None:
    class _BrokenRegistry(_FakeRegistry):
        async def execute(self, name: str, input: dict[str, Any], *, tool_use_id: str) -> ToolResult:  # noqa: A002
            raise RuntimeError("boom")

    reg = _BrokenRegistry([_desc("x")])
    node = wake_tool_node(reg)
    out = await node({
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "x", "args": {}, "id": "tu", "type": "tool_call"}],
            )
        ]
    })
    tm = out["messages"][0]
    assert tm.status == "error"
    assert "RuntimeError" in tm.content


# ---------------------------------------------------------------------------
# inject_wake_tools — graph rewriting
# ---------------------------------------------------------------------------


class _State(TypedDict):
    messages: Annotated[list, add_messages]


def _model(state: _State) -> dict[str, list]:
    return {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "echo", "args": {"text": "x"}, "id": "tu_1", "type": "tool_call"}
                ],
            )
        ]
    }


def _final(state: _State) -> dict[str, list]:
    return {"messages": [AIMessage(content="done")]}


def _cond(state: _State) -> str:
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return END


def _graph_with_toolnode() -> Any:
    from langchain_core.tools import tool

    @tool
    def echo(text: str) -> str:
        """Echo."""
        return text

    b: StateGraph = StateGraph(_State)
    b.add_node("model", _model)
    b.add_node("tools", ToolNode([echo]))
    b.add_node("final", _final)
    b.add_edge(START, "model")
    b.add_conditional_edges("model", _cond, {"tools": "tools", END: END})
    b.add_edge("tools", "final")
    b.add_edge("final", END)
    return b.compile()


@pytest.mark.asyncio
async def test_inject_wake_tools_replaces_toolnode_in_graph() -> None:
    reg = _FakeRegistry([_desc("echo")])
    graph = _graph_with_toolnode()
    new_graph = inject_wake_tools(graph, reg)

    # New graph is a fresh compiled graph (not the same instance).
    assert new_graph is not graph

    # Drive the new graph; the registry should record the tool call.
    state = {"messages": [HumanMessage(content="go")]}
    async for _ in new_graph.astream(state, stream_mode="updates"):
        pass

    assert reg.calls == [("echo", {"text": "x"}, "tu_1")]


def test_inject_wake_tools_returns_same_graph_when_no_toolnode() -> None:
    """A graph without any ToolNode is not rewritten — same instance back."""

    def _node(state: _State) -> dict[str, list]:
        return {"messages": [AIMessage(content="x")]}

    b: StateGraph = StateGraph(_State)
    b.add_node("only", _node)
    b.add_edge(START, "only")
    b.add_edge("only", END)
    graph = b.compile()

    reg = _FakeRegistry([])
    new_graph = inject_wake_tools(graph, reg)
    assert new_graph is graph
