"""Agent domain service.

Thin facade over ``AgentStore`` that adds:
- Friendly defaults
- Logging
- A single place to add cross-cutting concerns (auth, audit) later
"""

# `id` is mandated by the contract. `builtins` is imported at runtime so
# we can write `builtins.list[...]` annotations without shadowing the
# locally-defined `list` method.
# ruff: noqa: A002, TC001, TC003

from __future__ import annotations

import builtins
from typing import Any

import structlog

from wake.store.base import AgentStore
from wake.types import AgentConfig, McpServerConfig, ModelConfig, ToolConfig

log = structlog.get_logger(__name__)


class AgentService:
    """High-level operations on agents."""

    def __init__(self, store: AgentStore) -> None:
        self._store = store

    async def create(
        self,
        name: str,
        model: ModelConfig | dict[str, Any] | str,
        *,
        system: str | None = None,
        tools: list[ToolConfig | dict[str, Any]] | None = None,
        mcp_servers: list[McpServerConfig | dict[str, Any]] | None = None,
        skills: list[dict[str, Any]] | None = None,
        description: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> AgentConfig:
        """Create an agent. Accepts model as object, dict, or model-id string."""
        model_obj = _coerce_model(model)
        agent = await self._store.create(
            name=name,
            model=model_obj,
            system=system,
            tools=list(tools or []),
            mcp_servers=list(mcp_servers or []),
            skills=list(skills or []),
            description=description,
            metadata=dict(metadata or {}),
        )
        log.info("agent.service.created", agent_id=agent.id, name=name)
        return agent

    async def get(self, id: str, version: int | None = None) -> AgentConfig | None:
        return await self._store.get(id, version=version)

    async def update(self, id: str, **changes: Any) -> AgentConfig:
        if "model" in changes:
            changes["model"] = _coerce_model(changes["model"])
        return await self._store.update(id, **changes)

    async def list(
        self, *, include_archived: bool = False
    ) -> builtins.list[AgentConfig]:
        return await self._store.list(include_archived=include_archived)

    async def list_versions(self, id: str) -> builtins.list[AgentConfig]:
        return await self._store.list_versions(id)

    async def archive(self, id: str) -> AgentConfig:
        return await self._store.archive(id)


def _coerce_model(model: ModelConfig | dict[str, Any] | str) -> ModelConfig:
    if isinstance(model, ModelConfig):
        return model
    if isinstance(model, str):
        return ModelConfig(id=model)
    return ModelConfig.model_validate(model)
