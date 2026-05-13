"""FastAPI dependency providers and app state container.

Holds references to the storage layer + adapter registry + dispatcher + sandbox
so route handlers can resolve them via ``Depends(...)``. The foundation slice
provides the real store implementations; the runtime slice consumes them
through these dependencies.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from fastapi import Header, HTTPException, Request

if TYPE_CHECKING:
    from wake.adapters.registry import AdapterRegistry
    from wake.core.event_log import EventLog
    from wake.core.session import SessionStateMachine
    from wake.runtime.dispatcher import SessionDispatcher
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
    adapter_registry: AdapterRegistry | None = None
    dispatcher: SessionDispatcher | None = None
    # In-memory map of session_id → sandbox handle (single-process)
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


def get_adapter_registry(request: Request) -> AdapterRegistry:
    s = get_state(request).adapter_registry
    if s is None:
        raise HTTPException(status_code=501, detail="adapter_registry not configured")
    return s


def get_dispatcher(request: Request) -> SessionDispatcher:
    s = get_state(request).dispatcher
    if s is None:
        raise HTTPException(status_code=501, detail="dispatcher not configured")
    return s


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


# Environment variables consulted by ``verify_api_key``.
WAKE_API_KEY_ENV = "WAKE_API_KEY"
WAKE_API_KEY_HEADER = "X-Wake-API-Key"


async def verify_api_key(
    x_wake_api_key: str | None = Header(default=None, alias=WAKE_API_KEY_HEADER),
) -> None:
    """Reject requests that don't carry a valid Wake API key.

    Behaviour:

    * If ``WAKE_API_KEY`` is unset (or empty) the dependency is a no-op — this
      keeps local-dev ergonomics intact and matches how the CLI bootstraps
      a fresh install.
    * Otherwise the request must include the ``X-Wake-API-Key`` header set to
      that value. We compare in constant time to avoid timing oracles.
    * The dependency is mounted at app-level via ``include_router`` so any
      route can be exempted by listing it in ``EXEMPT_AUTH_PATHS`` (e.g.
      ``/health`` and the OpenAPI/Swagger surface).
    """
    expected = os.environ.get(WAKE_API_KEY_ENV, "").strip()
    if not expected:
        return
    provided = (x_wake_api_key or "").strip()
    if not provided:
        raise HTTPException(status_code=401, detail="missing api key")
    if not _constant_time_eq(provided, expected):
        raise HTTPException(status_code=401, detail="invalid api key")


def _constant_time_eq(a: str, b: str) -> bool:
    """Length-aware constant-time compare; tolerates ASCII strings."""
    if len(a) != len(b):
        return False
    acc = 0
    for x, y in zip(a.encode(), b.encode(), strict=True):
        acc |= x ^ y
    return acc == 0
