"""In-memory fakes for the foundation stores.

These let the runtime slice be tested end-to-end without depending on the
foundation agent's SQLite implementation.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from ulid import ULID

from wake.store.base import AgentStore, EnvironmentStore, EventStore, SessionStore
from wake.types import (
    AgentConfig,
    EnvironmentConfig,
    Event,
    EventType,
    McpServerConfig,
    ModelConfig,
    Session,
    SessionStatus,
    ToolConfig,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class InMemoryEventStore(EventStore):
    def __init__(self) -> None:
        self._events: dict[str, list[Event]] = {}
        self._subscribers: dict[str, list[asyncio.Queue[Event]]] = {}

    async def append(
        self,
        session_id: str,
        event_type: EventType,
        payload: dict[str, Any],
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Event:
        events = self._events.setdefault(session_id, [])
        seq = len(events)
        ev = Event(
            id=str(ULID()),
            session_id=session_id,
            seq=seq,
            type=event_type,
            payload=payload,
            parent_id=parent_id,
            metadata=metadata,
            created_at=_now(),
        )
        events.append(ev)
        for q in self._subscribers.get(session_id, []):
            await q.put(ev)
        return ev

    async def get(self, session_id: str, since: int = 0) -> list[Event]:
        return [e for e in self._events.get(session_id, []) if e.seq >= since]

    async def get_one(self, event_id: str) -> Event | None:
        for evs in self._events.values():
            for e in evs:
                if e.id == event_id:
                    return e
        return None

    async def subscribe(
        self, session_id: str, since: int = 0
    ) -> AsyncIterator[Event]:
        # Match foundation's pattern: outer coroutine returns the inner
        # async generator instance, so callers can `await store.subscribe(...)`
        # to obtain the iterator.
        return self._subscribe_impl(session_id, since)

    async def _subscribe_impl(
        self, session_id: str, since: int
    ) -> AsyncIterator[Event]:
        # First, replay any existing events from the requested seq onwards.
        for ev in self._events.get(session_id, []):
            if ev.seq >= since:
                yield ev
        # Then subscribe to live events.
        q: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers.setdefault(session_id, []).append(q)
        try:
            while True:
                ev = await q.get()
                if ev.seq >= since:
                    yield ev
        finally:
            self._subscribers[session_id].remove(q)

    async def count(self, session_id: str) -> int:
        return len(self._events.get(session_id, []))


class InMemoryAgentStore(AgentStore):
    def __init__(self) -> None:
        # id → list of versions (1-indexed)
        self._agents: dict[str, list[AgentConfig]] = {}

    async def create(
        self,
        name: str,
        model: ModelConfig,
        system: str | None = None,
        tools: list[ToolConfig] | None = None,
        mcp_servers: list[McpServerConfig] | None = None,
        description: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> AgentConfig:
        aid = f"agent_{ULID()}"
        agent = AgentConfig(
            id=aid,
            name=name,
            model=model,
            system=system,
            tools=tools or [],
            mcp_servers=mcp_servers or [],
            description=description,
            metadata=metadata or {},
            version=1,
            created_at=_now(),
            updated_at=_now(),
        )
        self._agents[aid] = [agent]
        return agent

    async def get(self, id: str, version: int | None = None) -> AgentConfig | None:
        versions = self._agents.get(id)
        if not versions:
            return None
        if version is None:
            return versions[-1]
        if 1 <= version <= len(versions):
            return versions[version - 1]
        return None

    async def update(self, id: str, **changes: Any) -> AgentConfig:
        versions = self._agents.get(id)
        if not versions:
            raise KeyError(id)
        current = versions[-1]
        data = current.model_dump()
        data.update({k: v for k, v in changes.items() if v is not None})
        data["version"] = current.version + 1
        data["updated_at"] = _now()
        new = AgentConfig.model_validate(data)
        versions.append(new)
        return new

    async def list(self) -> list[AgentConfig]:
        return [vs[-1] for vs in self._agents.values()]

    async def archive(self, id: str) -> AgentConfig:
        versions = self._agents.get(id)
        if not versions:
            raise KeyError(id)
        current = versions[-1]
        data = current.model_dump()
        data["archived_at"] = _now()
        new = AgentConfig.model_validate(data)
        versions[-1] = new
        return new

    async def list_versions(self, id: str) -> list[AgentConfig]:
        return list(self._agents.get(id, []))


class InMemoryEnvironmentStore(EnvironmentStore):
    def __init__(self) -> None:
        self._envs: dict[str, EnvironmentConfig] = {}

    async def create(self, name: str, config: dict[str, Any]) -> EnvironmentConfig:
        eid = f"env_{ULID()}"
        env = EnvironmentConfig(
            id=eid,
            name=name,
            config=config,
            created_at=_now(),
        )
        self._envs[eid] = env
        return env

    async def get(self, id: str) -> EnvironmentConfig | None:
        return self._envs.get(id)

    async def list(self) -> list[EnvironmentConfig]:
        return list(self._envs.values())

    async def archive(self, id: str) -> EnvironmentConfig:
        env = self._envs.get(id)
        if env is None:
            raise KeyError(id)
        data = env.model_dump()
        data["archived_at"] = _now()
        new = EnvironmentConfig.model_validate(data)
        self._envs[id] = new
        return new

    async def delete(self, id: str) -> None:
        if id not in self._envs:
            raise KeyError(id)
        del self._envs[id]


class InMemorySessionStore(SessionStore):
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    async def create(
        self,
        agent_id: str,
        agent_version: int,
        environment_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> Session:
        sid = f"sess_{ULID()}"
        sess = Session(
            id=sid,
            agent_id=agent_id,
            agent_version=agent_version,
            environment_id=environment_id,
            status="idle",
            metadata=metadata or {},
            created_at=_now(),
            updated_at=_now(),
        )
        self._sessions[sid] = sess
        return sess

    async def get(self, id: str) -> Session | None:
        return self._sessions.get(id)

    async def list(self) -> list[Session]:
        return list(self._sessions.values())

    async def update_status(self, id: str, status: str) -> Session:
        sess = self._sessions.get(id)
        if sess is None:
            raise KeyError(id)
        data = sess.model_dump()
        data["status"] = status
        data["updated_at"] = _now()
        new = Session.model_validate(data)
        self._sessions[id] = new
        return new

    async def update(self, id: str, **changes: Any) -> Session:
        sess = self._sessions.get(id)
        if sess is None:
            raise KeyError(id)
        data = sess.model_dump()
        data.update({k: v for k, v in changes.items() if v is not None})
        data["updated_at"] = _now()
        new = Session.model_validate(data)
        self._sessions[id] = new
        return new

    async def set_container(
        self,
        id: str,
        container_id: str | None,
        workspace_path: str | None = None,
    ) -> Session:
        sess = self._sessions.get(id)
        if sess is None:
            raise KeyError(id)
        data = sess.model_dump()
        data["container_id"] = container_id
        if workspace_path is not None:
            data["workspace_path"] = workspace_path
        data["updated_at"] = _now()
        new = Session.model_validate(data)
        self._sessions[id] = new
        return new

    async def delete(self, id: str) -> None:
        if id not in self._sessions:
            raise KeyError(id)
        del self._sessions[id]
