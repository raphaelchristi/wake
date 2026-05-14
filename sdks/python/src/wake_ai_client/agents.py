"""Agent CRUD + versioning operations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from wake_ai_client.types import AgentConfig, McpServerConfig, ModelConfig, ToolConfig

if TYPE_CHECKING:
    from wake_ai_client.client import WakeClient


class AgentsResource:
    """Resource bag for ``/v1/agents/*`` routes."""

    def __init__(self, client: WakeClient) -> None:
        self._client = client

    async def create(
        self,
        *,
        name: str,
        model: ModelConfig | Mapping[str, Any],
        system: str | None = None,
        tools: Sequence[ToolConfig | Mapping[str, Any]] | None = None,
        mcp_servers: Sequence[McpServerConfig | Mapping[str, Any]] | None = None,
        description: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> AgentConfig:
        body: dict[str, Any] = {
            "name": name,
            "model": _model_dump(model),
        }
        if system is not None:
            body["system"] = system
        if tools is not None:
            body["tools"] = [_model_dump(t) for t in tools]
        if mcp_servers is not None:
            body["mcp_servers"] = [_model_dump(m) for m in mcp_servers]
        if description is not None:
            body["description"] = description
        if metadata is not None:
            body["metadata"] = dict(metadata)
        data = await self._client.request("POST", "/v1/agents", json=body)
        return AgentConfig.model_validate(data)

    async def list(self) -> list[AgentConfig]:
        data = await self._client.request("GET", "/v1/agents")
        return [AgentConfig.model_validate(a) for a in (data or {}).get("data", [])]

    async def get(self, agent_id: str, *, version: int | None = None) -> AgentConfig:
        params = {"version": version} if version is not None else None
        data = await self._client.request(
            "GET", f"/v1/agents/{_q(agent_id)}", params=params
        )
        return AgentConfig.model_validate(data)

    async def update(
        self,
        agent_id: str,
        *,
        name: str | None = None,
        model: ModelConfig | Mapping[str, Any] | None = None,
        system: str | None = None,
        tools: Sequence[ToolConfig | Mapping[str, Any]] | None = None,
        mcp_servers: Sequence[McpServerConfig | Mapping[str, Any]] | None = None,
        description: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> AgentConfig:
        """Update an agent. Each call bumps ``version`` server-side."""
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if model is not None:
            body["model"] = _model_dump(model)
        if system is not None:
            body["system"] = system
        if tools is not None:
            body["tools"] = [_model_dump(t) for t in tools]
        if mcp_servers is not None:
            body["mcp_servers"] = [_model_dump(m) for m in mcp_servers]
        if description is not None:
            body["description"] = description
        if metadata is not None:
            body["metadata"] = dict(metadata)
        data = await self._client.request(
            "PATCH", f"/v1/agents/{_q(agent_id)}", json=body
        )
        return AgentConfig.model_validate(data)

    async def archive(self, agent_id: str) -> AgentConfig:
        data = await self._client.request(
            "POST", f"/v1/agents/{_q(agent_id)}/archive"
        )
        return AgentConfig.model_validate(data)

    async def list_versions(self, agent_id: str) -> list[AgentConfig]:
        data = await self._client.request(
            "GET", f"/v1/agents/{_q(agent_id)}/versions"
        )
        return [AgentConfig.model_validate(a) for a in (data or {}).get("data", [])]


def _model_dump(value: Any) -> Any:
    """Accept either a pydantic model or a plain mapping."""
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value


def _q(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")
