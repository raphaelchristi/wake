# Writing a Wake HarnessAdapter

A pragmatic, code-heavy guide to shipping your own `HarnessAdapter` —
the interface that lets any agent framework (LangGraph, CrewAI, Pydantic
AI, your in-house DSL) run on top of Wake's durable substrate.

Audience: you've used an agent framework, you understand Python async,
and you want your framework to gain Wake's event log, sandbox, vault,
and lifecycle without rewriting it.

This is a tutorial. The authoritative spec is
[`SPEC-HARNESS-ADAPTER.md`](./SPEC-HARNESS-ADAPTER.md) — read it once
the code below clicks.

---

## 1. The concept in one paragraph

Wake is a **runtime substrate**, not a framework. It owns the event log
(durable, append-only), the sandbox provisioner, the vault, and the
session lifecycle. It does **not** decide how your agent thinks. That
job belongs to a *harness* — the loop that reads conversation state,
calls an LLM, executes tools, and emits the resulting messages back.

A `HarnessAdapter` is the contract between the two: Wake hands the
adapter a session context plus a read-only view of the event log; the
adapter yields back new events to append. Whatever happens inside the
adapter — a LangGraph supergraph, a CrewAI Crew, three Anthropic
streaming chunks — is opaque to Wake.

Analogy: WSGI (Python) or Servlet (Java). The runtime doesn't care
which framework you use; only that you speak the protocol.

---

## 2. The interface, in fifteen lines

```python
from typing import Protocol, AsyncIterator
from wake.adapters import SessionContext, EventStream, ToolRegistry, LifecycleEvent
from wake.types import Event

class HarnessAdapter(Protocol):
    name: str            # unique, e.g. "claude-sdk" / "langgraph"
    version: str         # semver of your adapter
    compatibility: str   # spec range, e.g. "wake-harness-adapter@^0.1"

    async def step(
        self,
        ctx: SessionContext,
        events: EventStream,
        tools: ToolRegistry,
    ) -> AsyncIterator[Event]: ...

    async def on_lifecycle(
        self,
        ctx: SessionContext,
        event: LifecycleEvent,
    ) -> None: ...
```

That's it. The full narrative — what `step()` may emit, runtime
guarantees, idempotency contract — lives in
[`SPEC-HARNESS-ADAPTER.md`](./SPEC-HARNESS-ADAPTER.md). Don't memorize
it now; come back to it when you hit an edge case.

What follows is the workflow to ship a conformant package.

---

## 3. Package layout

A Wake adapter is a standalone PyPI package. Recommended layout:

```
wake-adapter-myframework/
├── pyproject.toml
├── README.md
├── src/
│   └── wake_adapter_myframework/
│       ├── __init__.py
│       └── adapter.py
└── tests/
    ├── __init__.py
    └── test_adapter.py
```

The `wake_adapter_<framework>` naming isn't enforced, but every
maintained adapter follows it — `wake-adapter-claude-sdk`,
`wake-adapter-langgraph`, etc. Discoverability matters.

### `pyproject.toml`

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "wake-adapter-myframework"
version = "0.1.0"
description = "Wake HarnessAdapter for MyFramework."
requires-python = ">=3.11"
license = "Apache-2.0"
dependencies = [
    "wake-ai>=0.0.1",
    "myframework>=1.0",
    "python-ulid>=3.0",
]

[project.entry-points."wake.adapters"]
myframework = "wake_adapter_myframework.adapter:create"

