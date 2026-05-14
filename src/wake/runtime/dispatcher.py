"""SessionDispatcher — routes session steps to a registered HarnessAdapter.

The dispatcher is the single Wake-side caller of ``HarnessAdapter.step``.
It is responsible for:

1. Resolving the adapter by name (from agent metadata, falling back to
   ``"claude-sdk"``).
2. Building the per-step ``SessionContext`` from the session + agent
   row.
3. Constructing ``EventStream`` and ``ToolRegistry`` views.
4. Notifying the adapter of lifecycle transitions (``created`` /
   ``resumed``) before invoking ``step()``.
5. Consuming the adapter's async-iterator of placeholder ``Event``
   objects and appending each into the event log (overwriting the
   placeholder ``id``/``seq`` with the runtime-assigned values).

Phase 7 ops-throughput addition: an in-process queue-depth gauge
(``in_flight`` counter + ``max_in_flight`` ceiling) so the API layer
can compute worker saturation and emit ``X-Wake-Worker-Saturation``
or 503 when the system is overloaded.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, cast

import structlog

from wake.adapters.context import SessionContext
from wake.runtime.event_stream import WakeEventStream
from wake.runtime.tool_registry import WakeToolRegistry

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from wake.adapters.base import LifecycleEvent
    from wake.adapters.registry import AdapterRegistry
    from wake.core.event_log import EventLog
    from wake.tools.registry import ToolRegistry as WakeToolsRegistry
    from wake.types import AgentConfig, Event, SandboxHandle, Session

logger = structlog.get_logger(__name__)


DEFAULT_ADAPTER_NAME = "claude-sdk"
"""Adapter name used when an agent doesn't specify one in metadata."""


#: Env var for the maximum in-flight steps used to compute saturation.
WAKE_DISPATCHER_MAX_INFLIGHT_ENV = "WAKE_DISPATCHER_MAX_INFLIGHT"
DEFAULT_MAX_INFLIGHT = 64


def _resolve_max_inflight() -> int:
    raw = os.environ.get(WAKE_DISPATCHER_MAX_INFLIGHT_ENV, "").strip()
    if not raw:
        return DEFAULT_MAX_INFLIGHT
    try:
        n = int(raw)
    except ValueError:
        return DEFAULT_MAX_INFLIGHT
    return max(1, n)


class SessionDispatcher:
    """Drives one step of a session through the configured adapter."""

    def __init__(
        self,
        adapter_registry: AdapterRegistry,
        event_log: EventLog,
        tool_registry: WakeToolsRegistry,
        *,
        default_adapter: str = DEFAULT_ADAPTER_NAME,
        max_in_flight: int | None = None,
    ) -> None:
        self._adapters = adapter_registry
        self._event_log = event_log
        self._tools = tool_registry
        self._default_adapter = default_adapter
        # Backpressure bookkeeping (Phase 7 — Tier 1 gap #4).
        # ``in_flight`` is incremented before ``run_step`` enters the
        # adapter and decremented in the matching ``finally`` block.
        # ``max_in_flight`` is the saturation ceiling: depth/max in
        # [0.0, 1.0] is exposed to the API layer as the
        # ``X-Wake-Worker-Saturation`` header; >= 1.0 triggers 503.
        self.in_flight: int = 0
        self.max_in_flight: int = max_in_flight if max_in_flight is not None else _resolve_max_inflight()

    # ------------------------------------------------------------------ queue depth

    @property
    def queue_depth(self) -> int:
        """Current number of in-flight steps (snapshot — no lock)."""
        return self.in_flight

    def saturation(self) -> float:
        """Return queue depth / ceiling clamped to ``[0.0, ...]``.

        Returns 0.0 when nothing is in flight; >= 1.0 when the
        configured ceiling is met or exceeded. The API layer uses
        this to populate the saturation header and decide 503.
        """
        if self.max_in_flight <= 0:
            return 0.0
        return self.in_flight / self.max_in_flight

    def resolve_adapter_name(self, agent: AgentConfig) -> str:
        """Pick the adapter name for an agent.

        Lookup order: ``agent.metadata["harness"]`` then the dispatcher
        default. Note ``metadata`` is ``dict[str, str]`` so the value is
        already a string when present.
        """
        return agent.metadata.get("harness") or self._default_adapter

    async def run_step(
        self,
        session: Session,
        agent: AgentConfig,
        sandbox_handle: SandboxHandle | None = None,
    ) -> None:
        """Execute one adapter step and persist every event it yields.

        The dispatcher uses the wrapped ``EventLog`` to assign each event
        a session-scoped ``seq``/``id`` — the placeholders the adapter
        emits are discarded.

        The in-flight counter is incremented before the adapter runs
        and decremented in the matching ``finally`` so the saturation
        gauge stays accurate even when an adapter raises.
        """
        adapter_name = self.resolve_adapter_name(agent)
        adapter = self._adapters.get(adapter_name)

        ctx = SessionContext(
            session_id=session.id,
            agent_id=agent.id,
            agent_version=agent.version,
            agent_config=agent,
            environment_id=session.environment_id,
            sandbox=sandbox_handle,
            vault_id=None,
            metadata=session.metadata,
        )
        events = WakeEventStream(
            self._event_log,
            session.id,
            organization_id=session.organization_id,
            workspace_id=session.workspace_id,
        )
        tools = WakeToolRegistry(self._tools, sandbox_handle=sandbox_handle)

        # Lifecycle notification before the step. "resumed" if any events
        # already exist (e.g. user.message just landed), "created"
        # otherwise. The exact semantics may be refined in later
        # phases; this matches the spec language ("first time the session
        # is wake()'d" vs "after a previous step ended").
        existing = await events.count()
        lifecycle: LifecycleEvent = "resumed" if existing > 1 else "created"
        try:
            await adapter.on_lifecycle(ctx, lifecycle)
        except Exception:  # noqa: BLE001
            logger.warning(
                "adapter_on_lifecycle_failed",
                adapter=adapter_name,
                lifecycle=lifecycle,
                exc_info=True,
            )

        logger.info(
            "dispatcher_run_step",
            session_id=session.id,
            adapter=adapter_name,
            lifecycle=lifecycle,
        )

        # Phase 7: queue-depth bookkeeping — increment before the
        # adapter does any work, decrement in finally. Combined with
        # Phase 6.1 fix: persist adapter-emitted events with the
        # session's tenant scope.
        self.in_flight += 1
        try:
            # The Protocol declares ``step`` as ``async def ... -> AsyncIterator``,
            # which mypy reads as a coroutine returning an iterator. Real adapters
            # are async generators that produce an iterator directly — that's the
            # SPEC's intent. Cast keeps mypy --strict happy without changing the
            # scaffolding Protocol.
            stream = cast("AsyncIterator[Event]", adapter.step(ctx, events, tools))
            async for emitted in stream:
                await self._event_log.append(
                    session.id,
                    emitted.type,
                    emitted.payload,
                    parent_id=emitted.parent_id,
                    metadata=emitted.metadata,
                    organization_id=session.organization_id,
                    workspace_id=session.workspace_id,
                )
        finally:
            self.in_flight = max(0, self.in_flight - 1)
