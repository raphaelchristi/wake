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
"""

from __future__ import annotations

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


class SessionDispatcher:
    """Drives one step of a session through the configured adapter."""

    def __init__(
        self,
        adapter_registry: AdapterRegistry,
        event_log: EventLog,
        tool_registry: WakeToolsRegistry,
        *,
        default_adapter: str = DEFAULT_ADAPTER_NAME,
    ) -> None:
        self._adapters = adapter_registry
        self._event_log = event_log
        self._tools = tool_registry
        self._default_adapter = default_adapter

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

        # The Protocol declares ``step`` as ``async def ... -> AsyncIterator``,
        # which mypy reads as a coroutine returning an iterator. Real adapters
        # are async generators that produce an iterator directly — that's the
        # SPEC's intent. Cast keeps mypy --strict happy without changing the
        # scaffolding Protocol.
        stream = cast("AsyncIterator[Event]", adapter.step(ctx, events, tools))
        async for emitted in stream:
            # Phase 6.1 finding #2 fix: persist with the session's
            # tenant scope so adapter-emitted events land in the
            # caller's workspace, not the default fallback that the
            # EventLog uses when the caller omits the tenant kwargs.
            await self._event_log.append(
                session.id,
                emitted.type,
                emitted.payload,
                parent_id=emitted.parent_id,
                metadata=emitted.metadata,
                organization_id=session.organization_id,
                workspace_id=session.workspace_id,
            )
