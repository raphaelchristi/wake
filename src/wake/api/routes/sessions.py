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

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from wake.api.dependencies import (
    get_agent_store,
    get_session_machine,
    get_session_store,
    get_state,
)
from wake.core.session import SessionStateMachine
from wake.store.base import AgentStore, SessionStore
from wake.types import Session

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])


class SessionCreate(BaseModel):
    agent_id: str
    environment_id: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class SessionList(BaseModel):
    data: list[Session]


@router.post("", response_model=Session, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: SessionCreate,
    agent_store: AgentStore = Depends(get_agent_store),
    machine: SessionStateMachine = Depends(get_session_machine),
) -> Session:
    agent = await agent_store.get(body.agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return await machine.create(
        agent_id=agent.id,
        agent_version=agent.version,
        environment_id=body.environment_id,
        metadata=body.metadata,
    )


@router.get("", response_model=SessionList)
async def list_sessions(
    store: SessionStore = Depends(get_session_store),
) -> SessionList:
    return SessionList(data=await store.list())


@router.get("/{session_id}", response_model=Session)
async def get_session(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
) -> Session:
    session = await store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    request: Request,
    store: SessionStore = Depends(get_session_store),
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
        await store.delete(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="session not found") from e


@router.post("/{session_id}/interrupt", response_model=Session)
async def interrupt_session(
    session_id: str,
    background: BackgroundTasks,
    machine: SessionStateMachine = Depends(get_session_machine),
) -> Session:
    sess = await machine.get(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    try:
        return await machine.terminate(session_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.post("/{session_id}/archive", response_model=Session)
async def archive_session(
    session_id: str,
    machine: SessionStateMachine = Depends(get_session_machine),
) -> Session:
    sess = await machine.get(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    try:
        return await machine.terminate(session_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
