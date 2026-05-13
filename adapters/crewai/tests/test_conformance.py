"""Run the full wake-test-conformance suite against the CrewAI adapter.

The factory inspects the user prompt and produces a Crew with scripted
LLM responses matched to the scenario. Each conformance scenario uses a
fixed canonical prompt:

- ``"say ok"``                   -> basic_step
- ``"use echo on 'hello'"``      -> tool_use
- ``"use echo on 'idempotence'"``-> idempotence
- ``"stream a long response"``   -> streaming + cancellation
- ``"PLEASE_PAUSE: ..."``        -> pause_turn (optional, lenient)
- ``"use both tool_a and tool_b"``-> parallel_tools
- ``"use failing_tool"``         -> error_handling

The adapter passes 10/10 scenarios as of Phase 3.
"""

from __future__ import annotations

import pytest
from crewai import Agent, Crew, Task
from wake_adapter_crewai import CrewAIAdapter
from wake_test_conformance import run_conformance


def _responses_for(prompt: str) -> list[str]:
    """Return the scripted FakeLLM responses for a given conformance prompt."""
    msg = (prompt or "").lower()

    if "tool_a" in msg and "tool_b" in msg:
        return [
            'Thought: call tool_a.\nAction: tool_a\nAction Input: {}',
            'Thought: call tool_b.\nAction: tool_b\nAction Input: {}',
            "Thought: both done.\nFinal Answer: ok",
        ]

    if "failing_tool" in msg or "failing" in msg:
        return [
            'Thought: try failing_tool.\nAction: failing_tool\nAction Input: {}',
            "Thought: it failed; giving up.\nFinal Answer: ok despite failure.",
        ]

    if "echo" in msg:
        return [
            'Thought: echo it.\nAction: echo\nAction Input: {"text": "hello"}',
            "Thought: done.\nFinal Answer: ok",
        ]

    # Fallback: any other prompt (basic_step, streaming, resume,
    # cancellation, pause_turn, lifecycle) — short final answer.
    return ["Final Answer: ok"]


@pytest.fixture
def crew_factory(fake_llm_factory: type) -> object:
    """Build a Crew factory whose script depends on the user prompt."""
    FakeLLM = fake_llm_factory  # noqa: N806

    def factory(user_input: str) -> Crew:
        llm = FakeLLM(model="fake", responses=_responses_for(user_input))
        agent = Agent(
            role="conformance-tester",
            goal="execute conformance scenarios",
            backstory="A test agent.",
            llm=llm,
            verbose=False,
        )
        task = Task(
            description=user_input or "say ok",
            expected_output="The expected output.",
            agent=agent,
        )
        return Crew(agents=[agent], tasks=[task], verbose=False)

    return factory


@pytest.mark.asyncio
async def test_conformance_suite_passes_seven_of_ten(
    crew_factory: object,
) -> None:
    """The adapter must pass at least 7/10 scenarios per Phase 3 contract.

    In practice this implementation passes 10/10. We assert 7 as the
    floor so future CrewAI changes don't immediately break CI; the
    summary is included in the failure message for diagnostics.
    """
    adapter = CrewAIAdapter(crew_factory)  # type: ignore[arg-type]
    report = await run_conformance(adapter)
    assert report.passed_count >= 7, report.summary()


@pytest.mark.asyncio
async def test_conformance_full_pass(crew_factory: object) -> None:
    """Aspirational: 10/10. If this fails we still pass the floor, but
    we want a fast signal when something regresses below full pass."""
    adapter = CrewAIAdapter(crew_factory)  # type: ignore[arg-type]
    report = await run_conformance(adapter)
    if not report.passed:
        # Make the failure message actionable.
        pytest.fail(
            "Conformance regressed from 10/10:\n" + report.summary()
        )
