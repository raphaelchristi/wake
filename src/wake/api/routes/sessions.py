# ruff: noqa: B008, TC001, SIM105
"""Session routes.

POST   /v1/sessions                       create
GET    /v1/sessions                       list
GET    /v1/sessions/{id}                  retrieve
DELETE /v1/sessions/{id}                  delete
POST   /v1/sessions/{id}/interrupt        interrupt running session
POST   /v1/sessions/{id}/archive          archive

(events endpoints live in routes/events.py; SSE in api/sse.py)
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from wake.api.dependencies import (
    get_agent_store,
    get_session_machine,
    get_session_store,
    get_state,
    get_tenant_context,
    require_role,
)
from wake.core.session import SessionStateMachine
from wake.rbac import Role
from wake.store.base import AgentStore, SessionStore, StoreError
from wake.tenancy import TenantContext
from wake.types import Session, SessionStatus

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


class SessionCreate(BaseModel):
    agent_id: str
    environment_id: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class SessionList(BaseModel):
    data: list[Session]


@router.post(
    "",
    response_model=Session,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(Role.ADMIN, Role.OPERATOR))],
)
async def create_session(
    body: SessionCreate,
    agent_store: AgentStore = Depends(get_agent_store),
    machine: SessionStateMachine = Depends(get_session_machine),
    tenant: TenantContext = Depends(get_tenant_context),
) -> Session:
    agent = await agent_store.get(body.agent_id, workspace_id=tenant.workspace_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return await machine.create(
        agent_id=agent.id,
        agent_version=agent.version,
        environment_id=body.environment_id,
        metadata=body.metadata,
        organization_id=tenant.organization_id,
        workspace_id=tenant.workspace_id,
    )


@router.get("", response_model=SessionList)
async def list_sessions(
    store: SessionStore = Depends(get_session_store),
    tenant: TenantContext = Depends(get_tenant_context),
    agent: str | None = Query(default=None, description="Filter by agent_id (exact)."),
    status_: SessionStatus | None = Query(
        default=None,
        alias="status",
        description="Filter by session status.",
    ),
    model: str | None = Query(
        default=None,
        description="Filter by metadata['model'] substring (case-insensitive).",
    ),
    since: datetime | None = Query(
        default=None,
        description="Only sessions created_at >= ISO 8601 timestamp.",
    ),
    until: datetime | None = Query(
        default=None,
        description="Only sessions created_at <= ISO 8601 timestamp.",
    ),
    q: str | None = Query(
        default=None,
        description=(
            "Free-text search across session_id, agent_id, and metadata values "
            "(case-insensitive substring)."
        ),
    ),
    page: int = Query(default=1, ge=1, description="1-indexed page number."),
    page_size: int = Query(
        default=50,
        ge=1,
        le=200,
        description="Sessions per page (1-200).",
    ),
) -> SessionList:
    """List sessions with optional filters and offset pagination.

    Filters are applied additively (AND). The response shape is unchanged from
    Phase 1 — just a ``{ "data": [...] }`` envelope — so existing clients keep
    working. New clients pass query params to narrow the view.
    """
    all_sessions = await store.list(workspace_id=tenant.workspace_id)
    filtered = _filter_sessions(
        all_sessions,
        agent=agent,
        status_=status_,
        model=model,
        since=since,
        until=until,
        q=q,
    )
    # Stable ordering by created_at desc so paging is deterministic.
    filtered.sort(key=lambda s: s.created_at, reverse=True)
    offset = (page - 1) * page_size
    return SessionList(data=filtered[offset : offset + page_size])


def _filter_sessions(
    sessions: list[Session],
    *,
    agent: str | None,
    status_: SessionStatus | None,
    model: str | None,
    since: datetime | None,
    until: datetime | None,
    q: str | None,
) -> list[Session]:
    def _ensure_aware(dt: datetime | None) -> datetime | None:
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt

    since_n = _ensure_aware(since)
    until_n = _ensure_aware(until)
    model_n = model.lower() if model else None
    q_n = q.lower() if q else None

    out: list[Session] = []
    for s in sessions:
        if agent and s.agent_id != agent:
            continue
        if status_ and s.status != status_:
            continue

        created = _ensure_aware(s.created_at)
        if since_n and (created is None or created < since_n):
            continue
        if until_n and (created is None or created > until_n):
            continue

        if model_n:
            session_model = (s.metadata or {}).get("model", "").lower()
            if model_n not in session_model:
                continue

        if q_n:
            haystack_parts = [s.id, s.agent_id]
            for v in (s.metadata or {}).values():
                haystack_parts.append(v)
            haystack = " ".join(haystack_parts).lower()
            if q_n not in haystack:
                continue

        out.append(s)
    return out


@router.get("/{session_id}", response_model=Session)
async def get_session(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
    tenant: TenantContext = Depends(get_tenant_context),
) -> Session:
    session = await store.get(session_id, workspace_id=tenant.workspace_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(Role.ADMIN, Role.OPERATOR))],
)
async def delete_session(
    session_id: str,
    request: Request,
    store: SessionStore = Depends(get_session_store),
    tenant: TenantContext = Depends(get_tenant_context),
) -> None:
    # Best-effort: tear down sandbox first
    state = get_state(request)
    handle = state.sandbox_handles.pop(session_id, None)
    if handle is not None and state.sandbox is not None:
        try:
            await state.sandbox.destroy(handle)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001
            pass
    try:
        await store.delete(session_id, workspace_id=tenant.workspace_id)
    except (KeyError, StoreError) as e:
        raise HTTPException(status_code=404, detail="session not found") from e


@router.post(
    "/{session_id}/interrupt",
    response_model=Session,
    dependencies=[Depends(require_role(Role.ADMIN, Role.OPERATOR))],
)
async def interrupt_session(
    session_id: str,
    background: BackgroundTasks,
    machine: SessionStateMachine = Depends(get_session_machine),
    tenant: TenantContext = Depends(get_tenant_context),
) -> Session:
    sess = await machine.get(session_id, workspace_id=tenant.workspace_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    try:
        return await machine.terminate(session_id, workspace_id=tenant.workspace_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.post(
    "/{session_id}/archive",
    response_model=Session,
    dependencies=[Depends(require_role(Role.ADMIN, Role.OPERATOR))],
)
async def archive_session(
    session_id: str,
    machine: SessionStateMachine = Depends(get_session_machine),
    tenant: TenantContext = Depends(get_tenant_context),
) -> Session:
    sess = await machine.get(session_id, workspace_id=tenant.workspace_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    try:
        return await machine.terminate(session_id, workspace_id=tenant.workspace_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
