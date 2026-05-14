"""In-memory fakes for the foundation stores.

These let the runtime slice be tested end-to-end without depending on the
foundation agent's SQLite implementation.
"""

# Public method parameter ``id`` matches the store ABC contract.
# ruff: noqa: A002, TC003

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from ulid import ULID

from wake.store.base import AgentStore, EnvironmentStore, EventStore, SessionStore
from wake.tenancy import DEFAULT_ORGANIZATION_ID, DEFAULT_WORKSPACE_ID
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
    return datetime.now(UTC)


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
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> Event:
        events = self._events.setdefault(session_id, [])
        seq = len(events)
        ev = Event(
            id=str(ULID()),
            organization_id=organization_id,
            workspace_id=workspace_id,
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

    async def get(
        self,
        session_id: str,
        since: int = 0,
        *,
        workspace_id: str | None = None,
    ) -> list[Event]:
        return [
            e
            for e in self._events.get(session_id, [])
            if e.seq >= since and (workspace_id is None or e.workspace_id == workspace_id)
        ]

    async def get_one(self, event_id: str, *, workspace_id: str | None = None) -> Event | None:
        for evs in self._events.values():
            for e in evs:
                if e.id == event_id and (workspace_id is None or e.workspace_id == workspace_id):
                    return e
        return None

    async def subscribe(
        self,
        session_id: str,
        since: int = 0,
        *,
        workspace_id: str | None = None,
    ) -> AsyncIterator[Event]:
        # Match foundation's pattern: outer coroutine returns the inner
        # async generator instance, so callers can `await store.subscribe(...)`
        # to obtain the iterator.
        return self._subscribe_impl(session_id, since, workspace_id=workspace_id)

    async def _subscribe_impl(
        self, session_id: str, since: int, *, workspace_id: str | None
    ) -> AsyncIterator[Event]:
        # First, replay any existing events from the requested seq onwards.
        for ev in self._events.get(session_id, []):
            if ev.seq >= since and (workspace_id is None or ev.workspace_id == workspace_id):
                yield ev
        # Then subscribe to live events.
        q: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers.setdefault(session_id, []).append(q)
        try:
            while True:
                ev = await q.get()
                if ev.seq >= since and (workspace_id is None or ev.workspace_id == workspace_id):
                    yield ev
        finally:
            self._subscribers[session_id].remove(q)

    async def count(self, session_id: str, *, workspace_id: str | None = None) -> int:
        return len(await self.get(session_id, workspace_id=workspace_id))


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
        skills: list[dict[str, Any]] | None = None,
        description: str | None = None,
        metadata: dict[str, str] | None = None,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> AgentConfig:
        aid = f"agent_{ULID()}"
        agent = AgentConfig(
            id=aid,
            organization_id=organization_id,
            workspace_id=workspace_id,
            name=name,
            model=model,
            system=system,
            tools=tools or [],
            mcp_servers=mcp_servers or [],
            skills=skills or [],
            description=description,
            metadata=metadata or {},
            version=1,
            created_at=_now(),
            updated_at=_now(),
        )
        self._agents[aid] = [agent]
        return agent

    async def get(
        self,
        id: str,
        version: int | None = None,
        *,
        workspace_id: str | None = None,
    ) -> AgentConfig | None:
        versions = self._agents.get(id)
        if not versions:
            return None
        if workspace_id is not None and versions[-1].workspace_id != workspace_id:
            return None
        if version is None:
            return versions[-1]
        if 1 <= version <= len(versions):
            return versions[version - 1]
        return None

    async def update(
        self, id: str, *, workspace_id: str | None = None, **changes: Any
    ) -> AgentConfig:
        versions = self._agents.get(id)
        if not versions or (workspace_id is not None and versions[-1].workspace_id != workspace_id):
            raise KeyError(id)
        current = versions[-1]
        data = current.model_dump()
        data.update({k: v for k, v in changes.items() if v is not None})
        data["version"] = current.version + 1
        data["updated_at"] = _now()
        new = AgentConfig.model_validate(data)
        versions.append(new)
        return new

    async def list(
        self, *, include_archived: bool = False, workspace_id: str | None = None
    ) -> list[AgentConfig]:
        agents = [vs[-1] for vs in self._agents.values()]
        if workspace_id is not None:
            agents = [a for a in agents if a.workspace_id == workspace_id]
        if not include_archived:
            agents = [a for a in agents if a.archived_at is None]
        return agents

    async def archive(self, id: str, *, workspace_id: str | None = None) -> AgentConfig:
        versions = self._agents.get(id)
        if not versions or (workspace_id is not None and versions[-1].workspace_id != workspace_id):
            raise KeyError(id)
        current = versions[-1]
        data = current.model_dump()
        data["archived_at"] = _now()
        new = AgentConfig.model_validate(data)
        versions[-1] = new
        return new

    async def list_versions(self, id: str, *, workspace_id: str | None = None) -> list[AgentConfig]:
        versions = self._agents.get(id, [])
        if workspace_id is not None and versions and versions[-1].workspace_id != workspace_id:
            return []
        return list(versions)


class InMemoryEnvironmentStore(EnvironmentStore):
    def __init__(self) -> None:
        self._envs: dict[str, EnvironmentConfig] = {}

    async def create(
        self,
        name: str,
        config: dict[str, Any],
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> EnvironmentConfig:
        eid = f"env_{ULID()}"
        env = EnvironmentConfig(
            id=eid,
            organization_id=organization_id,
            workspace_id=workspace_id,
            name=name,
            config=config,
            created_at=_now(),
        )
        self._envs[eid] = env
        return env

    async def get(self, id: str, *, workspace_id: str | None = None) -> EnvironmentConfig | None:
        env = self._envs.get(id)
        if env is not None and workspace_id is not None and env.workspace_id != workspace_id:
            return None
        return env

    async def list(
        self, *, include_archived: bool = False, workspace_id: str | None = None
    ) -> list[EnvironmentConfig]:
        envs = list(self._envs.values())
        if workspace_id is not None:
            envs = [e for e in envs if e.workspace_id == workspace_id]
        if not include_archived:
            envs = [e for e in envs if e.archived_at is None]
        return envs

    async def archive(self, id: str, *, workspace_id: str | None = None) -> EnvironmentConfig:
        env = self._envs.get(id)
        if env is None or (workspace_id is not None and env.workspace_id != workspace_id):
            raise KeyError(id)
        data = env.model_dump()
        data["archived_at"] = _now()
        new = EnvironmentConfig.model_validate(data)
        self._envs[id] = new
        return new

    async def delete(self, id: str, *, workspace_id: str | None = None) -> None:
        env = self._envs.get(id)
        if env is None or (workspace_id is not None and env.workspace_id != workspace_id):
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
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> Session:
        sid = f"sess_{ULID()}"
        sess = Session(
            id=sid,
            organization_id=organization_id,
            workspace_id=workspace_id,
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

    async def get(self, id: str, *, workspace_id: str | None = None) -> Session | None:
        sess = self._sessions.get(id)
        if sess is not None and workspace_id is not None and sess.workspace_id != workspace_id:
            return None
        return sess

    async def list(
        self,
        *,
        status: SessionStatus | None = None,
        workspace_id: str | None = None,
    ) -> list[Session]:
        sessions = list(self._sessions.values())
        if workspace_id is not None:
            sessions = [s for s in sessions if s.workspace_id == workspace_id]
        if status is not None:
            sessions = [s for s in sessions if s.status == status]
        return sessions

    async def update_status(
        self, id: str, status: SessionStatus, *, workspace_id: str | None = None
    ) -> Session:
        sess = self._sessions.get(id)
        if sess is None or (workspace_id is not None and sess.workspace_id != workspace_id):
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
        workspace_id: str | None = None,
    ) -> Session:
        sess = self._sessions.get(id)
        if sess is None or (workspace_id is not None and sess.workspace_id != workspace_id):
            raise KeyError(id)
        data = sess.model_dump()
        data["container_id"] = container_id
        if workspace_path is not None:
            data["workspace_path"] = workspace_path
        data["updated_at"] = _now()
        new = Session.model_validate(data)
        self._sessions[id] = new
        return new

    async def delete(self, id: str, *, workspace_id: str | None = None) -> None:
        sess = self._sessions.get(id)
        if sess is None or (workspace_id is not None and sess.workspace_id != workspace_id):
            raise KeyError(id)
        del self._sessions[id]
