# ruff: noqa: B008, TC001
"""Sandbox state reconstruction route.

GET /v1/sessions/{id}/state-at/{seq} → snapshot of sandbox state at seq.

The endpoint replays events 0..seq from the event log and returns a minimal
reconstructed view of the sandbox plus running counters. Replay UIs call this
once per scrubber position; the response is intentionally small and cache-
friendly (same input ⇒ same output).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from wake.api.dependencies import get_event_log, get_session_machine
from wake.api.state_reconstruction import reconstruct_state_at
from wake.core.event_log import EventLog
from wake.core.session import SessionStateMachine

router = APIRouter(prefix="/v1/sessions", tags=["replay"])


class SandboxStateResponse(BaseModel):
    cwd: str
    last_output_lines: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)


class StateAtResponse(BaseModel):
    seq: int
    sandbox: SandboxStateResponse
    tool_calls_so_far: int
    errors_so_far: int


@router.get("/{session_id}/state-at/{seq}", response_model=StateAtResponse)
async def get_state_at(
    session_id: str,
    seq: int,
    event_log: EventLog = Depends(get_event_log),
    machine: SessionStateMachine = Depends(get_session_machine),
) -> StateAtResponse:
    if seq < 0:
        raise HTTPException(status_code=422, detail="seq must be >= 0")

    session = await machine.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    events = await event_log.get(session_id, since=0)
    state = reconstruct_state_at(events, seq)
    return StateAtResponse(
        seq=state.seq,
        sandbox=SandboxStateResponse(
            cwd=state.sandbox.cwd,
            last_output_lines=state.sandbox.last_output_lines,
            files_modified=state.sandbox.files_modified,
        ),
        tool_calls_so_far=state.tool_calls_so_far,
        errors_so_far=state.errors_so_far,
    )
