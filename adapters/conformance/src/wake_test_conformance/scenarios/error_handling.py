"""error_handling — adapter incorporates failing tool results without crashing.

Setup:
    - Register `failing_tool` that always returns is_error=True
    - Inject `user.message` "use failing_tool"

Expectations:
    - adapter receives the error tool_result and DOES NOT crash
    - adapter emits a final `assistant.message` (retry, fallback, or
      graceful give-up are all acceptable)
    - no `error` event with `error_type='harness_panic'`

Why it matters: tools fail. Adapters that panic on the first
``is_error=True`` are useless. The Wake protocol expects adapters to
incorporate failures into their reasoning loop.
"""

from __future__ import annotations

from typing import Any

from wake.adapters import HarnessAdapter
from wake.types import TextBlock, ToolResult

from wake_test_conformance.harness import TestHarness
from wake_test_conformance.result import ScenarioResult
from wake_test_conformance.scenarios._helpers import run_with_timing

name = "error_handling"


async def run(adapter: HarnessAdapter) -> ScenarioResult:
    async def body() -> ScenarioResult:
        harness = TestHarness()

        async def failing(_: dict[str, Any]) -> ToolResult:
            return ToolResult(
                content=[TextBlock(text="simulated failure")],
                is_error=True,
                error_code="unknown",
            )

        harness.tools.add(
            "failing_tool",
            failing,
            description="always returns is_error=true",
        )

        await harness.inject_user_message("use failing_tool")

        emitted = await harness.run_step(adapter)

        panics = [
            e
            for e in emitted
            if e.type == "error"
            and (e.payload or {}).get("error_type") == "harness_panic"
        ]
        if panics:
            return ScenarioResult(
                name=name,
                passed=False,
                message=(
                    "adapter emitted error(harness_panic) when encountering an "
                    "is_error tool_result — should incorporate the error and continue"
                ),
            )

        messages = [e for e in emitted if e.type == "assistant.message"]
        if not messages:
            return ScenarioResult(
                name=name,
                passed=False,
                message=(
                    "adapter did not emit any assistant.message after a failing "
                    "tool result; must produce a final response (retry, fallback, or give-up)"
                ),
            )

        tool_results = [e for e in emitted if e.type == "tool_result"]
        err_results = [r for r in tool_results if (r.payload or {}).get("is_error")]
        if not err_results:
            # Adapter never observed the failing tool. Either it skipped the
            # tool entirely (acceptable behavior — failure-free path) or it
            # never tried.
            return ScenarioResult(
                name=name,
                passed=True,
                message="adapter did not invoke the failing tool; finished without errors",
                warnings=[
                    "failing_tool was registered but never invoked; "
                    "is_error path not exercised"
                ],
            )

        return ScenarioResult(
            name=name,
            passed=True,
            message=(
                f"adapter handled {len(err_results)} is_error tool_result(s) "
                f"and produced a final assistant.message"
            ),
        )

    return await run_with_timing(name, body)
