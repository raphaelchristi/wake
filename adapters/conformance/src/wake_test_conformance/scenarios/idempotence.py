"""idempotence — step() called twice with the same input does not duplicate.

Setup:
    - Register an `echo` tool
    - Inject `user.message` "use echo"
    - Run step() once, capture emitted events.
    - Run step() a second time on the SAME event log.

Expectations:
    - No two events across the two runs share the same `tool_use_id`.
    - Total tool_use_ids emitted by the adapter form a set with size
      equal to its list cardinality (no in-run duplicates either).
    - No exception propagates out.

Why it matters: the runtime persists each emission. If the adapter
re-emits the same `tool_use_id`, idempotence on the runtime side breaks
audit/dedup invariants. Adapters MUST treat events already in the log
as authoritative and not reproduce them with stale ids.
"""

from __future__ import annotations

from typing import Any

from wake.adapters import HarnessAdapter
from wake.types import TextBlock, ToolResult

from wake_test_conformance.harness import TestHarness
from wake_test_conformance.result import ScenarioResult
from wake_test_conformance.scenarios._helpers import run_with_timing

name = "idempotence"


async def run(adapter: HarnessAdapter) -> ScenarioResult:
    async def body() -> ScenarioResult:
        harness = TestHarness()

        async def echo(input_data: dict[str, Any]) -> ToolResult:
            return ToolResult(
                content=[TextBlock(text=str(input_data))],
                is_error=False,
            )

        harness.tools.add("echo", echo, description="echo input")
        await harness.inject_user_message("use echo on 'idempotence'")

        first = await harness.run_step(adapter)
        first_ids = [
            e.payload.get("tool_use_id")
            for e in first
            if e.type == "tool_use"
        ]

        if len(first_ids) != len(set(first_ids)):
            return ScenarioResult(
                name=name,
                passed=False,
                message=(
                    f"adapter emitted duplicate tool_use_ids in a single step: "
                    f"{first_ids}"
                ),
            )

        second = await harness.run_step(adapter)
        second_ids = [
            e.payload.get("tool_use_id")
            for e in second
            if e.type == "tool_use"
        ]

        if len(second_ids) != len(set(second_ids)):
            return ScenarioResult(
                name=name,
                passed=False,
                message=(
                    f"adapter emitted duplicate tool_use_ids in second step: "
                    f"{second_ids}"
                ),
            )

        cross_dups = set(first_ids) & set(second_ids)
        if cross_dups:
            return ScenarioResult(
                name=name,
                passed=False,
                message=(
                    f"adapter re-used tool_use_ids across step() calls: "
                    f"{sorted(cross_dups)}"
                ),
            )

        return ScenarioResult(
            name=name,
            passed=True,
            message=(
                f"first_step tool_use_ids={len(first_ids)}, "
                f"second_step tool_use_ids={len(second_ids)}, "
                f"no duplicates"
            ),
        )

    return await run_with_timing(name, body)
