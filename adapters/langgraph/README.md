# wake-adapter-langgraph

A [Wake](https://github.com/raphaelchristi/wake) `HarnessAdapter` that
runs [LangGraph](https://github.com/langchain-ai/langgraph)
`StateGraph`s on top of Wake's durable runtime substrate (event log,
sandbox, vault, lifecycle).

`v0.1.0` — implements
[`docs/SPEC-HARNESS-ADAPTER.md`](../../docs/SPEC-HARNESS-ADAPTER.md)
v0.1.0. Passes **10/10** scenarios of the `wake-test-conformance`
suite.

## Install

From the Wake monorepo (editable, recommended while pre-alpha):

```bash
cd adapters/langgraph
pip install -e ".[dev]"
```

Dependencies: `langgraph>=1.0,<2.0`, `langchain-core>=0.3`,
`wake-ai>=0.0.1`, `pydantic>=2.9`.

## What it does

1. Reads the Wake event log via `events.all()` and translates events to
   LangChain `BaseMessage` objects (see
   [`event_mapping.py`](./src/wake_adapter_langgraph/event_mapping.py)):
   - `user.message` → `HumanMessage`
   - `assistant.message` → `AIMessage` (with embedded `tool_use` blocks
     surfaced as `tool_calls`)
   - `tool_use` → `tool_calls` attached to the trailing `AIMessage`
   - `tool_result` → `ToolMessage`
2. Streams the user's compiled `StateGraph` via `astream(stream_mode=
   ["updates", "messages"])`.
3. For every new message in a per-node update, yields Wake events:
   - `AIMessage` (text) → `assistant.message`
   - `AIMessage` (with `tool_calls`) → one `tool_use` per call, then
     the aggregate `assistant.message`
   - `ToolMessage` → `tool_result`
4. Token-level streaming (when `emit_deltas=True`) emits
   `assistant.delta` events from the `"messages"` stream.
5. Tool execution is routed through `tools.execute(name, input,
   tool_use_id=...)` by deep-cloning the graph's builder, replacing
   every `langgraph.prebuilt.ToolNode` with a Wake-aware async node,
   and recompiling at the start of each `step()`. See
   [`tool_injection.py`](./src/wake_adapter_langgraph/tool_injection.py).

## Quick start

```python
from typing import Annotated, TypedDict
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from wake_adapter_langgraph import LangGraphAdapter


class State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


def model(state: State) -> dict:
    return {"messages": [AIMessage(content="hello from langgraph")]}


builder = StateGraph(State)
builder.add_node("model", model)
builder.add_edge(START, "model")
builder.add_edge("model", END)
graph = builder.compile()

adapter = LangGraphAdapter(graph)
# adapter is now a `HarnessAdapter`; pass it to your Wake runtime.
```

For a runnable end-to-end demo (graph + Wake event log + tool routing,
no LLM), see
[`examples/simple_graph.py`](./examples/simple_graph.py):

```bash
python examples/simple_graph.py
```

## ReAct agents

The adapter supports `langgraph.prebuilt.create_react_agent`. The
agent's tool node is detected and replaced at runtime — no code
changes required:

```python
from langgraph.prebuilt import create_react_agent

agent = create_react_agent(my_chat_model, [my_tool_1, my_tool_2])
adapter = LangGraphAdapter(agent)
```

See [`tests/test_react_agent.py`](./tests/test_react_agent.py) for a
worked example with a `FakeMessagesListChatModel`.

## Constructor reference

```python
LangGraphAdapter(
    graph: CompiledStateGraph | None,
    *,
    state_key: str = "messages",
    emit_deltas: bool = True,
)
```

- `graph` — your compiled `StateGraph`. Pass `None` to get the
  built-in default echo graph (used by the `wake.adapters` entry-point
  factory; ideal for end-to-end smoke tests).
- `state_key` — the field in your graph state where messages live.
  Defaults to `"messages"`. Override only if you use a different key.
- `emit_deltas` — when `True` (default), the adapter subscribes to
  `astream(stream_mode="messages")` and emits `assistant.delta` events
  for token-level streaming. Set `False` for non-streaming UIs.

## Conformance

Passes **10/10** scenarios of `wake-test-conformance` v0.1.0:

| Scenario | Status | Notes |
|---|---|---|
| `basic_step` | PASS | |
| `tool_use` | PASS | |
| `streaming` | PASS | `assistant.delta` emitted before final `assistant.message` |
| `cancellation` | PASS | `asyncio.CancelledError` propagates |
| `resume` | PASS | tool_use_ids and assistant text are de-duped on second step() |
| `parallel_tools` | PASS | Multiple `tool_call`s on one `AIMessage` |
| `error_handling` | PASS | Failing tools → `ToolMessage(status="error")` |
| `pause_turn` | PASS (warning) | LangGraph has no native pause primitive |
| `lifecycle` | PASS | `on_lifecycle()` is a no-op |
| `idempotence` | PASS | |

Run the suite:

```bash
pytest tests/test_conformance.py -v
```

## Run all tests

```bash
pytest -v
```

The suite includes:

- `tests/test_adapter.py` — identity, Protocol conformance, lifecycle
- `tests/test_event_mapping.py` — events ↔ LangChain messages
- `tests/test_tool_injection.py` — `WakeToolWrapper`, `wake_tool_node`,
  `inject_wake_tools`
- `tests/test_simple_graph.py` — end-to-end with a `StateGraph`
  (linear + conditional + tool node)
- `tests/test_react_agent.py` — `create_react_agent` with a fake
  chat model
- `tests/test_conformance.py` — the full conformance suite

All tests are offline-only: no real LLM, no network, no Wake runtime.

## Design notes

### Graph rewriting

Every `step()` deep-copies `graph.builder`, walks `builder.nodes`, and
swaps the `runnable` attribute of every node whose runnable is a
`langgraph.prebuilt.ToolNode` with a Wake-aware async function that
calls `tools.execute()`. The result is recompiled and discarded after
the step — the original graph is never mutated.

For graphs where the user binds tools directly to a model (no
`ToolNode`), the model's tool decisions still surface as `tool_calls`
on its emitted `AIMessage`, which `events_to_state` propagates back to
the log — but in that path the tool execution still happens inside the
model node (no Wake routing). Use a `ToolNode` if you need Wake
permission/sandbox/vault enforcement.

### Streaming

`stream_mode=["updates", "messages"]` gives us both kinds of signal in
one stream: `"updates"` for the structural per-node deltas (which we
translate to Wake events) and `"messages"` for the token-by-token
streaming (which we translate to `assistant.delta`). Set
`emit_deltas=False` to halve the streaming chatter for non-streaming
consumers.

### Resume

The HarnessAdapter contract requires `step()` to be safe to call
twice on the same log. The adapter consults `events.all()` to build
sets of already-emitted `tool_use_id`s, `tool_result` ids, and
`assistant.message` texts; new messages that would duplicate these
are dropped before yielding. This keeps the runtime's idempotence
invariant intact even though LangGraph itself is replay-friendly only
via checkpointers (which we deliberately don't use — Wake's event log
*is* the checkpoint).

### Pause / interrupt

LangGraph v1 has no first-class pause primitive that maps cleanly to
Wake's `pause_turn`. The conformance scenario passes with a warning
indicating the gap. A future spec amendment (`v0.2.0`) may add a
LangGraph-specific hook.

## License

Apache-2.0, same as Wake core.
