"""basic_step — adapter responds to a trivial user message.

Setup:
    - Inject `user.message` with text "say ok"
    - No tools registered

Expectations:
    - adapter emits >=1 event
    - the final event is an `assistant.message`
    - the assistant message text contains "ok" (case-insensitive)

Why it matters: validates the most fundamental request/response loop.
Any adapter that can't pass this can't handle ANY Wake session.
"""

from __future__ import annotations

from wake.adapters import HarnessAdapter

from wake_test_conformance.harness import TestHarness
from wake_test_conformance.result import ScenarioResult
from wake_test_conformance.scenarios._helpers import run_with_timing, text_from

name = "basic_step"


async def run(adapter: HarnessAdapter) -> ScenarioResult:
    async def body() -> ScenarioResult:
        harness = TestHarness()
        await harness.inject_user_message("say ok")

        emitted = await harness.run_step(adapter)

        if not emitted:
            return ScenarioResult(
                name=name,
                passed=False,
                message="adapter emitted no events for 'say ok'",
            )

        last = emitted[-1]
        if last.type != "assistant.message":
            return ScenarioResult(
                name=name,
                passed=False,
                message=(
                    f"expected final event type='assistant.message', "
                    f"got {last.type!r} (emitted {len(emitted)} events)"
                ),
            )

        text = text_from(last).lower()
        if "ok" not in text:
            return ScenarioResult(
                name=name,
                passed=False,
                message=(
                    f"final assistant.message text did not contain 'ok'; "
                    f"got: {text!r}"
                ),
            )

        return ScenarioResult(
            name=name,
            passed=True,
            message=f"emitted {len(emitted)} event(s); final text contains 'ok'",
        )

    return await run_with_timing(name, body)
