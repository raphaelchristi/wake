# ruff: noqa: B008, TC001
"""User + role assignment routes.

Endpoints (all under ``/v1/users``):

* ``POST   /v1/users``                       (admin) — create user
* ``GET    /v1/users``                       (admin) — list users
* ``GET    /v1/users/me``                    (any)   — return caller
* ``PATCH  /v1/users/{id}``                  (admin) — update display name
* ``DELETE /v1/users/{id}``                  (admin) — delete user
* ``POST   /v1/users/{id}/roles``            (admin) — assign role
* ``DELETE /v1/users/{id}/roles/{role}``     (admin) — revoke role

Every write is gated by :class:`Role.ADMIN`. The ``GET /me`` route is
open to any authenticated principal — it is the only way a non-admin
can introspect its own role set.

When ``WAKE_RBAC_ENABLED=false`` the routes still work but the gates
are effectively pass-through: ``User.system`` holds every role.
Operators that turn RBAC off keep CRUD access for migration tooling.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — pydantic field type

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from wake.api.dependencies import (
    get_current_user,
    get_tenant_context,
    get_user_store,
    require_role,
)
from wake.rbac import Role, User
from wake.store.base import StoreError, UserStore
from wake.tenancy import TenantContext

router = APIRouter(prefix="/v1/users", tags=["users"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class UserCreate(BaseModel):
    """Body for ``POST /v1/users``."""

    id: str = Field(..., min_length=1, description="Stable user identifier")
    display_name: str | None = None
    # Initial role set. Empty list creates a user with no permissions
    # (useful when the gateway will assign roles later via PATCH).
    roles: list[Role] = Field(default_factory=list)


class UserUpdate(BaseModel):
    display_name: str | None = None


class RoleAssign(BaseModel):
    """Body for ``POST /v1/users/{id}/roles``."""

    role: Role


class UserOut(BaseModel):
    """API-facing shape for a :class:`User`.

    Mirrors the dataclass but trades the tuple for a list so FastAPI's
    JSON encoder can round-trip cleanly.
    """

    id: str
    display_name: str | None
    organization_id: str
    workspace_id: str
    roles: list[Role]
    created_at: datetime | None


class UserList(BaseModel):
    data: list[UserOut]


def _to_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        display_name=user.display_name,
        organization_id=user.organization_id,
        workspace_id=user.workspace_id,
        roles=list(user.roles),
        created_at=user.created_at,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_user(
    body: UserCreate,
    store: UserStore = Depends(get_user_store),
    tenant: TenantContext = Depends(get_tenant_context),
    _admin: User = Depends(require_role(Role.ADMIN)),
) -> UserOut:
    """Create a new user in the request's workspace.

    Optional initial ``roles`` are assigned atomically (best effort —
    the user row is created first; if a role assign fails the user
    row remains so operators can retry). Duplicate user ids in the
    same workspace return ``409``.
    """
    try:
        user = await store.create(
            body.id,
            display_name=body.display_name,
            organization_id=tenant.organization_id,
            workspace_id=tenant.workspace_id,
        )
    except StoreError as exc:
        # Conflict for duplicates, 400 for the reserved id rejection.
        msg = str(exc)
        if "already exists" in msg:
            raise HTTPException(status_code=409, detail=msg) from exc
        raise HTTPException(status_code=400, detail=msg) from exc

    for role in body.roles:
        try:
            await store.assign_role(
                user.id,
                role,
                workspace_id=tenant.workspace_id,
            )
        except StoreError as exc:  # defensive — store.create already validated
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    refreshed = await store.get(user.id, workspace_id=tenant.workspace_id)
    return _to_out(refreshed or user)


@router.get("", response_model=UserList)
async def list_users(
    store: UserStore = Depends(get_user_store),
    tenant: TenantContext = Depends(get_tenant_context),
    _admin: User = Depends(require_role(Role.ADMIN)),
) -> UserList:
    """List users in the request's workspace, oldest first."""
    users = await store.list(workspace_id=tenant.workspace_id)
    return UserList(data=[_to_out(u) for u in users])


@router.get("/me", response_model=UserOut)
async def get_me(
    user: User = Depends(get_current_user),
) -> UserOut:
    """Return the caller's identity + role set.

    Open to any authenticated principal. With RBAC disabled returns
    the ``system`` sentinel so dashboards can render a coherent
    profile without special-casing.
    """
    return _to_out(user)


@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: str,
    store: UserStore = Depends(get_user_store),
    tenant: TenantContext = Depends(get_tenant_context),
    _admin: User = Depends(require_role(Role.ADMIN)),
) -> UserOut:
    user = await store.get(user_id, workspace_id=tenant.workspace_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return _to_out(user)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: str,
    body: UserUpdate,
    store: UserStore = Depends(get_user_store),
    tenant: TenantContext = Depends(get_tenant_context),
    _admin: User = Depends(require_role(Role.ADMIN)),
) -> UserOut:
    try:
        user = await store.update(
            user_id,
            workspace_id=tenant.workspace_id,
            display_name=body.display_name,
        )
    except StoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_out(user)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_user(
    user_id: str,
    store: UserStore = Depends(get_user_store),
    tenant: TenantContext = Depends(get_tenant_context),
    _admin: User = Depends(require_role(Role.ADMIN)),
) -> None:
    try:
        await store.delete(user_id, workspace_id=tenant.workspace_id)
    except StoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/{user_id}/roles",
    response_model=UserOut,
    status_code=status.HTTP_200_OK,
)
async def assign_role(
    user_id: str,
    body: RoleAssign,
    store: UserStore = Depends(get_user_store),
    tenant: TenantContext = Depends(get_tenant_context),
    _admin: User = Depends(require_role(Role.ADMIN)),
) -> UserOut:
    """Idempotent role assignment.

    Returns the refreshed user with the role set. Assigning a role
    the user already has is a no-op (still 200, same payload).
    """
    try:
        await store.assign_role(
            user_id,
            body.role,
            workspace_id=tenant.workspace_id,
        )
    except StoreError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    refreshed = await store.get(user_id, workspace_id=tenant.workspace_id)
    if refreshed is None:
        raise HTTPException(status_code=404, detail="user not found")
    return _to_out(refreshed)


@router.delete(
    "/{user_id}/roles/{role}",
    response_model=UserOut,
)
async def revoke_role(
    user_id: str,
    role: Role,
    store: UserStore = Depends(get_user_store),
    tenant: TenantContext = Depends(get_tenant_context),
    _admin: User = Depends(require_role(Role.ADMIN)),
) -> UserOut:
    """Idempotent role revoke. 404 when the user does not exist."""
    user = await store.get(user_id, workspace_id=tenant.workspace_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    await store.revoke_role(user_id, role, workspace_id=tenant.workspace_id)
    refreshed = await store.get(user_id, workspace_id=tenant.workspace_id)
    return _to_out(refreshed or user)


__all__ = ["router"]
