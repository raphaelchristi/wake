"""Session domain + state machine.

Wraps ``SessionStore`` and ``EventLog`` with the lifecycle rules that
the Wake design requires:

    idle ─────► running ─────► idle           (normal turn)
                  │                              ▲
                  ▼                              │
              rescheduling ──────────────────────┘  (transient retry)
                  │
                  ▼
              terminated  ←  (* → terminated allowed at any time)

Every status change is persisted in the ``sessions`` row *and* emitted
as a ``status`` event in the event log, so consumers reading the log
get a faithful history without polling the metadata table.

We use ``python-statemachine`` solely to validate transitions. The
canonical state lives in the SessionStore row (DB is authoritative).
"""

# Several store-method parameters are named `id` per the contract.
# `builtins` is imported at runtime to allow `builtins.list[...]` annotations.
# ruff: noqa: A002, TC001, TC003

from __future__ import annotations

import builtins
from typing import Any, Final

import structlog
from statemachine import State, StateMachine
from statemachine.exceptions import TransitionNotAllowed

from wake.core.event_log import EventLog
from wake.store.base import SessionStore
from wake.types import Session, SessionStatus

log = structlog.get_logger(__name__)


class InvalidTransitionError(Exception):
    """Raised when an invalid status transition is attempted."""


# State definitions ---------------------------------------------------------


VALID_TRANSITIONS: Final[dict[SessionStatus, set[SessionStatus]]] = {
    "idle": {"running", "terminated"},
    "running": {"idle", "rescheduling", "terminated"},
    "rescheduling": {"running", "terminated"},
    "terminated": set(),  # terminal
}


class _SessionFSM(StateMachine):
    """python-statemachine model used purely as a transition validator."""

    idle = State("idle", initial=True)
    running = State("running")
    rescheduling = State("rescheduling")
    terminated = State("terminated", final=True)

    start = idle.to(running)
    complete = running.to(idle)
    reschedule = running.to(rescheduling)
    resume = rescheduling.to(running)
    terminate = (
        idle.to(terminated)
        | running.to(terminated)
        | rescheduling.to(terminated)
    )


def _validate(current: SessionStatus, target: SessionStatus) -> None:
    """Raise InvalidTransitionError if ``current → target`` isn't allowed."""
    allowed = VALID_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise InvalidTransitionError(
            f"invalid transition {current!r} → {target!r}"
        )


# Service ------------------------------------------------------------------


class SessionService:
    """High-level operations on sessions with state-machine guarantees."""

    def __init__(self, store: SessionStore, event_log: EventLog) -> None:
        self._store = store
        self._events = event_log

    # ---- CRUD ----

    async def create(
        self,
        agent_id: str,
        agent_version: int,
        environment_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> Session:
        session = await self._store.create(
            agent_id=agent_id,
            agent_version=agent_version,
            environment_id=environment_id,
            metadata=metadata,
        )
        log.info("session.created", session_id=session.id, agent_id=agent_id)
        return session

    async def get(self, session_id: str) -> Session | None:
        """Return the session by id, or None if not found.

        Convention follows SessionStore.get — callers that require existence
        should check the result. The state-machine methods below (start,
        terminate, etc.) raise InvalidTransitionError if asked to operate on
        a missing session.
        """
        return await self._store.get(session_id)

    async def require(self, session_id: str) -> Session:
        """Fetch the session by id or raise InvalidTransitionError if missing."""
        s = await self._store.get(session_id)
        if s is None:
            raise InvalidTransitionError(f"session {session_id!r} not found")
        return s

    async def list(
        self, *, status: SessionStatus | None = None
    ) -> builtins.list[Session]:
        return await self._store.list(status=status)

    async def delete(self, session_id: str) -> None:
        await self._store.delete(session_id)

    # ---- transitions ----

    async def start(self, session_id: str) -> Session:
        """idle → running. Idempotent if already running."""
        return await self._transition(
            session_id, "running", reason="start", idempotent=True
        )

    async def complete(self, session_id: str, *, reason: str = "end_turn") -> Session:
        """running → idle. Emits status event."""
        return await self._transition(session_id, "idle", reason=reason)

    async def reschedule(
        self, session_id: str, *, reason: str = "transient_error"
    ) -> Session:
        """running → rescheduling."""
        return await self._transition(session_id, "rescheduling", reason=reason)

    async def resume(self, session_id: str, *, reason: str = "retry") -> Session:
        """rescheduling → running."""
        return await self._transition(session_id, "running", reason=reason)

    async def fail(
        self,
        session_id: str,
        reason: str,
        *,
        transient: bool = True,
    ) -> Session:
        """Either rescheduling (transient) or terminated (permanent)."""
        target: SessionStatus = "rescheduling" if transient else "terminated"
        return await self._transition(session_id, target, reason=reason)

    async def terminate(self, session_id: str, *, reason: str = "terminated") -> Session:
        """* → terminated. Idempotent — calling on a terminated session is a no-op."""
        return await self._transition(
            session_id, "terminated", reason=reason, idempotent=True
        )

    # ---- container metadata ----

    async def set_container(
        self,
        session_id: str,
        container_id: str | None,
        workspace_path: str | None = None,
    ) -> Session:
        return await self._store.set_container(
            session_id, container_id=container_id, workspace_path=workspace_path
        )

    # ---- internal ----

    async def _transition(
        self,
        session_id: str,
        target: SessionStatus,
        *,
        reason: str | None,
        idempotent: bool = False,
    ) -> Session:
        current = await self.require(session_id)
        if current.status == target:
            if idempotent:
                # No-op (don't emit duplicate status events).
                return current
            # Same-state transition that the caller did NOT mark idempotent
            # — treat as an invalid transition (e.g. complete() from idle).
            raise InvalidTransitionError(
                f"invalid transition {current.status!r} → {target!r}"
            )
        _validate(current.status, target)
        # Sanity-check with python-statemachine as a second guard.
        fsm = _SessionFSM(start_value=current.status)
        try:
            self._dispatch_fsm(fsm, current.status, target)
        except TransitionNotAllowed as e:
            # Should never happen if VALID_TRANSITIONS matches FSM.
            raise InvalidTransitionError(str(e)) from e
        updated = await self._store.update_status(session_id, target)
        await self._events.status(
            session_id, from_=current.status, to=target, reason=reason
        )
        log.info(
            "session.transition",
            session_id=session_id,
            **{"from": current.status, "to": target, "reason": reason},
        )
        return updated

    @staticmethod
    def _dispatch_fsm(
        fsm: _SessionFSM, current: SessionStatus, target: SessionStatus
    ) -> None:
        # Map (current,target) to the corresponding event name.
        event = _FSM_EVENTS[(current, target)]
        method: Any = getattr(fsm, event)
        method()


_FSM_EVENTS: Final[dict[tuple[SessionStatus, SessionStatus], str]] = {
    ("idle", "running"): "start",
    ("running", "idle"): "complete",
    ("running", "rescheduling"): "reschedule",
    ("rescheduling", "running"): "resume",
    ("idle", "terminated"): "terminate",
    ("running", "terminated"): "terminate",
    ("rescheduling", "terminated"): "terminate",
}


# Compatibility alias: runtime slice was written against the SessionStateMachine
# name (per PHASE-1-CONTRACT.md). Foundation chose SessionService; keep both
# names pointing at the same class for backward compatibility.
SessionStateMachine = SessionService
