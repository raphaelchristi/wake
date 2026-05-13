# ruff: noqa: B008, TC001
"""Environment CRUD routes.

POST   /v1/environments
GET    /v1/environments
GET    /v1/environments/{id}
POST   /v1/environments/{id}/archive
DELETE /v1/environments/{id}
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from wake.api.dependencies import get_environment_store
from wake.store.base import EnvironmentStore
from wake.types import EnvironmentConfig

router = APIRouter(prefix="/v1/environments", tags=["environments"])


class EnvironmentCreate(BaseModel):
    name: str
    config: dict[str, Any] = Field(default_factory=dict)


class EnvironmentList(BaseModel):
    data: list[EnvironmentConfig]


@router.post("", response_model=EnvironmentConfig, status_code=status.HTTP_201_CREATED)
async def create_environment(
    body: EnvironmentCreate,
    store: EnvironmentStore = Depends(get_environment_store),
) -> EnvironmentConfig:
    return await store.create(name=body.name, config=body.config)


@router.get("", response_model=EnvironmentList)
async def list_environments(
    store: EnvironmentStore = Depends(get_environment_store),
) -> EnvironmentList:
    return EnvironmentList(data=await store.list())


@router.get("/{env_id}", response_model=EnvironmentConfig)
async def get_environment(
    env_id: str,
    store: EnvironmentStore = Depends(get_environment_store),
) -> EnvironmentConfig:
    env = await store.get(env_id)
    if env is None:
        raise HTTPException(status_code=404, detail="environment not found")
    return env


@router.post("/{env_id}/archive", response_model=EnvironmentConfig)
async def archive_environment(
    env_id: str,
    store: EnvironmentStore = Depends(get_environment_store),
) -> EnvironmentConfig:
    try:
        return await store.archive(env_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="environment not found") from e


@router.delete("/{env_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_environment(
    env_id: str,
    store: EnvironmentStore = Depends(get_environment_store),
) -> None:
    try:
        await store.delete(env_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="environment not found") from e