[tool.hatch.build.targets.wheel]
packages = ["src/wake_adapter_myframework"]
```

The single critical line is the entry-point declaration:

```toml
[project.entry-points."wake.adapters"]
myframework = "wake_adapter_myframework.adapter:create"
```

Once your package is `pip install`-ed, any `AdapterRegistry.discover()`
call will pick it up — no edit to Wake required. This is the same
mechanism `pytest` uses for plugins.

The pointer on the right (`wake_adapter_myframework.adapter:create`)
must resolve to either a `HarnessAdapter` *instance* or a callable that
returns one. Conventionally we expose a no-arg `create()` factory that
returns a default instance, and let advanced users construct the class
directly when they need configuration.

> **PEP 440 trap.** Versions like `"0.1.0-stub"` are *not* valid PyPI
> versions. Use `"0.1.0a0"` in `pyproject.toml` and keep your
> human-readable label on the runtime `version` attribute. The stubs
> in `adapters/langgraph` and `adapters/crewai` do exactly this.

---

## 4. Implementing `step()`

`step()` is the heart of an adapter. The contract:

- **Input**: `ctx` (session context, mostly read-only), `events` (the
  complete event log for this session up to now), `tools` (a filtered
  registry of tool descriptors).
- **Output**: an `AsyncIterator[Event]`. Yield events as you produce
  them; the runtime persists each one before the next is visible.

Pattern 1 — **simple turn**: read events, call the LLM, emit a single
`assistant.message`:

```python
async def step(self, ctx, events, tools):
    history = await events.all()
    messages = [self._to_provider_format(e) for e in history if self._keep(e)]

    response = await self.client.chat.create(
        model=ctx.agent_config.model.id,
        system=ctx.agent_config.system,
        messages=messages,
    )

    yield Event(
        id=str(ULID()),
        session_id=ctx.session_id,
        seq=0,  # runtime reassigns
        type="assistant.message",
        payload={
            "content": [TextBlock(text=response.text).model_dump()],
            "stop_reason": "end_turn",
        },
        created_at=datetime.now(UTC),
    )
```

Pattern 2 — **streaming**: emit `assistant.delta` while the model
produces tokens, then `assistant.message` when the turn closes:

```python
async def step(self, ctx, events, tools):
    async for chunk in self.client.chat.stream(...):
        if chunk.kind == "text_delta":
            yield self._delta_event(ctx, chunk.text)
        elif chunk.kind == "stop":
            yield self._message_event(ctx, chunk.full_text)
            return
```

Pattern 3 — **tool use**: when the model wants to call a tool, **never**
call the underlying Python function. Always go through
`tools.execute()`. That single chokepoint enforces permission policy,
sandbox routing, vault credential injection, and audit logging:

```python
async def step(self, ctx, events, tools):
    async for chunk in self.client.chat.stream(...):
        if chunk.kind == "tool_call":
            yield self._tool_use_event(ctx, chunk)
            result = await tools.execute(
                name=chunk.tool_name,
                input=chunk.tool_input,
                tool_use_id=chunk.id,
            )
            yield self._tool_result_event(ctx, chunk.id, result)
            # loop back into the model with the result
            ...
```

### What you may emit

| Event type            | When                                          |
|-----------------------|-----------------------------------------------|
| `assistant.message`   | Final message of a turn.                      |
| `assistant.delta`     | Incremental token (streaming).                |
| `assistant.thinking`  | Extended thinking content (optional).         |
| `tool_use`            | Before executing a tool — required for audit. |
| `tool_result`         | After executing a tool — required for audit.  |
| `pause_turn`          | Long-running pause (e.g. `max_tokens`).       |
| `error`               | Recoverable error; the loop continues.        |
| `artifact`            | File / blob / URL produced by the agent.      |

You may **not** emit `user.message` or `interrupt` — those come from
clients, never harnesses. See
[`SPEC-EVENT-SCHEMA.md`](./SPEC-EVENT-SCHEMA.md) for the full payload
schema of each type.

### Runtime guarantees, adapter obligations

The runtime promises:

- `events` is the complete log up to this `step()` call.
- `tools` is already filtered by the session's permission policy.
- Each emitted event is persisted before the next one is visible.
- `step()` may be cancelled (`asyncio.CancelledError`). Clean up
  gracefully — no warnings, no half-written state.

You promise:

- Tools are called *only* through `tools.execute(...)`.
- `step()` is **idempotent** within a session. Calling it twice on
  the same event log must not duplicate side-effecting tool calls.
  Use `tool_use_id` for dedup; if a `tool_use` event is already in
  the log with the same `id`, don't replay it.
- The adapter is **stateless** across `step()` calls. The event log
  is your only memory.

---

## 5. Implementing `on_lifecycle()`

Most adapters don't need this. The default — no-op — is fine. Override
only when your framework has expensive setup or teardown that should be
tied to the session lifecycle:

```python
async def on_lifecycle(self, ctx, event):
    if event == "created":
        # compile a LangGraph StateGraph once per session
        self._executor = self._graph.compile(checkpointer=None)
    elif event == "terminated":
        # release framework state
        self._executor = None
