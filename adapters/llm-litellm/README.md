# wake-llm-litellm

Wake `LLMProvider` backed by [LiteLLM](https://github.com/BerriAI/litellm).
Phase 4 component.

## What it does

One API surface against 100+ model providers (Anthropic, OpenAI,
Ollama, Bedrock, …). The adapter normalises provider-specific quirks
into canonical Wake `tool_use` / `tool_result` events so the runtime
stays provider-agnostic.

## Install

```bash
pip install -e adapters/llm-litellm
```

Registers `litellm` under the `wake.llm_providers` entry-point group.

## Quick start

```python
from wake_llm_litellm import LiteLLMProvider

provider = LiteLLMProvider()

msg = await provider.create_message(
    model="anthropic/claude-opus-4-7",
    messages=[{"role": "user", "content": "Hi"}],
    tools=[],
)
print(msg.text, msg.stop_reason, msg.usage)
```

## Tool-use semantics across providers

LiteLLM returns an OpenAI-shaped envelope (`choices[0].message`) but
each provider preserves its native tool-call format inside it.

| Provider  | Where tool calls live | Argument format |
|-----------|-----------------------|------------------|
| Anthropic | `message.content` (list of `text` / `tool_use` blocks) | parsed dict |
| OpenAI    | `message.tool_calls[]` with `function.arguments` (string) | JSON string |
| Ollama    | `message.tool_calls[]` (matches OpenAI) | sometimes dict |

`normalize_response()` handles all three. The result is a
`NormalizedMessage` you can convert to Wake events with
`to_wake_events()`.

## Cost tracking

`install_litellm_callback()` registers LiteLLM's `success_callback` so
every completion's cost lands in the in-process `CostTracker`. The
adapter calls this automatically on first instantiation.

```python
from wake_llm_litellm import get_tracker

await provider.create_message(model="openai/gpt-4o", messages=[...])
print(get_tracker().total_usd())  # USD
```

Per-session totals: pass `metadata={"session_id": ...}` to
`create_message(**kwargs)` — the callback picks it up.

## Degradation by provider

Be aware:

| Capability               | Anthropic | OpenAI | Ollama |
|--------------------------|-----------|--------|--------|
| Streaming                | yes       | yes    | yes    |
| Prompt caching           | yes       | no     | no     |
| Extended thinking        | yes       | no     | no     |
| Tool use                 | yes       | yes    | partial (model-dependent) |
| Function/tool parallelism | yes      | yes    | no     |
| Cost reporting           | yes       | yes    | no (local) |

The adapter does **not** paper over these — it surfaces empty `usage`,
`cost_usd=None`, etc., where the provider lacks the data.

## Tests

```bash
pytest adapters/llm-litellm/tests/ -q
```

All tests run against an injected fake `completion_fn` — no real LLM
calls are ever made.
