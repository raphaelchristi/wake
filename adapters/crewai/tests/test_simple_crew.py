"""Integration tests: single-agent, single-task Crew driven by the adapter.

We use the :class:`TestHarness` from ``wake_test_conformance`` to set up
a session in memory, inject a user message, then drive
``adapter.step()`` to completion. The Agent's LLM is a :class:`FakeLLM`
with scripted responses — no network.
"""

from __future__ import annotations

from typing import Any

import pytest
from crewai import Agent, Crew, Task
from wake_adapter_crewai import CrewAIAdapter
from wake_test_conformance.harness import TestHarness

from wake.types import TextBlock, ToolResult


def _build_simple_factory(fake_llm_cls: type, responses: list[str]) -> Any:
    def factory(user_input: str) -> Crew:
        llm = fake_llm_cls(model="fake", responses=responses)
        agent = Agent(
            role="tester",
            goal="complete the task",
            backstory="A test agent.",
            llm=llm,
            verbose=False,
        )
        task = Task(
            description=user_input or "say ok",
            expected_output="A short answer.",
            agent=agent,
        )
        return Crew(agents=[agent], tasks=[task], verbose=False)

    return factory


@pytest.mark.asyncio
async def test_basic_run_emits_assistant_message(
    fake_llm_factory: type,
) -> None:
    factory = _build_simple_factory(fake_llm_factory, ["Final Answer: ok"])
    adapter = CrewAIAdapter(factory)
    harness = TestHarness()
    await harness.inject_user_message("say ok")

    events = await harness.run_step(adapter, timeout=15.0)

    types = [e.type for e in events]
    assert "assistant.message" in types
    final = next(e for e in events if e.type == "assistant.message")
    assert "ok" in str(final.payload).lower()


@pytest.mark.asyncio
async def test_run_with_tool_emits_tool_use_and_result(
    fake_llm_factory: type,
) -> None:
    factory = _build_simple_factory(
        fake_llm_factory,
        [
            'Thought: use echo.\nAction: echo\nAction Input: {"text": "hi"}',
            "Thought: ok.\nFinal Answer: Done.",
        ],
    )
    adapter = CrewAIAdapter(factory)
    harness = TestHarness()

    async def echo_impl(input_data: dict[str, Any]) -> ToolResult:
        text = input_data.get("text", "")
        return ToolResult(
            content=[TextBlock(text=f"echo: {text}")], is_error=False
        )

    harness.tools.add(
        "echo",
        echo_impl,
        description="echo back input text",
        schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )

    await harness.inject_user_message("use the echo tool on 'hi'")
    events = await harness.run_step(adapter, timeout=15.0)

    use_events = [e for e in events if e.type == "tool_use"]
    result_events = [e for e in events if e.type == "tool_result"]
    msg_events = [e for e in events if e.type == "assistant.message"]

    assert use_events, "adapter must emit tool_use"
    assert result_events, "adapter must emit tool_result"
    assert msg_events, "adapter must emit assistant.message"

    # tool_use_id correlates use <-> result
    use_ids = {e.payload["tool_use_id"] for e in use_events}
    result_ids = {e.payload["tool_use_id"] for e in result_events}
    assert use_ids == result_ids

    # tools.execute was invoked
    assert harness.tools.calls
    assert harness.tools.calls[0]["name"] == "echo"
    assert harness.tools.calls[0]["input"] == {"text": "hi"}


@pytest.mark.asyncio
async def test_no_user_message_is_noop(fake_llm_factory: type) -> None:
    """If the log has no ``user.message``, step() yields nothing."""
    factory = _build_simple_factory(fake_llm_factory, ["Final Answer: ok"])
    adapter = CrewAIAdapter(factory)
    harness = TestHarness()

    events = await harness.run_step(adapter, timeout=5.0)
    assert events == []


@pytest.mark.asyncio
async def test_resume_after_complete_is_noop(fake_llm_factory: type) -> None:
    """Once an assistant.message follows the user message, step() exits early."""
    factory = _build_simple_factory(fake_llm_factory, ["Final Answer: ok"])
    adapter = CrewAIAdapter(factory)
    harness = TestHarness()
    await harness.inject_user_message("say ok")

    first = await harness.run_step(adapter, timeout=15.0)
    assert any(e.type == "assistant.message" for e in first)

    second = await harness.run_step(adapter, timeout=5.0)
    assert second == []


@pytest.mark.asyncio
async def test_thinking_event_emitted_for_agent_thoughts(
    fake_llm_factory: type,
) -> None:
    """Agent thoughts in the LLM output surface as assistant.thinking."""
    factory = _build_simple_factory(
        fake_llm_factory,
        ["Thought: I am thinking deeply.\nFinal Answer: 42"],
    )
    adapter = CrewAIAdapter(factory)
    harness = TestHarness()
    await harness.inject_user_message("what is the meaning of life?")

    events = await harness.run_step(adapter, timeout=15.0)
    thinking = [e for e in events if e.type == "assistant.thinking"]
    assert thinking, "expected at least one assistant.thinking event"
