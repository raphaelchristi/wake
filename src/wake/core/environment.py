"""Environment domain service.

Environments are simple — no versioning (matching Managed Agents). This
service is a thin facade for parity with ``AgentService``/``SessionService``.
"""

# `id` is mandated by the contract. `builtins` is imported at runtime to
# allow `builtins.list[...]` annotations.
# ruff: noqa: A002, TC001, TC003

from __future__ import annotations

import builtins
from typing import Any

import structlog

from wake.store.base import EnvironmentStore
from wake.types import EnvironmentConfig

log = structlog.get_logger(__name__)


class EnvironmentService:
    def __init__(self, store: EnvironmentStore) -> None:
        self._store = store

    async def create(
        self, name: str, config: dict[str, Any] | None = None
    ) -> EnvironmentConfig:
        env = await self._store.create(name=name, config=dict(config or {}))
        log.info("environment.created", env_id=env.id, name=name)
        return env

    async def get(self, id: str) -> EnvironmentConfig | None:
        return await self._store.get(id)

    async def list(
        self, *, include_archived: bool = False
    ) -> builtins.list[EnvironmentConfig]:
        return await self._store.list(include_archived=include_archived)

    async def archive(self, id: str) -> EnvironmentConfig:
        return await self._store.archive(id)

    async def delete(self, id: str) -> None:
        await self._store.delete(id)
