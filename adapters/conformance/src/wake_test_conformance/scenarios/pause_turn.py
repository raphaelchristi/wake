"""pause_turn — adapter emits pause_turn when conditions request it.

Setup:
    - Inject `user.message` containing the marker token "PLEASE_PAUSE"
      (echo adapters and well-behaved adapters can opt-in by detecting it)

Expectations (LENIENT):
    - If the adapter emits a `pause_turn` event, scenario passes with a
      message noting the reason.
    - If the adapter does not emit `pause_turn`, scenario passes with a
      warning: "adapter does not signal pause_turn".

Why it matters: long-running turns must be observable. This scenario is
lenient because not every framework supports the concept natively; the
goal is to surface the gap so consumers can plan around it.
"""

from __future__ import annotations

from wake.adapters import HarnessAdapter

from wake_test_conformance.harness import TestHarness
from wake_test_conformance.result import ScenarioResult
from wake_test_conformance.scenarios._helpers import run_with_timing

name = "pause_turn"


async def run(adapter: HarnessAdapter) -> ScenarioResult:
    async def body() -> ScenarioResult:
        harness = TestHarness(metadata={"conformance_pause_hint": "1"})
        await harness.inject_user_message("PLEASE_PAUSE: do long work")

        emitted = await harness.run_step(adapter)

        pauses = [e for e in emitted if e.type == "pause_turn"]
        if pauses:
            reason = (pauses[-1].payload or {}).get("reason", "unspecified")
            return ScenarioResult(
                name=name,
                passed=True,
                message=f"adapter emitted pause_turn (reason={reason!r})",
            )

        return ScenarioResult(
            name=name,
            passed=True,
            message="adapter did not emit pause_turn (optional feature)",
            warnings=[
                "adapter does not signal pause_turn; long-running turns will not "
                "be observable mid-flight"
            ],
        )

    return await run_with_timing(name, body)
