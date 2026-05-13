# STUB: foundation agent will replace this during merge
"""Stub interfaces for storage layer.

These ABCs mirror the contract in `phases/PHASE-1-CONTRACT.md`. The foundation
agent owns the full implementation in `wake/store/base.py` + `wake/store/sqlite.py`.

This stub exists so the runtime slice can import + type-check correctly while
the foundation slice is being built in parallel. It will be replaced during
the merge step.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from wake.types import (
    AgentConfig,
    EnvironmentConfig,
    Event,
    EventType,
    ModelConfig,
    Session,
)


class EventStore(ABC):
    """Append-only store for session events."""

    @abstractmethod
    async def append(
        self,
        session_id: str,
        event_type: EventType,
        payload: dict[str, Any],
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Event: ...

    @abstractmethod
    async def get(self, session_id: str, since: int = 0) -> list[Event]: ...

    @abstractmethod
    async def get_one(self, event_id: str) -> Event | None: ...

    @abstractmethod
    def subscribe(self, session_id: str) -> AsyncIterator[Event]: ...

    @abstractmethod
    async def count(self, session_id: str) -> int: ...


class AgentStore(ABC):
    @abstractmethod
    async def create(
        self,
        name: str,
        model: ModelConfig,
        system: str | None = None,
        tools: list[Any] | None = None,
        mcp_servers: list[Any] | None = None,
        description: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> AgentConfig: ...

    @abstractmethod
    async def get(self, id: str, version: int | None = None) -> AgentConfig | None: ...

    @abstractmethod
    async def update(self, id: str, **changes: Any) -> AgentConfig: ...

    @abstractmethod
    async def list(self) -> list[AgentConfig]: ...

    @abstractmethod
    async def archive(self, id: str) -> AgentConfig: ...

    @abstractmethod
    async def list_versions(self, id: str) -> list[AgentConfig]: ...


class EnvironmentStore(ABC):
    @abstractmethod
    async def create(self, name: str, config: dict[str, Any]) -> EnvironmentConfig: ...

    @abstractmethod
    async def get(self, id: str) -> EnvironmentConfig | None: ...

    @abstractmethod
    async def list(self) -> list[EnvironmentConfig]: ...

    @abstractmethod
    async def archive(self, id: str) -> EnvironmentConfig: ...

    @abstractmethod
    async def delete(self, id: str) -> None: ...


class SessionStore(ABC):
    @abstractmethod
    async def create(
        self,
        agent_id: str,
        agent_version: int,
        environment_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> Session: ...

    @abstractmethod
    async def get(self, id: str) -> Session | None: ...

    @abstractmethod
    async def list(self) -> list[Session]: ...

    @abstractmethod
    async def update_status(self, id: str, status: str) -> Session: ...

    @abstractmethod
    async def update(self, id: str, **changes: Any) -> Session: ...

    @abstractmethod
    async def delete(self, id: str) -> None: ...
