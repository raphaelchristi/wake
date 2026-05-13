"""tool_use — adapter invokes a registered tool and incorporates the result.

Setup:
    - Register a fake `echo` tool that returns its input as text
    - Inject `user.message` "use echo on 'hello'"

Expectations:
    - adapter emits a `tool_use` event with name='echo'
    - tools.execute was called at least once with that tool_use_id
    - adapter emits a `tool_result` event correlated by tool_use_id
    - adapter eventually emits an `assistant.message`

Why it matters: validates the tool-call protocol — the most common
divergence point between frameworks. Adapters MUST go through
``tools.execute()`` (not call functions directly) so this scenario
also verifies that contract via the registry's call log.
"""

from __future__ import annotations

from typing import Any

from wake.adapters import HarnessAdapter
from wake.types import TextBlock, ToolResult

from wake_test_conformance.harness import TestHarness
from wake_test_conformance.result import ScenarioResult
from wake_test_conformance.scenarios._helpers import run_with_timing

name = "tool_use"


async def run(adapter: HarnessAdapter) -> ScenarioResult:
    async def body() -> ScenarioResult:
        harness = TestHarness()

        async def echo_impl(input_data: dict[str, Any]) -> ToolResult:
            text = input_data.get("text") or input_data.get("input") or ""
            return ToolResult(
                content=[TextBlock(text=f"echo: {text}")],
                is_error=False,
            )

        harness.tools.add(
            "echo",
            echo_impl,
            description="returns its input as text",
            schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        )

        await harness.inject_user_message("use echo on 'hello'")

        emitted = await harness.run_step(adapter)

        tool_uses = [e for e in emitted if e.type == "tool_use"]
        tool_results = [e for e in emitted if e.type == "tool_result"]
        messages = [e for e in emitted if e.type == "assistant.message"]

        if not tool_uses:
            return ScenarioResult(
                name=name,
                passed=False,
                message=(
                    "adapter did not emit a tool_use event despite a tool "
                    "being registered and the user asking for it"
                ),
            )

        # The adapter must call the registered tool via tools.execute().
        if not harness.tools.calls:
            return ScenarioResult(
                name=name,
                passed=False,
                message=(
                    "adapter emitted tool_use but never called tools.execute(); "
                    "adapters must route tool invocations through the registry"
                ),
            )

        # Pair-up tool_use → tool_result by tool_use_id.
        use_ids = {e.payload.get("tool_use_id") for e in tool_uses}
        result_ids = {e.payload.get("tool_use_id") for e in tool_results}
        missing = use_ids - result_ids
        if missing:
            return ScenarioResult(
                name=name,
                passed=False,
                message=(
                    f"tool_use events without matching tool_result: {sorted(missing)}"
                ),
            )

        if not messages:
            return ScenarioResult(
                name=name,
                passed=False,
                message="adapter never emitted a final assistant.message after tool execution",
            )

        return ScenarioResult(
            name=name,
            passed=True,
            message=(
                f"observed {len(tool_uses)} tool_use, "
                f"{len(tool_results)} tool_result, "
                f"{len(messages)} assistant.message"
            ),
        )

    return await run_with_timing(name, body)
