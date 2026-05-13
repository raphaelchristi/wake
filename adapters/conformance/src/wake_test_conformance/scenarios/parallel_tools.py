"""parallel_tools — adapter handles multiple tool calls in one turn.

Setup:
    - Register two fake tools: `tool_a` and `tool_b`
    - Inject `user.message` "use both tool_a and tool_b"

Expectations:
    - adapter emits >=2 distinct `tool_use` events (one per tool, with
      distinct tool_use_ids)
    - each `tool_use` has a matching `tool_result` event with the same
      tool_use_id
    - tools.execute was called for both tools
    - adapter eventually emits an `assistant.message`

Why it matters: Claude (and other models) can request several tools in
one turn. Adapters that serialize accidentally or that drop a tool
break parallel-friendly workflows.
"""

from __future__ import annotations

from typing import Any

from wake.adapters import HarnessAdapter
from wake.types import TextBlock, ToolResult

from wake_test_conformance.harness import TestHarness
from wake_test_conformance.result import ScenarioResult
from wake_test_conformance.scenarios._helpers import run_with_timing

name = "parallel_tools"


async def _make_tool(label: str) -> Any:
    async def impl(input_data: dict[str, Any]) -> ToolResult:
        return ToolResult(
            content=[TextBlock(text=f"{label}: {input_data}")],
            is_error=False,
        )

    return impl


async def run(adapter: HarnessAdapter) -> ScenarioResult:
    async def body() -> ScenarioResult:
        harness = TestHarness()

        harness.tools.add("tool_a", await _make_tool("A"), description="tool A")
        harness.tools.add("tool_b", await _make_tool("B"), description="tool B")

        await harness.inject_user_message("use both tool_a and tool_b")

        emitted = await harness.run_step(adapter)

        tool_uses = [e for e in emitted if e.type == "tool_use"]
        tool_results = [e for e in emitted if e.type == "tool_result"]
        messages = [e for e in emitted if e.type == "assistant.message"]

        names_used = {e.payload.get("name") for e in tool_uses}
        if not {"tool_a", "tool_b"} <= names_used:
            return ScenarioResult(
                name=name,
                passed=False,
                message=(
                    f"adapter did not invoke both tools; observed tool names: "
                    f"{sorted(n for n in names_used if n)}"
                ),
            )

        ids = [e.payload.get("tool_use_id") for e in tool_uses]
        if len(set(ids)) != len(ids):
            return ScenarioResult(
                name=name,
                passed=False,
                message=f"duplicate tool_use_ids emitted: {ids}",
            )

        result_ids = {e.payload.get("tool_use_id") for e in tool_results}
        missing = set(ids) - result_ids
        if missing:
            return ScenarioResult(
                name=name,
                passed=False,
                message=f"tool_use events without matching tool_result: {sorted(missing)}",
            )

        execute_names = {c["name"] for c in harness.tools.calls}
        if not {"tool_a", "tool_b"} <= execute_names:
            return ScenarioResult(
                name=name,
                passed=False,
                message=(
                    "tools.execute() was not called for both tools "
                    f"(saw: {sorted(execute_names)})"
                ),
            )

        if not messages:
            return ScenarioResult(
                name=name,
                passed=False,
                message="adapter never emitted a final assistant.message",
            )

        return ScenarioResult(
            name=name,
            passed=True,
            message=(
                f"both tools invoked; {len(tool_uses)} tool_use, "
                f"{len(tool_results)} tool_result"
            ),
        )

    return await run_with_timing(name, body)
