# ruff: noqa: B008, TC001
# `Depends(...)` defaults are idiomatic FastAPI (B008); store ABCs must be
# importable at runtime so FastAPI can resolve them (TC001).
"""Agent CRUD routes.

POST   /v1/agents              create
GET    /v1/agents              list
GET    /v1/agents/{id}         retrieve
PATCH  /v1/agents/{id}         update (creates new version)
POST   /v1/agents/{id}/archive archive
GET    /v1/agents/{id}/versions list all versions
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from wake.api.dependencies import get_agent_store
from wake.store.base import AgentStore
from wake.types import AgentConfig, McpServerConfig, ModelConfig, ToolConfig

router = APIRouter(prefix="/v1/agents", tags=["agents"])


class AgentCreate(BaseModel):
    name: str
    model: ModelConfig
    system: str | None = None
    tools: list[ToolConfig] = Field(default_factory=list)
    mcp_servers: list[McpServerConfig] = Field(default_factory=list)
    description: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class AgentUpdate(BaseModel):
    name: str | None = None
    model: ModelConfig | None = None
    system: str | None = None
    tools: list[ToolConfig] | None = None
    mcp_servers: list[McpServerConfig] | None = None
    description: str | None = None
    metadata: dict[str, str] | None = None


class AgentList(BaseModel):
    data: list[AgentConfig]


@router.post("", response_model=AgentConfig, status_code=status.HTTP_201_CREATED)
async def create_agent(
    body: AgentCreate,
    store: AgentStore = Depends(get_agent_store),
) -> AgentConfig:
    return await store.create(
        name=body.name,
        model=body.model,
        system=body.system,
        tools=body.tools,
        mcp_servers=body.mcp_servers,
        description=body.description,
        metadata=body.metadata,
    )


@router.get("", response_model=AgentList)
async def list_agents(store: AgentStore = Depends(get_agent_store)) -> AgentList:
    return AgentList(data=await store.list())


@router.get("/{agent_id}", response_model=AgentConfig)
async def get_agent(
    agent_id: str,
    version: int | None = None,
    store: AgentStore = Depends(get_agent_store),
) -> AgentConfig:
    agent = await store.get(agent_id, version=version)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return agent


@router.patch("/{agent_id}", response_model=AgentConfig)
async def update_agent(
    agent_id: str,
    body: AgentUpdate,
    store: AgentStore = Depends(get_agent_store),
) -> AgentConfig:
    changes: dict[str, Any] = {
        k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None
    }
    try:
        return await store.update(agent_id, **changes)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="agent not found") from e


@router.post("/{agent_id}/archive", response_model=AgentConfig)
async def archive_agent(
    agent_id: str,
    store: AgentStore = Depends(get_agent_store),
) -> AgentConfig:
    try:
        return await store.archive(agent_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="agent not found") from e


@router.get("/{agent_id}/versions", response_model=AgentList)
async def list_agent_versions(
    agent_id: str,
    store: AgentStore = Depends(get_agent_store),
) -> AgentList:
    versions = await store.list_versions(agent_id)
    if not versions:
        raise HTTPException(status_code=404, detail="agent not found")
    return AgentList(data=versions)
