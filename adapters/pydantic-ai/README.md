# wake-adapter-pydantic-ai

Wake `HarnessAdapter` for the [Pydantic AI](https://ai.pydantic.dev/) framework.

Pydantic AI is the most strictly-typed agent framework in the Wake adapter family
— typed outputs via `output_type=...`, typed tools via JSON-schema-derived-from-
pydantic, structured streaming with `Agent.run_stream(...)`. Each Wake event maps
1:1 to a `pydantic_ai.messages.ModelMessage` part and vice versa.

## Install

```bash
pip install -e adapters/pydantic-ai
```

This pulls in `pydantic-ai>=1.0`, `wake-ai`, `pydantic>=2.10`, and `structlog`.

## Use

```python
from pydantic_ai import Agent
from wake_adapter_pydantic_ai import PydanticAIAdapter

agent = Agent(
    "anthropic:claude-opus-4-7",
    system_prompt="You are a research assistant.",
)

adapter = PydanticAIAdapter(agent)
# pass `adapter` to a Wake session via the dispatcher / AdapterRegistry
```

Typed agents work too:

```python
from pydantic import BaseModel

class Result(BaseModel):
    answer: str
    confidence: float

agent = Agent("anthropic:claude-opus-4-7", output_type=Result)
adapter = PydanticAIAdapter(agent)
```

## Event mapping

| Wake event | Pydantic AI part |
|---|---|
| `user.message` | `ModelRequest(parts=[UserPromptPart(...)])` |
| `assistant.message` | `ModelResponse(parts=[TextPart(...)])` (final, aggregated) |
| `assistant.delta` | yielded from `result.stream_text(delta=True)` |
| `assistant.thinking` | `ThinkingPart` (if present) |
| `tool_use` | `ToolCallPart` |
| `tool_result` | `ToolReturnPart` (paired by `tool_call_id`) |

Wake `tools` are attached to each run as a fresh `FunctionToolset` (passed via
the `toolsets=` keyword on `Agent.run_stream`). The adapter never mutates the
user-supplied `Agent` — it stays stateless across sessions and steps.

## Conformance

`tests/test_conformance.py` runs the `wake-test-conformance` suite. Expected
score: **≥8/10** on a clean run with `TestModel` / `FunctionModel` driving the
adapter (Pydantic AI's strict typing makes the mapping the cleanest of the
three Phase 3 adapters).

Scenarios marked as optional in the Wake spec (`pause_turn`) are not natively
expressed by Pydantic AI; they pass with a warning rather than a hard failure
— see the conformance harness for details.

## Layout

```
adapters/pydantic-ai/
├── pyproject.toml
├── README.md
├── src/wake_adapter_pydantic_ai/
│   ├── __init__.py
│   ├── adapter.py        # PydanticAIAdapter + event ↔ message_history mapping
│   └── tool_bridge.py    # Wake ToolRegistry → Pydantic AI FunctionToolset
├── tests/
│   ├── test_adapter.py
│   ├── test_tool_bridge.py
│   ├── test_typed_agent.py
│   ├── test_streaming.py
│   └── test_conformance.py
└── examples/
    └── typed_agent.py
```
