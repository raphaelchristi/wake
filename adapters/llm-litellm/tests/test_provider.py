"""Tests for ``LiteLLMProvider``.

All tests inject a fake ``completion_fn`` — no real network / LiteLLM
involvement.
"""

from __future__ import annotations

from typing import Any

import pytest

from wake_llm_litellm import LiteLLMProvider, LLMProvider, NormalizedMessage
from wake_llm_litellm.base import LLMProviderError

from ._fixtures import anthropic_response, openai_response


async def test_provider_is_llm_provider() -> None:
    p = LiteLLMProvider(completion_fn=lambda **kw: None)
    assert isinstance(p, LLMProvider)


async def test_create_message_basic_anthropic() -> None:
    captured: dict[str, Any] = {}

    async def fake_completion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return anthropic_response(text="Bonjour")

    p = LiteLLMProvider(completion_fn=fake_completion)
    msg = await p.create_message(
        model="anthropic/claude-opus-4-7",
        messages=[{"role": "user", "content": "Hi"}],
        max_tokens=512,
    )
    assert isinstance(msg, NormalizedMessage)
    assert msg.text == "Bonjour"
    assert msg.stop_reason == "end_turn"
    assert msg.usage["input_tokens"] == 120
    assert msg.usage["output_tokens"] == 64
    # Forwarded kwargs reach litellm verbatim.
    assert captured["model"] == "anthropic/claude-opus-4-7"
    assert captured["max_tokens"] == 512


async def test_create_message_with_system_prompt_prepended() -> None:
    captured: dict[str, Any] = {}

    async def fake_completion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return anthropic_response(text="ok")

    p = LiteLLMProvider(completion_fn=fake_completion)
    await p.create_message(
        model="anthropic/claude-opus-4-7",
        messages=[{"role": "user", "content": "Hi"}],
        system="You are a helpful assistant.",
    )
    msgs = captured["messages"]
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == "You are a helpful assistant."
    assert msgs[1]["role"] == "user"


async def test_existing_system_message_not_duplicated() -> None:
    captured: dict[str, Any] = {}

    async def fake_completion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return openai_response(text="ok")

    p = LiteLLMProvider(completion_fn=fake_completion, install_cost_tracking=False)
    await p.create_message(
        model="openai/gpt-4o",
        messages=[
            {"role": "system", "content": "Custom system"},
            {"role": "user", "content": "Hi"},
        ],
        system="ignored fallback",
    )
    msgs = captured["messages"]
    # First message is the user-supplied system, not the fallback.
    assert msgs[0]["content"] == "Custom system"
    # Exactly one system message.
    assert sum(1 for m in msgs if m["role"] == "system") == 1


async def test_create_message_with_tools_openai_renders_function_shape() -> None:
    captured: dict[str, Any] = {}

    async def fake_completion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return openai_response(text="ok")

    p = LiteLLMProvider(completion_fn=fake_completion, install_cost_tracking=False)
    await p.create_message(
        model="openai/gpt-4o",
        messages=[{"role": "user", "content": "x"}],
        tools=[
            {
                "name": "bash",
                "description": "run shell",
                "input_schema": {"type": "object", "properties": {"cmd": {"type": "string"}}},
            }
        ],
    )
    tools = captured["tools"]
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "bash"
    assert "parameters" in tools[0]["function"]


async def test_create_message_with_tools_anthropic_passes_through() -> None:
    captured: dict[str, Any] = {}

    async def fake_completion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return anthropic_response(text="ok")

    p = LiteLLMProvider(completion_fn=fake_completion, install_cost_tracking=False)
    tool = {
        "name": "bash",
        "description": "run shell",
        "input_schema": {"type": "object"},
    }
    await p.create_message(
        model="anthropic/claude-opus-4-7",
        messages=[{"role": "user", "content": "x"}],
        tools=[tool],
    )
    # Anthropic models receive the tool unmodified.
    assert captured["tools"] == [tool]


async def test_completion_fn_failure_wrapped_in_provider_error() -> None:
    async def explode(**kwargs: Any) -> Any:
        raise RuntimeError("network down")

    p = LiteLLMProvider(completion_fn=explode, install_cost_tracking=False)
    with pytest.raises(LLMProviderError, match="network down"):
        await p.create_message(
            model="openai/gpt-4o",
            messages=[{"role": "user", "content": "x"}],
        )


async def test_default_kwargs_forwarded() -> None:
    captured: dict[str, Any] = {}

    async def fake_completion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return openai_response(text="ok")

    p = LiteLLMProvider(
        completion_fn=fake_completion,
        install_cost_tracking=False,
        default_kwargs={"api_base": "http://localhost:11434"},
    )
    await p.create_message(
        model="ollama/qwen2.5",
        messages=[{"role": "user", "content": "x"}],
    )
    assert captured.get("api_base") == "http://localhost:11434"


async def test_create_factory_returns_litellm_provider() -> None:
    from wake_llm_litellm.provider import create

    p = create()
    assert isinstance(p, LiteLLMProvider)
