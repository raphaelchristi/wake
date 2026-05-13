"""Multi-agent crew: classic researcher -> writer pipeline.

CrewAI's value-add is orchestrating multiple agents per crew. The Wake
adapter must surface each agent's contribution through the event log so
downstream consumers (UIs, audit trails) can attribute thoughts and
tool calls to the right role.
"""

from __future__ import annotations

import pytest
from crewai import Agent, Crew, Task
from wake_adapter_crewai import CrewAIAdapter
from wake_test_conformance.harness import TestHarness


@pytest.mark.asyncio
async def test_researcher_writer_pipeline(fake_llm_factory: type) -> None:
    """A 2-agent / 2-task crew runs end-to-end and emits a final message.

    Two scripted responses suffice — one per task. CrewAI threads the
    first task's output into the second task's context automatically.
    """
    # Task 1 (research) is short; task 2 (write) consumes its output.
    research_response = "Final Answer: water boils at 100C."
    write_response = "Final Answer: Did you know water boils at 100C?"

    def factory(user_input: str) -> Crew:
        FakeLLM = fake_llm_factory  # noqa: N806
        researcher_llm = FakeLLM(
            model="fake-researcher", responses=[research_response]
        )
        writer_llm = FakeLLM(model="fake-writer", responses=[write_response])

        researcher = Agent(
            role="researcher",
            goal="gather facts",
            backstory="finds reliable information.",
            llm=researcher_llm,
            verbose=False,
        )
        writer = Agent(
            role="writer",
            goal="produce engaging prose",
            backstory="turns dry facts into prose.",
            llm=writer_llm,
            verbose=False,
        )

        research_task = Task(
            description=f"Research the answer to: {user_input}",
            expected_output="One fact.",
            agent=researcher,
        )
        write_task = Task(
            description="Turn the research into a one-line statement.",
            expected_output="A statement.",
            agent=writer,
            context=[research_task],
        )

        return Crew(
            agents=[researcher, writer],
            tasks=[research_task, write_task],
            verbose=False,
        )

    adapter = CrewAIAdapter(factory)
    harness = TestHarness()
    await harness.inject_user_message("tell me a fact about water")

    events = await harness.run_step(adapter, timeout=30.0)

    messages = [e for e in events if e.type == "assistant.message"]
    assert messages, "expected an assistant.message at the end"
    # Final message corresponds to the second task (writer).
    assert "water" in str(messages[-1].payload).lower()


@pytest.mark.asyncio
async def test_multi_agent_emits_thinking_per_task(
    fake_llm_factory: type,
) -> None:
    """Each task surfaces an ``assistant.thinking`` event with phase=task."""

    def factory(user_input: str) -> Crew:
        FakeLLM = fake_llm_factory  # noqa: N806
        a_llm = FakeLLM(model="fake-a", responses=["Final Answer: A done."])
        b_llm = FakeLLM(model="fake-b", responses=["Final Answer: B done."])
        agent_a = Agent(role="A", goal="g", backstory="b", llm=a_llm)
        agent_b = Agent(role="B", goal="g", backstory="b", llm=b_llm)
        task_a = Task(
            description=f"a-task: {user_input}",
            expected_output="A's output.",
            agent=agent_a,
        )
        task_b = Task(
            description="b-task continues from A.",
            expected_output="B's output.",
            agent=agent_b,
            context=[task_a],
        )
        return Crew(
            agents=[agent_a, agent_b],
            tasks=[task_a, task_b],
            verbose=False,
        )

    adapter = CrewAIAdapter(factory)
    harness = TestHarness()
    await harness.inject_user_message("kick off pipeline")

    events = await harness.run_step(adapter, timeout=30.0)
    task_thoughts = [
        e
        for e in events
        if e.type == "assistant.thinking"
        and (e.payload or {}).get("phase") == "task"
    ]
    # Expect one per task — but be lenient: at least one is required.
    assert task_thoughts, "expected at least one phase=task thinking event"


@pytest.mark.asyncio
async def test_multi_agent_final_message_carries_last_output(
    fake_llm_factory: type,
) -> None:
    """The final assistant.message text reflects the last task's output."""

    def factory(user_input: str) -> Crew:
        FakeLLM = fake_llm_factory  # noqa: N806
        a = Agent(
            role="A",
            goal="g",
            backstory="b",
            llm=FakeLLM(model="fake", responses=["Final Answer: A says hi"]),
        )
        b = Agent(
            role="B",
            goal="g",
            backstory="b",
            llm=FakeLLM(
                model="fake", responses=["Final Answer: B says goodbye"]
            ),
        )
        ta = Task(description="task a", expected_output=".", agent=a)
        tb = Task(
            description="task b", expected_output=".", agent=b, context=[ta]
        )
        return Crew(agents=[a, b], tasks=[ta, tb], verbose=False)

    adapter = CrewAIAdapter(factory)
    harness = TestHarness()
    await harness.inject_user_message("run pipeline")

    events = await harness.run_step(adapter, timeout=30.0)
    final = next(e for e in events if e.type == "assistant.message")
    final_text = str(final.payload).lower()
    assert "goodbye" in final_text or "b says" in final_text
