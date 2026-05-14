# ruff: noqa: B008, TC001
"""Replay routes — Phase 8 / Tier 2 gap #10.

POST /v1/sessions/{id}/replay — replay a session with optional
``system_prompt`` / ``tools`` / ``max_steps`` overrides. Returns the
``new_session_id`` so the dashboard can navigate to the replay view.

The handler is intentionally a *thin shell*: it builds a
:class:`ReplayEngine` per request, calls ``replay()`` and translates
``ReplayError`` into a 404. Engine semantics — determinism, override
recording, truncation — live in ``wake.runtime.replay_engine``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from wake.api.dependencies import (
    get_agent_store,
    get_event_log,
    get_session_store,
    get_state,
    get_tenant_context,
    require_role,
)
from wake.core.event_log import EventLog
from wake.rbac import Role
from wake.runtime.replay_engine import ReplayEngine, ReplayError
from wake.store.base import AgentStore, SessionStore
from wake.tenancy import TenantContext
from wake.types import ReplayRequest, ReplayResult

router = APIRouter(prefix="/v1/sessions", tags=["replay"])


@router.post(
    "/{session_id}/replay",
    response_model=ReplayResult,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(Role.ADMIN, Role.OPERATOR))],
)
async def replay_session(
    session_id: str,
    body: ReplayRequest,
    request: Request,
    session_store: SessionStore = Depends(get_session_store),
    agent_store: AgentStore = Depends(get_agent_store),
    event_log: EventLog = Depends(get_event_log),
    tenant: TenantContext = Depends(get_tenant_context),
) -> ReplayResult:
    """Replay ``session_id`` with the provided overrides.

    Returns 201 with the new session id when the replay succeeds.
    Returns 404 when the source session or its pinned agent version
    cannot be resolved (e.g. the agent was archived between recording
    and replay).
    """
    # ``request`` is taken so future hooks can stash the replay outcome
    # on app state (e.g. for SSE broadcast). Unused here but documented
    # in the signature so the route looks consistent with the rest of
    # the API surface.
    _ = get_state(request)

    engine = ReplayEngine(
        session_store=session_store,
        agent_store=agent_store,
        event_log=event_log,
    )
    try:
        return await engine.replay(
            session_id,
            body,
            workspace_id=tenant.workspace_id,
        )
    except ReplayError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
