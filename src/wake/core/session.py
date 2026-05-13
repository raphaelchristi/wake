# STUB: foundation agent will replace this during merge
"""Stub session state machine.

Foundation agent owns the real implementation; this stub is the minimum needed
for the runtime slice to import + type-check.
"""

from __future__ import annotations

from wake.store.base import EventStore, SessionStore
from wake.types import Session, SessionStatus


class SessionStateMachine:
    """Coordinates session lifecycle transitions across SessionStore + EventStore.

    States: idle, running, rescheduling, terminated.
    """

    VALID_TRANSITIONS: dict[SessionStatus, set[SessionStatus]] = {
        "idle": {"running", "terminated"},
        "running": {"idle", "rescheduling", "terminated"},
        "rescheduling": {"running", "terminated"},
        "terminated": set(),
    }

    def __init__(self, store: SessionStore, event_store: EventStore) -> None:
        self._store = store
        self._event_store = event_store

    async def create(
        self,
        agent_id: str,
        agent_version: int,
        environment_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> Session:
        return await self._store.create(
            agent_id=agent_id,
            agent_version=agent_version,
            environment_id=environment_id,
            metadata=metadata,
        )

    async def get(self, session_id: str) -> Session | None:
        return await self._store.get(session_id)

    async def _transition(self, session_id: str, to: SessionStatus, reason: str) -> Session:
        current = await self._store.get(session_id)
        if current is None:
            raise ValueError(f"session {session_id} not found")
        if to == current.status:
            return current  # idempotent
        if to not in self.VALID_TRANSITIONS.get(current.status, set()):
            raise ValueError(
                f"invalid transition {current.status} → {to} for session {session_id}"
            )
        updated = await self._store.update_status(session_id, to)
        await self._event_store.append(
            session_id,
            "status",
            {"from": current.status, "to": to, "reason": reason},
        )
        return updated

    async def start(self, session_id: str) -> Session:
        return await self._transition(session_id, "running", "step_started")

    async def complete(self, session_id: str) -> Session:
        return await self._transition(session_id, "idle", "end_turn")

    async def fail(
        self, session_id: str, reason: str, transient: bool = True
    ) -> Session:
        target: SessionStatus = "rescheduling" if transient else "terminated"
        return await self._transition(session_id, target, reason)

    async def terminate(self, session_id: str) -> Session:
        return await self._transition(session_id, "terminated", "interrupt")
