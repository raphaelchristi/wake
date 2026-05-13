"""CrewAI adapter for Wake — STUB.

This is a Phase 2 stub that demonstrates the :class:`HarnessAdapter`
Protocol plus entry-point discovery. It deliberately has **zero**
CrewAI dependency: a real implementation that runs CrewAI ``Crew``s
is planned for Phase 3.

See:
    - ``docs/SPEC-HARNESS-ADAPTER.md`` — narrative spec
    - ``docs/WRITING-AN-ADAPTER.md`` — tutorial
    - ``phases/PHASE-3-spec-validation.md`` — when this becomes real
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ulid import ULID

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from wake.adapters import EventStream, LifecycleEvent, SessionContext, ToolRegistry
    from wake.types import Event


class CrewAIAdapter:
    """Stub adapter that pretends to host a CrewAI ``Crew``.

    Conforms to the ``HarnessAdapter`` Protocol but emits a single
    canned ``assistant.message`` regardless of input. Use it to verify
    that:

    1. The adapter package installs cleanly.
    2. The ``wake.adapters`` entry point is picked up by
       :class:`wake.adapters.AdapterRegistry`.
    3. ``step()`` plumbs through the runtime.

    A production-grade replacement lives in Phase 3.
    """

    name: str = "crewai"
    version: str = "0.1.0-stub"
    compatibility: str = "wake-harness-adapter@^0.1"

    async def step(
        self,
        ctx: SessionContext,
        events: EventStream,
        tools: ToolRegistry,
    ) -> AsyncIterator[Event]:
        """Emit exactly one ``assistant.message`` event.

        Input is ignored. The point of the stub is to prove the wiring,
        not to reason. ``seq`` is left at 0 — the runtime reassigns it
        when persisting.
        """
        # Local imports keep import-time cost low and avoid a circular
        # dependency at module load.
        from wake.types import Event, TextBlock

        yield Event(
            id=str(ULID()),
            session_id=ctx.session_id,
            seq=0,  # runtime will reassign on append
            type="assistant.message",
            payload={
                "content": [TextBlock(text="stub from crewai").model_dump()],
                "stop_reason": "end_turn",
            },
            created_at=datetime.now(UTC),
        )

    async def on_lifecycle(
        self,
        ctx: SessionContext,
        event: LifecycleEvent,
    ) -> None:
        """No-op lifecycle hook.

        A real CrewAI adapter would assemble a ``Crew`` on ``created``
        (CrewAI setup is expensive) and tear it down on ``terminated``.
        """
        return None


def create() -> CrewAIAdapter:
    """Factory used by the ``wake.adapters`` entry point.

    Returns a default-configured instance. Callers that need a real
    CrewAI ``Crew`` would pass a ``crew_factory`` callable to the class
    constructor directly instead of going through this factory.
    """
    return CrewAIAdapter()
