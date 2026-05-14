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

from wake.api.dependencies import get_environment_store, get_tenant_context, require_role
from wake.rbac import Role
from wake.store.base import EnvironmentStore, StoreError
from wake.tenancy import TenantContext
from wake.types import EnvironmentConfig

router = APIRouter(prefix="/v1/environments", tags=["environments"])


class EnvironmentCreate(BaseModel):
    name: str
    config: dict[str, Any] = Field(default_factory=dict)


class EnvironmentList(BaseModel):
    data: list[EnvironmentConfig]


@router.post(
    "",
    response_model=EnvironmentConfig,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(Role.ADMIN, Role.OPERATOR))],
)
async def create_environment(
    body: EnvironmentCreate,
    store: EnvironmentStore = Depends(get_environment_store),
    tenant: TenantContext = Depends(get_tenant_context),
) -> EnvironmentConfig:
    return await store.create(
        name=body.name,
        config=body.config,
        organization_id=tenant.organization_id,
        workspace_id=tenant.workspace_id,
    )


@router.get("", response_model=EnvironmentList)
async def list_environments(
    store: EnvironmentStore = Depends(get_environment_store),
    tenant: TenantContext = Depends(get_tenant_context),
) -> EnvironmentList:
    return EnvironmentList(data=await store.list(workspace_id=tenant.workspace_id))


@router.get("/{env_id}", response_model=EnvironmentConfig)
async def get_environment(
    env_id: str,
    store: EnvironmentStore = Depends(get_environment_store),
    tenant: TenantContext = Depends(get_tenant_context),
) -> EnvironmentConfig:
    env = await store.get(env_id, workspace_id=tenant.workspace_id)
    if env is None:
        raise HTTPException(status_code=404, detail="environment not found")
    return env


@router.post(
    "/{env_id}/archive",
    response_model=EnvironmentConfig,
    dependencies=[Depends(require_role(Role.ADMIN, Role.OPERATOR))],
)
async def archive_environment(
    env_id: str,
    store: EnvironmentStore = Depends(get_environment_store),
    tenant: TenantContext = Depends(get_tenant_context),
) -> EnvironmentConfig:
    try:
        return await store.archive(env_id, workspace_id=tenant.workspace_id)
    except (KeyError, StoreError) as e:
        raise HTTPException(status_code=404, detail="environment not found") from e


@router.delete(
    "/{env_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(Role.ADMIN, Role.OPERATOR))],
)
async def delete_environment(
    env_id: str,
    store: EnvironmentStore = Depends(get_environment_store),
    tenant: TenantContext = Depends(get_tenant_context),
) -> None:
    try:
        await store.delete(env_id, workspace_id=tenant.workspace_id)
    except (KeyError, StoreError) as e:
        raise HTTPException(status_code=404, detail="environment not found") from e
