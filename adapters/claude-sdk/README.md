# wake-adapter-claude-sdk

Reference [Wake](https://github.com/raphaelchristi/wake) `HarnessAdapter` that drives
[Anthropic's Claude SDK](https://github.com/anthropics/anthropic-sdk-python).

This is the first conformant adapter and the production path for running Claude models on
the Wake runtime. It is also the model the other reference adapters (LangGraph, CrewAI,
Pydantic AI) follow.

## Install

```bash
pip install wake-adapter-claude-sdk
```

The Wake core (`wake-ai`) picks the adapter up via the
`wake.adapters` Python entry-point group, so no further wiring is required.

## Programmatic use

```python
from wake_adapter_claude_sdk import ClaudeSDKAdapter

adapter = ClaudeSDKAdapter()  # uses AsyncAnthropic() with default env
assert adapter.name == "claude-sdk"
assert adapter.version == "0.1.0"
assert adapter.compatibility == "wake-harness-adapter@^0.1"
```

A custom client (mock, alternate base URL, etc.) can be injected:

```python
from anthropic import AsyncAnthropic
adapter = ClaudeSDKAdapter(client=AsyncAnthropic(base_url="https://my-proxy"))
```

## Interface

The adapter implements `wake.adapters.HarnessAdapter`:

```python
async def step(ctx, events, tools) -> AsyncIterator[Event]: ...
async def on_lifecycle(ctx, event) -> None: ...
```

`step()` is an async generator that yields canonical Wake events
(`assistant.delta`, `assistant.message`, `tool_use`, `tool_result`, ...). The
Wake runtime is responsible for assigning `seq`/`id` and persisting them — adapters
emit `Event` objects with placeholder values.

## Conformance

Tested against the `wake-test-conformance` suite (see `adapters/conformance/`).

## License

Apache 2.0.
