"""Tests for LangGraphAdapter with a ReAct-style agent.

These tests use ``langgraph.prebuilt.create_react_agent`` with a fake
chat model that scripts the assistant's responses. No real LLM is
invoked.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
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

if TYPE_CHECKING:
    from langchain_core.runnables import Runnable


class _FakeChatWithToolBinding(FakeMessagesListChatModel):
    """``FakeMessagesListChatModel`` that also implements ``bind_tools``.

    LangGraph's ``create_react_agent`` calls ``bind_tools`` on the
    supplied model. The default Fake model doesn't implement it; this
    subclass just returns ``self`` so the scripted responses are still
    authoritative.
    """

    def bind_tools(
        self,
        tools: Any,
        *,
        tool_choice: Any = None,
        **kwargs: Any,
    ) -> Runnable:
        return self


def _now() -> datetime:
    return datetime.now(UTC)


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
    def __init__(self, descs: list[ToolDescriptor]) -> None:
        self._descs = descs
        self.calls: list[tuple[str, dict[str, Any], str]] = []

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
        self.calls.append((name, input, tool_use_id))
        return ToolResult(
            content=[TextBlock(text=f"wake-ran:{input}")],
            is_error=False,
        )


def _ctx() -> SessionContext:
    return SessionContext(
        session_id="s",
        agent_id="a",
        agent_version=1,
        agent_config=AgentConfig(
            id="a",
            name="t",
            model=ModelConfig(id="m"),
            created_at=_now(),
            updated_at=_now(),
        ),
    )


def _user_msg(seq: int, text: str) -> Event:
    return Event(
        id=f"e{seq}",
        session_id="s",
        seq=seq,
        type="user.message",
        payload={"content": [{"type": "text", "text": text}]},
        created_at=_now(),
    )


@tool
def get_weather(city: str) -> str:
    """Return the weather for a city."""
    return f"sunny in {city}"


# ---------------------------------------------------------------------------
# ReAct agent with one tool call + final response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_react_agent_with_tool_call() -> None:
    """A ReAct agent that calls one tool then produces a final answer."""
    # Skip if create_react_agent isn't available in this LangGraph version.
    pytest.importorskip("langgraph.prebuilt")
    from langgraph.prebuilt import create_react_agent

    # Script the fake model: first emits an AIMessage with a tool_call,
    # then emits the final AIMessage. ``bind_tools`` on this model is a
    # no-op in fake mode — it ignores the tools and just walks the
    # scripted list, but the agent still routes through our injected
    # tool node when tool_calls are present.
    responses = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "get_weather",
                    "args": {"city": "Lisbon"},
                    "id": "tu_1",
                    "type": "tool_call",
                }
            ],
        ),
        AIMessage(content="It's sunny."),
    ]
    fake_llm = _FakeChatWithToolBinding(responses=responses)

    agent = create_react_agent(fake_llm, [get_weather])

    adapter = LangGraphAdapter(agent, emit_deltas=False)
    stream = _ListStream([_user_msg(0, "weather in Lisbon?")])
    reg = _Registry(descs=[
        ToolDescriptor(
            name="get_weather",
            description="weather",
            schema={
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        )
    ])

    emitted: list[Event] = []
    async for ev in adapter.step(_ctx(), stream, reg):
        emitted.append(ev)
        stream.append(ev)

    types = [e.type for e in emitted]
    assert "tool_use" in types
    assert "tool_result" in types
    assert "assistant.message" in types

    # Wake registry got the tool call.
    assert reg.calls == [("get_weather", {"city": "Lisbon"}, "tu_1")]

    # Final assistant.message text says it's sunny.
    finals = [e for e in emitted if e.type == "assistant.message"]
    assert any(
        "sunny" in (b.get("text", "") for b in (e.payload.get("content") or []))
        or "sunny" in str(e.payload)
        for e in finals
    )
