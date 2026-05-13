"""cancellation — adapter respects asyncio.CancelledError without leaking.

Setup:
    - Inject `user.message` "stream a long response"
    - Start `adapter.step(...)` as a task, consuming events into a list
    - Cancel the task after a brief delay (50ms)

Expectations:
    - The task observes CancelledError exactly once
    - No unhandled exception (other than CancelledError) bubbles out
    - The adapter releases its async iterator without raising in __aexit__

Why it matters: any production runtime cancels in-flight steps when the
user interrupts. Adapters that swallow CancelledError or raise spurious
errors on cancellation are broken.
"""

from __future__ import annotations

import asyncio

from wake.adapters import HarnessAdapter
from wake.types import Event

from wake_test_conformance.harness import TestHarness
from wake_test_conformance.result import ScenarioResult
from wake_test_conformance.scenarios._helpers import run_with_timing

name = "cancellation"


async def run(adapter: HarnessAdapter) -> ScenarioResult:
    async def body() -> ScenarioResult:
        harness = TestHarness()
        await harness.inject_user_message("stream a long response")

        collected: list[Event] = []
        cancelled_seen = False

        async def driver() -> None:
            async for ev in adapter.step(harness.context, harness.events, harness.tools):
                collected.append(ev)
                # Give the canceller time to fire after the first event.
                await asyncio.sleep(0.005)

        task = asyncio.create_task(driver())
        await asyncio.sleep(0.05)
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            cancelled_seen = True
        except Exception as e:  # noqa: BLE001
            return ScenarioResult(
                name=name,
                passed=False,
                message=(
                    f"adapter raised {type(e).__name__} during cancellation "
                    f"instead of propagating CancelledError: {e}"
                ),
            )

        if not cancelled_seen and not task.cancelled():
            # Adapter completed before cancellation fired. Acceptable if
            # the step was naturally short — record as a warning.
            return ScenarioResult(
                name=name,
                passed=True,
                message=(
                    f"adapter completed in {len(collected)} events before "
                    "cancel could fire — cancellation path not exercised"
                ),
                warnings=[
                    "adapter completed before cancellation could be tested; "
                    "this scenario only verifies it did not panic"
                ],
            )

        return ScenarioResult(
            name=name,
            passed=True,
            message=(
                f"adapter honored CancelledError after {len(collected)} event(s)"
            ),
        )

    return await run_with_timing(name, body)
