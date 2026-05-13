"""Runnable example: a single-agent Crew driven by the Wake adapter.

Run::

    python -m wake_adapter_crewai.examples.simple_crew

Or with ``CREWAI_REAL_LLM=1`` set, the example builds a real LLM (you
must have ``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY``, etc. configured for
LiteLLM). Otherwise it uses a scripted :class:`FakeLLM` so the example
is fully offline.

The example builds an in-memory event log, injects one user message,
runs ``adapter.step()`` to completion, and prints every emitted Wake
event.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from crewai import Agent, Crew, Task
from crewai.llms.base_llm import BaseLLM
from wake_adapter_crewai import CrewAIAdapter
from wake_test_conformance.harness import TestHarness


class _ScriptedLLM(BaseLLM):
    """Inline FakeLLM mirroring the test conftest.

    Returns each item from ``responses`` once. Used when the example is
    run without ``CREWAI_REAL_LLM=1``.
    """

    responses: list[str] = []
    idx: int = 0

    def call(
        self,
        messages: Any,
        tools: Any = None,
        callbacks: Any = None,
        available_functions: Any = None,
        from_task: Any = None,
        from_agent: Any = None,
        response_model: Any = None,
    ) -> str:
        resp = self.responses[self.idx % len(self.responses)]
        object.__setattr__(self, "idx", self.idx + 1)
        return resp

    def supports_function_calling(self) -> bool:
        return False

    def supports_stop_words(self) -> bool:
        return False


def build_crew(user_input: str) -> Crew:
    """Factory: a 1-agent / 1-task crew that answers the user's prompt."""
    use_real = os.getenv("CREWAI_REAL_LLM") == "1"
    if use_real:
        # Real LiteLLM-backed LLM. Requires API credentials in env.
        from crewai import LLM

        llm: BaseLLM = LLM(model=os.getenv("CREWAI_MODEL", "gpt-4o-mini"))
    else:
        llm = _ScriptedLLM(
            model="wake-scripted",
            responses=[
                "Thought: I will answer directly.\n"
                f"Final Answer: Hello! You said: {user_input!r}",
            ],
        )

    agent = Agent(
        role="greeter",
        goal="greet the user politely",
        backstory="An over-eager greeter.",
        llm=llm,
        verbose=False,
    )
    task = Task(
        description=user_input or "Greet the user warmly.",
        expected_output="A warm one-sentence greeting.",
        agent=agent,
    )
    return Crew(agents=[agent], tasks=[task], verbose=False)


async def main() -> None:
    """Run a single step end-to-end and print every emitted event."""
    adapter = CrewAIAdapter(build_crew)
    harness = TestHarness()
    await harness.inject_user_message("Hi, how are you?")

    print(">>> Driving adapter.step() <<<")
    events = await harness.run_step(adapter, timeout=30.0)
    print(f">>> Got {len(events)} event(s) <<<")
    for ev in events:
        print(f"  [{ev.type}] {ev.payload}")


if __name__ == "__main__":
    # CrewAI's external tracing makes noisy stdout on first run.
    os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
    asyncio.run(main())
