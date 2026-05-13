"""Core unit tests for ``LangGraphAdapter``.

Covers identity fields, Protocol conformance, constructor variants,
and the ``on_lifecycle`` no-op contract.
"""

from __future__ import annotations

from datetime import UTC
from typing import Annotated, TypedDict

import pytest
from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from wake_adapter_langgraph import LangGraphAdapter, create

from wake.adapters import HarnessAdapter


class _State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


def _trivial_node(state: _State) -> dict[str, list[BaseMessage]]:
    return {"messages": [AIMessage(content="hi")]}


def _build_trivial_graph() -> object:
    b: StateGraph = StateGraph(_State)
    b.add_node("model", _trivial_node)
    b.add_edge(START, "model")
    b.add_edge("model", END)
    return b.compile()


# ---------------------------------------------------------------------------
# Identity + Protocol conformance
# ---------------------------------------------------------------------------


def test_adapter_identity_fields() -> None:
    adapter = LangGraphAdapter(_build_trivial_graph())
    assert adapter.name == "langgraph"
    assert adapter.version == "0.1.0"
    assert adapter.compatibility == "wake-harness-adapter@^0.1"


def test_adapter_implements_protocol() -> None:
    adapter = LangGraphAdapter(_build_trivial_graph())
    assert isinstance(adapter, HarnessAdapter)


def test_create_factory_returns_default_adapter() -> None:
    adapter = create()
    assert isinstance(adapter, LangGraphAdapter)
    assert adapter.name == "langgraph"
    assert isinstance(adapter, HarnessAdapter)


def test_constructor_accepts_compiled_graph() -> None:
    graph = _build_trivial_graph()
    adapter = LangGraphAdapter(graph)
    assert adapter.graph is graph


def test_constructor_accepts_none_for_default_graph_mode() -> None:
    adapter = LangGraphAdapter(None)
    assert adapter.graph is None


def test_state_key_default_and_override() -> None:
    g = _build_trivial_graph()
    a1 = LangGraphAdapter(g)
    a2 = LangGraphAdapter(g, state_key="chat")
    assert a1.state_key == "messages"
    assert a2.state_key == "chat"


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_lifecycle_is_noop_for_all_events() -> None:
    from datetime import datetime

    from wake.adapters import SessionContext
    from wake.types import AgentConfig, ModelConfig

    adapter = LangGraphAdapter(_build_trivial_graph())
    now = datetime.now(UTC)
    ctx = SessionContext(
        session_id="s",
        agent_id="a",
        agent_version=1,
        agent_config=AgentConfig(
            id="a", name="x", model=ModelConfig(id="m"),
            created_at=now, updated_at=now,
        ),
    )
    for lc in ("created", "resumed", "interrupted", "terminated"):
        assert await adapter.on_lifecycle(ctx, lc) is None  # type: ignore[arg-type]
