"""Conformance scenarios.

Each module exports:

- ``name: str`` — canonical scenario name (matches module name)
- ``async def run(adapter: HarnessAdapter) -> ScenarioResult``

The runner imports them through ``SCENARIOS`` defined here so adding a
new scenario is a single-line change.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from wake_test_conformance.scenarios import (
    basic_step,
    cancellation,
    error_handling,
    idempotence,
    lifecycle,
    parallel_tools,
    pause_turn,
    resume,
    streaming,
    tool_use,
)

if TYPE_CHECKING:
    from wake.adapters import HarnessAdapter

    from wake_test_conformance.result import ScenarioResult

ScenarioRun = Callable[["HarnessAdapter"], "Awaitable[ScenarioResult]"]


SCENARIOS: list[tuple[str, ScenarioRun]] = [
    (basic_step.name, basic_step.run),
    (tool_use.name, tool_use.run),
    (streaming.name, streaming.run),
    (cancellation.name, cancellation.run),
    (resume.name, resume.run),
    (parallel_tools.name, parallel_tools.run),
    (error_handling.name, error_handling.run),
    (pause_turn.name, pause_turn.run),
    (lifecycle.name, lifecycle.run),
    (idempotence.name, idempotence.run),
]

__all__ = ["SCENARIOS", "ScenarioRun"]
