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
    # DEPRECATED (Phase 5.1 finding #4 fix): OAuth ``state`` is now a
    # signed HMAC-SHA256 token (see ``wake.api.oauth_state``) so callbacks
    # work across replicas. This dict is no longer written to; kept for
    # one release to keep existing imports stable. TODO(0.6.x): remove.
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


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


# Environment variables consulted by ``verify_api_key``.
WAKE_API_KEY_ENV = "WAKE_API_KEY"
WAKE_AUTH_REQUIRED_ENV = "WAKE_AUTH_REQUIRED"
WAKE_API_KEY_HEADER = "X-Wake-API-Key"


def _auth_required_flag() -> bool:
    """Return True when the operator opted into fail-closed auth."""
    raw = os.environ.get(WAKE_AUTH_REQUIRED_ENV, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def is_under_pytest() -> bool:
    """Detect a running pytest process — used to silence the startup warning."""
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) or "PYTEST_VERSION" in os.environ


async def verify_api_key(
    x_wake_api_key: str | None = Header(default=None, alias=WAKE_API_KEY_HEADER),
) -> None:
    """Reject requests that don't carry a valid Wake API key.

    Behaviour (canonical auth modes — see PHASE-5.1-CONTRACT.md):

    * ``WAKE_API_KEY`` unset AND ``WAKE_AUTH_REQUIRED`` unset/false → no-op.
      Preserves zero-friction dev mode.
    * ``WAKE_API_KEY=<key>`` (regardless of ``WAKE_AUTH_REQUIRED``) → the
      ``X-Wake-API-Key`` header must equal ``<key>``. Constant-time compare.
    * ``WAKE_AUTH_REQUIRED=true`` AND ``WAKE_API_KEY`` unset → fail-closed:
      every authenticated request returns 503 ``auth required but not
      configured``. Prevents the production fail-open footgun where the
      operator forgets to inject the key Secret.

    The dependency is mounted at app-level via ``include_router`` so the
    unauthenticated surface (``/health``, ``/docs``, ``/redoc``,
    ``/openapi.json``) is unaffected.
    """
    expected = os.environ.get(WAKE_API_KEY_ENV, "").strip()
    auth_required = _auth_required_flag()

    if not expected:
        if auth_required:
            raise HTTPException(
                status_code=503,
                detail="auth required but not configured",
            )
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
