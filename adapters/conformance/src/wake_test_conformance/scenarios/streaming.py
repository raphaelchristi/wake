"""streaming — adapter emits assistant.delta events before assistant.message.

Setup:
    - Inject `user.message` "stream a long response"

Expectations (delta-or-direct):
    - Preferred: adapter emits >=1 ``assistant.delta`` before the final
      ``assistant.message``.
    - Acceptable: adapter emits exactly one ``assistant.message`` and no
      deltas (non-streaming adapters), in which case the scenario passes
      with a WARNING note.

Why it matters: streaming UX is a first-class feature in Wake. Adapters
that can't stream are not disqualified, but consumers must know.
"""

from __future__ import annotations

from wake.adapters import HarnessAdapter

from wake_test_conformance.harness import TestHarness
from wake_test_conformance.result import ScenarioResult
from wake_test_conformance.scenarios._helpers import run_with_timing

name = "streaming"


async def run(adapter: HarnessAdapter) -> ScenarioResult:
    async def body() -> ScenarioResult:
        harness = TestHarness()
        await harness.inject_user_message("stream a long response")

        emitted = await harness.run_step(adapter)

        deltas = [i for i, e in enumerate(emitted) if e.type == "assistant.delta"]
        messages = [i for i, e in enumerate(emitted) if e.type == "assistant.message"]

        if not messages:
            return ScenarioResult(
                name=name,
                passed=False,
                message="adapter never emitted an assistant.message",
            )

        if not deltas:
            # Non-streaming adapter. Must have produced exactly one
            # assistant.message and no deltas.
            if len(messages) != 1:
                return ScenarioResult(
                    name=name,
                    passed=False,
                    message=(
                        f"non-streaming adapter must emit exactly one "
                        f"assistant.message; got {len(messages)}"
                    ),
                )
            return ScenarioResult(
                name=name,
                passed=True,
                message="adapter emitted assistant.message without deltas (non-streaming)",
                warnings=[
                    "adapter does not emit assistant.delta events; "
                    "consumers will not see incremental output"
                ],
            )

        # All deltas must precede the final assistant.message.
        last_message_idx = messages[-1]
        deltas_after_message = [d for d in deltas if d > last_message_idx]
        if deltas_after_message:
            return ScenarioResult(
                name=name,
                passed=False,
                message=(
                    f"{len(deltas_after_message)} assistant.delta event(s) "
                    f"emitted AFTER the final assistant.message"
                ),
            )

        return ScenarioResult(
            name=name,
            passed=True,
            message=(
                f"adapter streamed {len(deltas)} delta(s) before "
                f"{len(messages)} assistant.message(s)"
            ),
        )

    return await run_with_timing(name, body)
