"""Shared test fixtures: a deterministic fake LLM for CrewAI.

The tests never make real model calls. Every Agent uses :class:`FakeLLM`,
which iterates through a pre-baked list of responses. Each response is
the raw string CrewAI's parser would see from a real model — Thought /
Action / Action Input / Final Answer in ReAct format.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import pytest
from crewai.llms.base_llm import BaseLLM

if TYPE_CHECKING:
    from collections.abc import Iterator

# Disable CrewAI's external tracing in tests — keeps stdout clean and
# avoids any network attempts on cold caches.
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")


class FakeLLM(BaseLLM):
    """A scripted LLM that returns the next item from ``responses``.

    Use it like::

        llm = FakeLLM(model="fake", responses=[
            "Final Answer: ok",
        ])
        agent = Agent(role=..., goal=..., backstory=..., llm=llm)
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
        # Use object.__setattr__ to bypass pydantic's field validation for
        # incrementing the index — ``idx`` is declared as a model field but
        # we treat it as mutable per-call state.
        resp = self.responses[self.idx % len(self.responses)]
        object.__setattr__(self, "idx", self.idx + 1)
        return resp

    def supports_function_calling(self) -> bool:
        return False

    def supports_stop_words(self) -> bool:
        return False


@pytest.fixture
def fake_llm_factory() -> Iterator[type[FakeLLM]]:
    """Yield the FakeLLM class for tests that want to instantiate it."""
    yield FakeLLM
