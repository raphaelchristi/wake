"""lifecycle — on_lifecycle accepts all four canonical events.

Setup:
    - Build a TestHarness (no events seeded)

Expectations:
    - ``adapter.on_lifecycle(ctx, e)`` returns None without raising for
      every value of LifecycleEvent: 'created', 'resumed', 'interrupted',
      'terminated'.

Why it matters: the Wake runtime invokes ``on_lifecycle`` at each
session state transition. Adapters MUST tolerate every event even when
they have no business logic for it (the default is no-op).
"""

from __future__ import annotations

from typing import get_args

from wake.adapters import HarnessAdapter, LifecycleEvent

from wake_test_conformance.harness import TestHarness
from wake_test_conformance.result import ScenarioResult
from wake_test_conformance.scenarios._helpers import run_with_timing

name = "lifecycle"


async def run(adapter: HarnessAdapter) -> ScenarioResult:
    async def body() -> ScenarioResult:
        harness = TestHarness()

        events: tuple[LifecycleEvent, ...] = get_args(LifecycleEvent)
        if not events:
            # Defensive: if Literal not introspectable, fall back to spec values.
            events = ("created", "resumed", "interrupted", "terminated")

        for ev in events:
            try:
                rv = await adapter.on_lifecycle(harness.context, ev)
            except Exception as e:  # noqa: BLE001
                return ScenarioResult(
                    name=name,
                    passed=False,
                    message=(
                        f"on_lifecycle({ev!r}) raised "
                        f"{type(e).__name__}: {e}"
                    ),
                )
            if rv is not None:
                return ScenarioResult(
                    name=name,
                    passed=False,
                    message=(
                        f"on_lifecycle({ev!r}) returned {rv!r}; "
                        "spec requires None"
                    ),
                )

        return ScenarioResult(
            name=name,
            passed=True,
            message=f"on_lifecycle accepted {len(events)} event(s) cleanly",
        )

    return await run_with_timing(name, body)