```

Possible values: `"created"`, `"resumed"`, `"interrupted"`,
`"terminated"`.

If you make the adapter stateful across `step()`s (via `on_lifecycle`),
keep that state derivable from the event log — Wake may resume the
session in a different process after a crash, and your in-memory state
won't follow.

---

## 6. Adapting framework tools to `ToolRegistry`

Most frameworks have their own tool abstraction (LangChain `BaseTool`,
CrewAI `BaseTool`, Pydantic AI function tools). Your job is to wrap
each Wake `ToolDescriptor` so the framework sees a native object that,
when invoked, routes through `tools.execute()`.

Sketch for LangChain:

```python
from langchain_core.tools import BaseTool

def to_langchain_tool(descriptor, tools_registry):
    class _Proxy(BaseTool):
        name = descriptor.name
        description = descriptor.description
        args_schema = _schema_to_pydantic(descriptor.schema)

        async def _arun(self, **kwargs):
            tool_use_id = str(ULID())
            result = await tools_registry.execute(
                name=descriptor.name,
                input=kwargs,
                tool_use_id=tool_use_id,
            )
            if result.is_error:
                raise RuntimeError(result.content[0].text)
            return result.content[0].text
    return _Proxy()
```

Build the proxy list once per `step()` from `tools.list()`, then hand
it to whatever framework API expects tools.

The critical bit: every path that ends in tool execution must go through
`tools.execute()`. If you accept a framework `Tool` from user code and
call `.run()` on it directly, you've broken the audit chain.

---

## 7. Running the conformance suite

Wake ships [`wake-test-conformance`](../adapters/conformance/) — a
package that exercises your adapter against ten canonical scenarios:
`basic_step`, `tool_use`, `streaming`, `cancellation`, `resume`,
`parallel_tools`, `error_handling`, `pause_turn`, `lifecycle`,
`idempotence`.

```python
# tests/test_conformance.py
import pytest
from wake_test_conformance import run_conformance
from wake_adapter_myframework import MyFrameworkAdapter

@pytest.mark.asyncio
async def test_conformance():
    adapter = MyFrameworkAdapter(client=fake_client_for_determinism)
    report = await run_conformance(adapter)
    assert report.passed, report.summary()
```

A failing scenario prints a deterministic message — usually a missing
event, a wrong `stop_reason`, or a tool called bypassing the registry.
Treat conformance failures as bugs in your adapter, not the suite.

Adapters that pass all scenarios get the `verified` tag in the public
registry. Unverified adapters are still allowed; users see the tag.

The full conformance suite is required for **production** adapters.
Stubs (like `wake-adapter-langgraph` and `wake-adapter-crewai` in this
repo today) are exempt — they only need to prove discoverability and
ABI shape.

---

## 8. Versioning and compatibility

Two numbers matter:

- `version` — the semver of your *adapter package*. Bump freely.
- `compatibility` — the range of the *Wake `HarnessAdapter` ABI* your
  adapter targets, e.g. `"wake-harness-adapter@^0.1"`. The Wake runtime
  uses this field to reject incompatible adapters at registry load.

```python
class MyFrameworkAdapter:
    name = "myframework"
    version = "0.3.2"
    compatibility = "wake-harness-adapter@^0.1"
