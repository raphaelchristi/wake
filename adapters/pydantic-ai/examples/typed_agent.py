"""Runnable example: typed Pydantic AI agent driven by the Wake adapter.

Run::

    python -m wake_adapter_pydantic_ai.examples.typed_agent
    # or
    python adapters/pydantic-ai/examples/typed_agent.py

The example uses :class:`pydantic_ai.models.function.FunctionModel` so
no real LLM credentials are needed — the agent is deterministic and
self-contained. It demonstrates:

* Building a :class:`PydanticAIAdapter` from a typed
  :class:`pydantic_ai.Agent` (``output_type=ResearchResult``).
* Driving it through one Wake step with an in-memory event log and a
  user-registered ``lookup`` tool.
* Emitting and printing the canonical Wake events.

The plumbing (in-memory ``EventStream`` / ``ToolRegistry``) is
intentionally minimal — in production, Wake's runtime dispatcher
provides these.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from wake_adapter_pydantic_ai import PydanticAIAdapter

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
# 1. Define a typed output schema. Pydantic AI will coerce the model's
#    final answer into this Pydantic model.
# ---------------------------------------------------------------------------


class ResearchResult(BaseModel):
    answer: str
    sources: list[str]
    confidence: float


# ---------------------------------------------------------------------------
# 2. Build a deterministic agent using FunctionModel.
#
#    The stream function:
#      • First call → ask the wake-registered ``lookup`` tool.
#      • Second call → return the structured ResearchResult.
# ---------------------------------------------------------------------------


async def _scripted_stream(messages, info: AgentInfo):  # type: ignore[no-untyped-def]
    has_returns = any(
        any(getattr(p, "part_kind", None) == "tool-return" for p in m.parts)
        for m in messages
    )
    if not has_returns:
        yield {
            0: DeltaToolCall(
                name="lookup",
                json_args=json.dumps({"query": "wake"}),
                tool_call_id="t1",
            )
        }
        return
    # Second pass: emit the typed final_result tool call.
    out_name = info.output_tools[0].name if info.output_tools else "final_result"
    payload = json.dumps(
        {
            "answer": "Wake is a durable runtime substrate for AI agents.",
            "sources": ["docs/SPEC-HARNESS-ADAPTER.md"],
            "confidence": 0.92,
        }
    )
    yield {0: DeltaToolCall(name=out_name, json_args=payload, tool_call_id="r1")}


agent: Agent[None, ResearchResult] = Agent(
    FunctionModel(stream_function=_scripted_stream),
    output_type=ResearchResult,
    system_prompt="You are a research assistant. Use the lookup tool and produce a typed result.",
)


# ---------------------------------------------------------------------------
# 3. Minimal in-memory Wake plumbing.
# ---------------------------------------------------------------------------


class _ListStream(EventStream):  # type: ignore[misc]
    def __init__(self, events: list[Event] | None = None) -> None:
        self._events: list[Event] = list(events or [])

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


class _MemRegistry(ToolRegistry):  # type: ignore[misc]
    def __init__(self) -> None:
        self._descs: list[ToolDescriptor] = []

    def add(self, desc: ToolDescriptor) -> None:
        self._descs.append(desc)

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
        print(f"  [runtime] tools.execute({name=}, {input=}, {tool_use_id=})")
        return ToolResult(
            content=[TextBlock(text=f"lookup result for {input.get('query', '?')}")],
            is_error=False,
        )


# ---------------------------------------------------------------------------
# 4. Drive one step()
# ---------------------------------------------------------------------------


async def main() -> None:
    now = datetime.now(UTC)
    agent_config = AgentConfig(
        id="research_agent",
        name="research",
        model=ModelConfig(id="function-test", provider="test"),
        system=None,
        created_at=now,
        updated_at=now,
    )
    ctx = SessionContext(
        session_id="sess_demo",
        agent_id=agent_config.id,
        agent_version=1,
        agent_config=agent_config,
    )

    stream = _ListStream(
        [
            Event(
                id="e0",
                session_id=ctx.session_id,
                seq=0,
                type="user.message",
                payload={
                    "content": [
                        {"type": "text", "text": "What is wake? Use the lookup tool."}
                    ]
                },
                created_at=now,
            )
        ]
    )
    tools = _MemRegistry()
    tools.add(
        ToolDescriptor(
            name="lookup",
            description="Look up information about a topic.",
            schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )
    )

    adapter = PydanticAIAdapter(agent)

    print("=" * 70)
    print("Pydantic AI ↔ Wake adapter demo")
    print("=" * 70)
    async for ev in adapter.step(ctx, stream, tools):
        seq = await stream.count()
        new_ev = Event(
            id=f"e{seq}",
            session_id=ev.session_id,
            seq=seq,
            type=ev.type,
            payload=ev.payload,
            parent_id=ev.parent_id,
            metadata=ev.metadata,
            created_at=ev.created_at,
        )
        stream.append(new_ev)
        if ev.type == "assistant.delta":
            print(f"  [delta] {ev.payload['delta']['text']!r}")
        elif ev.type == "tool_use":
            print(
                f"  [tool_use] name={ev.payload['name']} "
                f"input={ev.payload['input']} id={ev.payload['tool_use_id']}"
            )
        elif ev.type == "tool_result":
            txt = ev.payload["content"][0]["text"]
            print(
                f"  [tool_result] id={ev.payload['tool_use_id']} "
                f"is_error={ev.payload['is_error']} text={txt!r}"
            )
        elif ev.type == "assistant.message":
            print("  [assistant.message]")
            for block in ev.payload["content"]:
                if block.get("type") == "text":
                    print(f"    text: {block['text']}")
                elif block.get("type") == "tool_use":
                    print(f"    tool_use: {block['name']}({block['input']})")
        else:
            print(f"  [{ev.type}] {ev.payload}")

    print("=" * 70)
    print(f"Final log: {await stream.count()} event(s)")


if __name__ == "__main__":
    asyncio.run(main())
