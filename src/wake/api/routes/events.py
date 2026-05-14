# ruff: noqa: B008, TC001, SIM105
"""Session events routes.

POST /v1/sessions/{id}/events   append an event (typically user.message); kicks the dispatcher
GET  /v1/sessions/{id}/events   list events
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from wake.api.dependencies import (
    get_agent_store,
    get_event_log,
    get_session_machine,
    get_state,
    get_tenant_context,
    require_role,
)
from wake.core.event_log import EventLog
from wake.core.session import SessionStateMachine
from wake.rbac import Role
from wake.store.base import AgentStore
from wake.tenancy import TenantContext
from wake.types import Event, EventType

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/v1/sessions", tags=["events"])


class EventCreate(BaseModel):
    type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)
    parent_id: str | None = None
    metadata: dict[str, Any] | None = None
    #: Optional idempotency key — when set, a second request carrying
    #: the same key for the same (workspace, session) returns the
    #: previously-persisted event instead of creating a duplicate.
    idempotency_key: str | None = Field(default=None, max_length=128)


class EventList(BaseModel):
    data: list[Event]


@router.post(
    "/{session_id}/events",
    response_model=Event,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_role(Role.ADMIN, Role.OPERATOR))],
)
async def append_event(
    session_id: str,
    body: EventCreate,
    request: Request,
    background: BackgroundTasks,
    event_log: EventLog = Depends(get_event_log),
    machine: SessionStateMachine = Depends(get_session_machine),
    agent_store: AgentStore = Depends(get_agent_store),
    tenant: TenantContext = Depends(get_tenant_context),
) -> Event:
    session = await machine.get(session_id, workspace_id=tenant.workspace_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    if session.status == "terminated":
        raise HTTPException(status_code=409, detail="session is terminated")

    event = await event_log.append(
        session_id,
        body.type,
        body.payload,
        parent_id=body.parent_id,
        metadata=body.metadata,
        organization_id=session.organization_id,
        workspace_id=session.workspace_id,
        idempotency_key=body.idempotency_key,
    )

    # If the user just spoke, kick the harness in the background through
    # the dispatcher. The dispatcher resolves the adapter by name (from
    # agent metadata or the runtime default) and drives the loop.
    if body.type == "user.message":
        agent = await agent_store.get(
            session.agent_id,
            version=session.agent_version,
            workspace_id=tenant.workspace_id,
        )
        if agent is None:
            raise HTTPException(status_code=404, detail="agent not found")

        state = get_state(request)
        if state.dispatcher is None:
            logger.warning("dispatcher_not_configured", session_id=session_id)
        else:
            background.add_task(_run_dispatcher_safely, request, session_id, agent.id)

    return event


@router.get("/{session_id}/events", response_model=EventList)
async def list_events(
    session_id: str,
    since: int = 0,
    event_log: EventLog = Depends(get_event_log),
    machine: SessionStateMachine = Depends(get_session_machine),
    tenant: TenantContext = Depends(get_tenant_context),
) -> EventList:
    session = await machine.get(session_id, workspace_id=tenant.workspace_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    events = await event_log.get(
        session_id,
        since=since,
        workspace_id=tenant.workspace_id,
    )
    return EventList(data=events)


async def _run_dispatcher_safely(request: Request, session_id: str, agent_id: str) -> None:
    """Background task: drive the configured adapter for a session."""
    state = get_state(request)
    if state.dispatcher is None or state.session_machine is None or state.agent_store is None:
        return

    sess = await state.session_machine.get(session_id)
    if sess is None:
        return
    agent = await state.agent_store.get(
        agent_id,
        version=sess.agent_version,
        workspace_id=sess.workspace_id,
    )
    if agent is None:
        return

    sandbox_handle = state.sandbox_handles.get(session_id)

    try:
        await state.session_machine.start(session_id)
    except ValueError:
        # already running or terminated — skip
        pass

    try:
        await state.dispatcher.run_step(sess, agent, sandbox_handle=sandbox_handle)  # type: ignore[arg-type]
        await state.session_machine.complete(session_id)
    except asyncio.CancelledError:
        await state.session_machine.fail(session_id, "cancelled", transient=False)
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("dispatcher_step_failed", session_id=session_id)
        if state.event_log is not None:
            await state.event_log.append(
                session_id,
                "error",
                {"error_type": "harness_panic", "message": str(e)},
                organization_id=sess.organization_id,
                workspace_id=sess.workspace_id,
            )
        try:
            await state.session_machine.fail(session_id, str(e), transient=False)
        except Exception:  # noqa: BLE001
            pass
