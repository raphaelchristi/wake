# ruff: noqa: A002, TC001, TC003
"""Deprecated compat shim — use ``wake_adapter_claude_sdk`` instead.

Phase 2 lifted the hardcoded Anthropic loop onto the ``HarnessAdapter``
ABI. The canonical implementation now lives in
``wake_adapter_claude_sdk.adapter.ClaudeSDKAdapter``.

This module preserves the Phase 1 surface (``AnthropicHarness``,
``events_to_messages``, ``MAX_RECURSION``) by wrapping the new adapter
behind an old-style ``run_step()`` method. A ``DeprecationWarning`` is
emitted on instantiation. Callers should migrate to the
``AdapterRegistry`` + ``SessionDispatcher`` flow exposed in
``wake.api.dependencies`` / ``wake.runtime``.

Slated for removal in Phase 2.5 / Phase 3.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any

import structlog

# Re-export from the new adapter package so existing imports continue to work.
from wake_adapter_claude_sdk.adapter import (
    MAX_RECURSION,
    ClaudeSDKAdapter,
    events_to_messages,
)

from wake.adapters.context import SessionContext
from wake.runtime.event_stream import WakeEventStream
from wake.runtime.tool_registry import WakeToolRegistry

if TYPE_CHECKING:
    from wake.core.event_log import EventLog
    from wake.sandbox.base import SandboxAdapter
    from wake.tools.registry import ToolRegistry
    from wake.types import AgentConfig, SandboxHandle, Session

logger = structlog.get_logger(__name__)

__all__ = [
    "AnthropicHarness",
    "events_to_messages",
    "MAX_RECURSION",
]


class AnthropicHarness:
    """Deprecated. Use ``wake_adapter_claude_sdk.ClaudeSDKAdapter`` + ``SessionDispatcher``.

    Preserves the Phase 1 ``run_step()`` entry point by delegating to the
    new adapter and appending each yielded placeholder event through the
    provided ``EventLog``. Behaviour is identical to Phase 1 for callers
    that already drive it directly (tests, examples).
    """

    def __init__(
        self,
        event_log: EventLog,
        tool_registry: ToolRegistry,
        sandbox: SandboxAdapter | None = None,
        client: Any | None = None,
        *,
        max_tokens: int = 4096,
        max_recursion: int = MAX_RECURSION,
    ) -> None:
        warnings.warn(
            "wake.harness.AnthropicHarness is deprecated; use "
            "wake_adapter_claude_sdk.ClaudeSDKAdapter via "
            "wake.runtime.SessionDispatcher instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._events = event_log
        self._tools = tool_registry
        self._sandbox = sandbox
        self._max_tokens = max_tokens
        self._max_recursion = max_recursion
        # Suppress the inner DeprecationWarning on adapter construction
        # so we only emit one per AnthropicHarness().
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            self._adapter = ClaudeSDKAdapter(
                client=client,
                max_tokens=max_tokens,
                max_recursion=max_recursion,
            )
        # Expose the underlying client for legacy tests that introspect it.
        self._client: Any = self._adapter._client

    async def run_step(
        self,
        session: Session,
        agent: AgentConfig,
        sandbox_handle: SandboxHandle | None = None,
        _depth: int = 0,  # noqa: ARG002 — accepted for Phase-1 signature parity
    ) -> None:
        """Drive one or more LLM rounds until ``end_turn`` or recursion cap.

        Internally delegates to ``ClaudeSDKAdapter.step`` and appends each
        yielded placeholder event through the bound ``EventLog`` so the
        observable side-effects match the Phase 1 implementation.
        """
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
        events_view = WakeEventStream(self._events, session.id)
        tools_view = WakeToolRegistry(self._tools, sandbox_handle=sandbox_handle)

        # tool_use → tool_result correlation: in Phase 1, tool_result
        # carried parent_id = the tool_use event's id. We replay that
        # behaviour by remembering the last-appended tool_use's id and
        # attaching it to the immediately-following tool_result.
        last_tool_use_id: str | None = None
        async for emitted in self._adapter.step(ctx, events_view, tools_view):
            parent_id: str | None = emitted.parent_id
            if emitted.type == "tool_result" and last_tool_use_id is not None:
                parent_id = last_tool_use_id

            persisted = await self._events.append(
                session.id,
                emitted.type,
                emitted.payload,
                parent_id=parent_id,
                metadata=emitted.metadata,
            )

            if emitted.type == "tool_use":
                last_tool_use_id = persisted.id
            elif emitted.type == "tool_result":
                last_tool_use_id = None
