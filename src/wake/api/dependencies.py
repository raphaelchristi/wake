"""FastAPI dependency providers and app state container.

Holds references to the storage layer + adapter registry + dispatcher + sandbox
so route handlers can resolve them via ``Depends(...)``. The foundation slice
provides the real store implementations; the runtime slice consumes them
through these dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

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
    # Phase 5 metrics-vault slice. ``vault`` is typed loosely (``object``)
    # so we don't take a hard dep on the wake_vault_infisical adapter
    # package at import time. Vault routes verify the duck-typed surface
    # at call time and return 503 when missing.
    vault: object | None = None
    # OAuth client config keyed by provider name. Populated from env
    # vars (``WAKE_OAUTH_<PROVIDER>_CLIENT_ID/SECRET/REDIRECT_URI``) at
    # startup by ``create_app`` callers.
    oauth_clients: dict[str, dict[str, str]] = field(default_factory=dict)
    # In-memory audit log (single-process). Postgres-backed stores
    # supersede this in production.
    vault_audit: list[dict[str, object]] = field(default_factory=list)
    # OAuth ``state`` → ``flow`` map for callback verification. Cleared
    # when the matching callback completes (or on TTL).
    oauth_flows: dict[str, object] = field(default_factory=dict)


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


def get_vault(request: Request) -> object:
    """Return the configured vault adapter, or raise 503.

    Phase 5: vault routes deliberately return 503 when no vault is wired
    (NOT 500), so the dashboard can render an "Offline" empty state
    without surfacing as a backend bug.
    """
    s = get_state(request).vault
    if s is None:
        raise HTTPException(status_code=503, detail="Vault not configured")
    return s
