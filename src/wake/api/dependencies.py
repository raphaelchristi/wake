"""FastAPI dependency providers and app state container.

Holds references to the storage layer + harness + sandbox so route handlers can
resolve them via `Depends(...)`. In Phase 1 the foundation slice provides the
real store implementations; the runtime slice consumes them through these
dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

if TYPE_CHECKING:
    from wake.core.event_log import EventLog
    from wake.core.session import SessionStateMachine
    from wake.harness.anthropic import AnthropicHarness
    from wake.sandbox.base import SandboxAdapter
    from wake.store.base import AgentStore, EnvironmentStore, SessionStore
    from wake.tools.registry import ToolRegistry


@dataclass
class AppState:
    """Container for everything the API routes need access to."""

    agent_store: AgentStore | None = None
    environment_store: EnvironmentStore | None = None
    session_store: SessionStore | None = None
    event_log: EventLog | None = None
    session_machine: SessionStateMachine | None = None
    tool_registry: ToolRegistry | None = None
    sandbox: SandboxAdapter | None = None
    harness: AnthropicHarness | None = None
    # In-memory map of session_id → sandbox handle (Phase 1 stays single-process)
    sandbox_handles: dict[str, object] = field(default_factory=dict)


def get_state(request: Request) -> AppState:
    state: AppState | None = getattr(request.app.state, "wake", None)
    if state is None:
        raise HTTPException(status_code=503, detail="wake state not initialized")
    return state


def get_agent_store(request: Request) -> AgentStore:
    s = get_state(request).agent_store
    if s is None:
        raise HTTPException(status_code=501, detail="agent_store not configured")
    return s


def get_environment_store(request: Request) -> EnvironmentStore:
    s = get_state(request).environment_store
    if s is None:
        raise HTTPException(status_code=501, detail="environment_store not configured")
    return s


def get_session_store(request: Request) -> SessionStore:
    s = get_state(request).session_store
    if s is None:
        raise HTTPException(status_code=501, detail="session_store not configured")
    return s


def get_event_log(request: Request) -> EventLog:
    s = get_state(request).event_log
    if s is None:
        raise HTTPException(status_code=501, detail="event_log not configured")
    return s


def get_session_machine(request: Request) -> SessionStateMachine:
    s = get_state(request).session_machine
    if s is None:
        raise HTTPException(status_code=501, detail="session_machine not configured")
    return s
