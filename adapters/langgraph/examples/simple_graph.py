"""Runnable example: a tiny LangGraph StateGraph on Wake.

The graph has two nodes:

1. ``model`` — looks at the latest ``HumanMessage`` and either:
   - asks the ``echo`` tool to reflect the input, then
   - produces a final assistant response.
2. ``tools`` — a ``ToolNode``; at runtime the Wake adapter replaces
   this with a Wake-aware node that calls ``tools.execute()`` for
   every tool_call.

No real LLM is invoked — the ``model`` node hand-rolls AIMessages so
the example is deterministic and offline-friendly. Run it directly:

    python -m examples.simple_graph

(from the ``adapters/langgraph/`` directory).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated, Any, TypedDict

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.tools import tool
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
# 1. Build a LangGraph StateGraph
# ---------------------------------------------------------------------------


class State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


@tool
def echo(text: str) -> str:
    """Echo the input text."""
    return text


def model(state: State) -> dict[str, list[BaseMessage]]:
    """Decide between calling the ``echo`` tool and ending the turn.

    First call (after a ``HumanMessage``) emits an AIMessage with a
    tool_call. Subsequent call (after a ``ToolMessage``) emits the
    final assistant response.
    """
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
                            "args": {"text": last.content or ""},
                            "id": "tu_1",
                            "type": "tool_call",
                        }
                    ],
                )
            ]
        }
    if isinstance(last, ToolMessage):
        return {
            "messages": [
                AIMessage(content=f"The tool said: {last.content}")
            ]
        }
    return {"messages": [AIMessage(content="ok")]}


def should_continue(state: State) -> str:
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return END


def build_graph() -> Any:
    builder: StateGraph = StateGraph(State)
    builder.add_node("model", model)
    builder.add_node("tools", ToolNode([echo]))
    builder.add_edge(START, "model")
    builder.add_conditional_edges(
        "model",
        should_continue,
        {"tools": "tools", END: END},
    )
    builder.add_edge("tools", "model")
    return builder.compile()


# ---------------------------------------------------------------------------
# 2. Provide a minimal Wake runtime (in-memory)
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


class _Stream(EventStream):
    def __init__(self) -> None:
        self._events: list[Event] = []

    def append(self, ev: Event) -> None:
        self._events.append(ev)

    def add_user(self, text: str) -> None:
        self._events.append(
            Event(
                id=f"e{len(self._events)}",
                session_id="demo",
                seq=len(self._events),
                type="user.message",
                payload={"content": [{"type": "text", "text": text}]},
                created_at=_now(),
            )
        )

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
    def __init__(self) -> None:
        self._descs: list[ToolDescriptor] = [
            ToolDescriptor(
                name="echo",
                description="Echo input",
                schema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            )
        ]

    def list(self) -> list[ToolDescriptor]:
        return list(self._descs)

    def get(self, name: str) -> ToolDescriptor:
        for d in self._descs:
            if d.name == name:
                return d
        raise KeyError(name)

    async def execute(
        self, name: str, input: dict[str, Any], *, tool_use_id: str  # noqa: A002
    ) -> ToolResult:
        # Real Wake routes here through permission policy + sandbox.
        # In this offline demo we just echo.
        print(f"[wake.execute] {name}({input}) tool_use_id={tool_use_id}")
        return ToolResult(
            content=[TextBlock(text=f"echoed by wake: {input.get('text', '')}")],
            is_error=False,
        )


def _ctx() -> SessionContext:
    return SessionContext(
        session_id="demo",
        agent_id="demo-agent",
        agent_version=1,
        agent_config=AgentConfig(
            id="demo-agent",
            name="demo",
            model=ModelConfig(id="fake-model"),
            created_at=_now(),
            updated_at=_now(),
        ),
    )


# ---------------------------------------------------------------------------
# 3. Run
# ---------------------------------------------------------------------------


async def main() -> None:
    graph = build_graph()
    adapter = LangGraphAdapter(graph, emit_deltas=False)

    events = _Stream()
    events.add_user("hello from langgraph")
    registry = _Registry()

    print("\n--- Wake event log ---")
    print(f"  before: {len(await events.all())} event(s)")

    print("\n--- adapter.step() output ---")
    async for ev in adapter.step(_ctx(), events, registry):
        events.append(ev)
        if ev.type == "assistant.message":
            text_blocks = [
                b.get("text", "")
                for b in (ev.payload.get("content") or [])
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            print(f"  assistant.message: {''.join(text_blocks)!r}")
        elif ev.type == "tool_use":
            print(
                f"  tool_use: name={ev.payload['name']} "
                f"input={ev.payload['input']} id={ev.payload['tool_use_id']}"
            )
        elif ev.type == "tool_result":
            text = ev.payload.get("content", [{}])[0].get("text", "")
            print(f"  tool_result: {text!r}")
        else:
            print(f"  {ev.type}: {ev.payload}")

    print(f"\n  after:  {len(await events.all())} event(s)")


if __name__ == "__main__":
    asyncio.run(main())