```

Rules of thumb:

- The ABI is at `v0.1.x` during Phase 2 and 3 — minor breakages
  possible until `v1.0`.
- A major ABI bump (`^0.1 → ^1.0`) means you must audit your adapter
  for the change list in the migration guide. Don't blanket-update.
- Your adapter `version` is independent. A bugfix in `MyFrameworkAdapter`
  bumps your patch number, not Wake's.

---

## 9. Publishing to PyPI

```bash
# inside wake-adapter-myframework/
python -m build
python -m twine upload dist/*
```

Naming convention: `wake-adapter-<framework>` on PyPI, importable as
`wake_adapter_<framework>`. Include the entry point and a clear README
documenting:

- Which framework version(s) you support.
- Required environment (`OPENAI_API_KEY`, etc.).
- Whether the adapter passes the conformance suite.
- Known limitations.

Once published, users get your adapter with:

```bash
pip install wake-ai wake-adapter-myframework
```

…and the next `AdapterRegistry.discover()` call finds it.

---

## 10. Real-world references

Three concrete adapters live in this monorepo:

| Path                              | Status     | What it is                                       |
|-----------------------------------|------------|--------------------------------------------------|
| [`adapters/claude-sdk/`](../adapters/claude-sdk/)   | Production | Full Anthropic Messages API integration with streaming, tool use, parallel tools, pause/resume. The reference adapter — read this first when you need to see what a real `step()` looks like end-to-end. |
| [`adapters/langgraph/`](../adapters/langgraph/)     | **Stub**   | Phase 2 wiring proof for LangGraph. Demonstrates package layout + entry point + Protocol conformance. ~80 LoC of adapter code; emits `"stub from langgraph"` and stops. Full LangGraph integration arrives in Phase 3. |
| [`adapters/crewai/`](../adapters/crewai/)           | **Stub**   | Same shape as the LangGraph stub but for CrewAI. Use either stub as a template when starting your own. |

Look at the stubs first to understand the *minimum viable adapter*,
then read `claude-sdk` to understand a *production* adapter.
[`examples/03-adapter-discovery/`](../examples/03-adapter-discovery/)
runs all three (well, both stubs + the registry) end-to-end in under
ten seconds.

---

## 11. A complete minimal example: the echo adapter

Glue the pieces above into a working adapter you can `pip install -e .`
and use immediately. The echo adapter ignores tools and replies with
whatever the user just said:

```python
# src/wake_adapter_echo/adapter.py
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ulid import ULID

if TYPE_CHECKING:
    from wake.adapters import EventStream, LifecycleEvent, SessionContext, ToolRegistry
    from wake.types import Event


class EchoAdapter:
    name = "echo"
    version = "0.1.0"
    compatibility = "wake-harness-adapter@^0.1"

    async def step(
        self,
        ctx: SessionContext,
        events: EventStream,
        tools: ToolRegistry,
    ) -> AsyncIterator[Event]:
        from wake.types import Event, TextBlock

        last_user = await events.latest(type="user.message")
        text = "<empty>"
        if last_user is not None:
            blocks = last_user.payload.get("content", [])
            text = " ".join(b.get("text", "") for b in blocks if b.get("type") == "text")

        yield Event(
            id=str(ULID()),
            session_id=ctx.session_id,
            seq=0,
            type="assistant.message",
            payload={
                "content": [TextBlock(text=f"echo: {text}").model_dump()],
                "stop_reason": "end_turn",
            },
            created_at=datetime.now(UTC),
        )

    async def on_lifecycle(self, ctx, event):
        return None


def create() -> EchoAdapter:
    return EchoAdapter()
```

```toml
# pyproject.toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "wake-adapter-echo"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["wake-ai>=0.0.1", "python-ulid>=3.0"]

[project.entry-points."wake.adapters"]
echo = "wake_adapter_echo.adapter:create"

[tool.hatch.build.targets.wheel]
packages = ["src/wake_adapter_echo"]
```

```bash
pip install -e .
python -c "from wake.adapters import AdapterRegistry; r=AdapterRegistry(); r.discover(); print(r.names())"
# ['echo', ...]
```

Replace the body of `step()` with a real LLM call, wire your framework
in, and you have a production adapter. The rest is conformance polish.

---

## 12. Where to go next

- Read [`SPEC-HARNESS-ADAPTER.md`](./SPEC-HARNESS-ADAPTER.md) for the
  open questions (statefulness, dynamic tools, mid-step cancellation
  signals) we still want feedback on.
- Read [`SPEC-EVENT-SCHEMA.md`](./SPEC-EVENT-SCHEMA.md) before designing
  any new event payload — emit canonical shapes, not framework-flavored
  ones.
- Open an RFC issue (`rfc` label) if your framework forces a Protocol
  change. See [`CONTRIBUTING.md`](../CONTRIBUTING.md).
- Look at the [`adapters/claude-sdk/`](../adapters/claude-sdk/)
  source for the production reference once Phase 2 merges; the stubs
  are useful skeletons but they don't show streaming, tool use, or
  cancellation.

Ship something. The ABI gets better with every adapter that lands.
