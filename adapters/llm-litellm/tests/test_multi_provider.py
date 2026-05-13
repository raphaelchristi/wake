"""End-to-end multi-provider test: same agent loop against Anthropic /
OpenAI / Ollama, asserting that the canonical Wake event flow is
identical regardless of which provider answered.

These tests inject a fake ``completion_fn`` so no real LLM is called.
"""

from __future__ import annotations

from typing import Any

import pytest

from wake_llm_litellm import LiteLLMProvider, to_wake_events
from wake_llm_litellm.cost_tracking import CostTracker

from ._fixtures import anthropic_response, ollama_response, openai_response


PROVIDER_CASES = [
    pytest.param(
        "anthropic/claude-opus-4-7",
        anthropic_response,
        id="anthropic",
    ),
    pytest.param(
        "openai/gpt-4o",
        openai_response,
        id="openai",
    ),
    pytest.param(
        "ollama/qwen2.5-coder",
        ollama_response,
        id="ollama",
    ),
]


@pytest.mark.parametrize(("model", "make_response"), PROVIDER_CASES)
async def test_text_response_normalises_identically(
    model: str, make_response: Any
) -> None:
    async def fake(**kwargs: Any) -> Any:
        return make_response(text="hello world")

    provider = LiteLLMProvider(completion_fn=fake, install_cost_tracking=False)
    msg = await provider.create_message(
        model=model,
        messages=[{"role": "user", "content": "hi"}],
    )
    assert msg.text == "hello world"
    assert msg.stop_reason == "end_turn"
    assert msg.tool_calls == []


@pytest.mark.parametrize(("model", "make_response"), PROVIDER_CASES)
async def test_tool_use_normalises_identically(
    model: str, make_response: Any
) -> None:
    async def fake(**kwargs: Any) -> Any:
        return make_response(
            text="",
            tool_calls=[{"id": "tu_1", "name": "bash", "input": {"cmd": "ls"}}],
        )

    provider = LiteLLMProvider(completion_fn=fake, install_cost_tracking=False)
    msg = await provider.create_message(
        model=model,
        messages=[{"role": "user", "content": "list files"}],
        tools=[
            {
                "name": "bash",
                "description": "run shell",
                "input_schema": {"type": "object", "properties": {"cmd": {"type": "string"}}},
            }
        ],
    )
    assert msg.stop_reason == "tool_use"
    assert len(msg.tool_calls) == 1
    tc = msg.tool_calls[0]
    assert tc.name == "bash"
    assert tc.input == {"cmd": "ls"}

    # Wake event shape must be identical across providers.
    events = to_wake_events(msg, session_id="sess_x")
    assert [e.type for e in events] == ["assistant.message", "tool_use"]
    tool_use_event = events[1]
    assert tool_use_event.payload["name"] == "bash"
    assert tool_use_event.payload["input"] == {"cmd": "ls"}


async def test_cost_tracker_aggregates_across_providers() -> None:
    """Sum costs from a 3-provider session into the same tracker."""

    tracker = CostTracker()

    # Simulate three completions with provider-reported costs.
    responses = [
        anthropic_response(text="a", cost_usd=0.01),
        openai_response(text="b", cost_usd=0.005),
        ollama_response(text="c"),  # cost_usd=None
    ]

    for resp in responses:
        from datetime import datetime

        from wake_llm_litellm.normalize import normalize_response

        # Pretend the LiteLLM callback runs after each completion. We
        # bypass the litellm import entirely by recording directly.
        msg = normalize_response(resp, model="x")
        if msg.cost_usd is not None:
            from wake_llm_litellm.cost_tracking import CostMetadata

            tracker.record(
                CostMetadata(
                    model="x",
                    cost_usd=msg.cost_usd,
                    input_tokens=msg.usage.get("input_tokens", 0),
                    output_tokens=msg.usage.get("output_tokens", 0),
                    timestamp=datetime.utcnow(),
                    session_id="sess_e2e",
                )
            )

    assert tracker.session_total_usd("sess_e2e") == pytest.approx(0.015)
    # Ollama recorded nothing (local).
    assert len(tracker.all()) == 2


async def test_provider_specific_tool_rendering() -> None:
    """Anthropic models receive native schema; others get OpenAI shape."""

    captured: list[dict[str, Any]] = []

    async def fake(**kwargs: Any) -> Any:
        captured.append(kwargs)
        return openai_response(text="ok")

    provider = LiteLLMProvider(completion_fn=fake, install_cost_tracking=False)
    tool = {
        "name": "bash",
        "description": "run shell",
        "input_schema": {"type": "object"},
    }

    await provider.create_message(
        model="anthropic/claude-opus-4-7",
        messages=[{"role": "user", "content": "x"}],
        tools=[tool],
    )
    await provider.create_message(
        model="openai/gpt-4o",
        messages=[{"role": "user", "content": "x"}],
        tools=[tool],
    )
    await provider.create_message(
        model="ollama/qwen2.5-coder",
        messages=[{"role": "user", "content": "x"}],
        tools=[tool],
    )

    anthropic_tools = captured[0]["tools"]
    openai_tools = captured[1]["tools"]
    ollama_tools = captured[2]["tools"]

    # Anthropic: passed through.
    assert anthropic_tools == [tool]
    # OpenAI / Ollama: wrapped in function shape.
    for ts in (openai_tools, ollama_tools):
        assert ts[0]["type"] == "function"
        assert ts[0]["function"]["name"] == "bash"
