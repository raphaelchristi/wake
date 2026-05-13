"""resume — calling step() a second time on the same session is sane.

Setup:
    - Inject `user.message` "say ok"
    - Run step() to completion once (events are persisted into the log)
    - Run step() a second time on the same log

Expectations:
    - Second invocation either:
       a) emits zero events and terminates (nothing more to do), OR
       b) emits new events that DO NOT duplicate the first batch
    - In particular, no duplicate `tool_use_id` and no duplicate
      assistant.message identical to the previous final message.
    - No exception bubbles out.

Why it matters: Wake re-invokes adapters after crashes/resumes. Adapters
that blindly re-emit prior events corrupt the log; adapters that crash
on a non-empty log can't resume after interruption.
"""

from __future__ import annotations

from wake.adapters import HarnessAdapter

from wake_test_conformance.harness import TestHarness
from wake_test_conformance.result import ScenarioResult
from wake_test_conformance.scenarios._helpers import run_with_timing, text_from

name = "resume"


async def run(adapter: HarnessAdapter) -> ScenarioResult:
    async def body() -> ScenarioResult:
        harness = TestHarness()
        await harness.inject_user_message("say ok")

        first = await harness.run_step(adapter)
        if not first:
            return ScenarioResult(
                name=name,
                passed=False,
                message="adapter emitted nothing on first step()",
            )

        # Capture identifying info from first run.
        first_messages = [e for e in first if e.type == "assistant.message"]
        first_tool_use_ids = {
            e.payload.get("tool_use_id")
            for e in first
            if e.type == "tool_use"
        }
        first_text = text_from(first_messages[-1]) if first_messages else ""

        # Second invocation: events from first run are now in the log.
        second = await harness.run_step(adapter)

        # Zero new events on the second pass is the cleanest outcome.
        if not second:
            return ScenarioResult(
                name=name,
                passed=True,
                message=(
                    f"adapter idle on resume after {len(first)} first-step events"
                ),
            )

        # Otherwise, ensure no duplicated tool_use_ids and no exact
        # repeat of the final assistant.message text.
        second_tool_use_ids = {
            e.payload.get("tool_use_id")
            for e in second
            if e.type == "tool_use"
        }
        dups = first_tool_use_ids & second_tool_use_ids
        if dups:
            return ScenarioResult(
                name=name,
                passed=False,
                message=f"adapter re-emitted tool_use_id(s) on resume: {sorted(dups)}",
            )

        second_messages = [e for e in second if e.type == "assistant.message"]
        if second_messages and first_text:
            new_text = text_from(second_messages[-1])
            if new_text == first_text:
                return ScenarioResult(
                    name=name,
                    passed=False,
                    message=(
                        "adapter re-emitted an identical assistant.message text "
                        "on resume — should either terminate or extend the conversation"
                    ),
                )

        return ScenarioResult(
            name=name,
            passed=True,
            message=(
                f"adapter resumed cleanly: first={len(first)}, second={len(second)}"
            ),
        )

    return await run_with_timing(name, body)
