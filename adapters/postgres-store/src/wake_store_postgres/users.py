"""PostgresUserStore — RBAC users + role bindings.

Mirrors :class:`wake.store.sqlite.SQLiteUserStore`: same method
surface, same idempotent semantics. The schema mirrors the SQLite
layout exactly (composite PK on ``(workspace_id, id)``), kept in
sync by the Phase 6 migration ``0003_rbac``.

The ``user_roles`` table carries an ``ON DELETE CASCADE`` FK so
``delete_user`` purges the role bindings transactionally inside
Postgres — no application-level cascade needed (unlike the SQLite
backend which carries the cascade in Python to stay schema-portable).
"""

# Public method parameter ``id`` matches the ABC contract.
# ruff: noqa: A002

from __future__ import annotations

import builtins
from datetime import UTC, datetime

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from wake.rbac import Role, User
from wake.store.base import StoreError, UserStore
from wake.tenancy import DEFAULT_ORGANIZATION_ID, DEFAULT_WORKSPACE_ID

from wake_store_postgres.models import UserRoleRow, UserRow

log = structlog.get_logger(__name__)


SYSTEM_USER_ID = "system"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _sorted_roles(roles: builtins.list[Role]) -> builtins.list[Role]:
    order = {r: i for i, r in enumerate(Role)}
    return sorted(set(roles), key=lambda r: order[r])


def _row_to_user(row: UserRow, role_rows: builtins.list[UserRoleRow]) -> User:
    roles = _sorted_roles(
        [Role.parse(r.role) for r in role_rows if r.user_id == row.id]
    )
    return User(
        id=row.id,
        display_name=row.display_name,
        roles=tuple(roles),
        organization_id=row.organization_id,
        workspace_id=row.workspace_id,
        created_at=row.created_at,
    )


class PostgresUserStore(UserStore):
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def create(
        self,
        user_id: str,
        *,
        display_name: str | None = None,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> User:
        if not user_id or not user_id.strip():
            raise StoreError("user id cannot be empty")
        if user_id == SYSTEM_USER_ID:
            raise StoreError(f"user id {SYSTEM_USER_ID!r} is reserved")
        now = _utcnow()
        async with self._sessionmaker() as s, s.begin():
            existing = await s.get(UserRow, (workspace_id, user_id))
            if existing is not None:
                raise StoreError(
                    f"user {user_id!r} already exists in workspace {workspace_id!r}"
                )
            s.add(
                UserRow(
                    workspace_id=workspace_id,
                    id=user_id,
                    organization_id=organization_id,
                    display_name=display_name,
                    created_at=now,
                )
            )
        log.info("user.created", user_id=user_id, workspace_id=workspace_id)
        return User(
            id=user_id,
            display_name=display_name,
            roles=(),
            organization_id=organization_id,
            workspace_id=workspace_id,
            created_at=now,
        )

    async def get(
        self,
        user_id: str,
        *,
        workspace_id: str,
    ) -> User | None:
        async with self._sessionmaker() as s:
            row = await s.get(UserRow, (workspace_id, user_id))
            if row is None:
                return None
            role_rows = (
                (
                    await s.execute(
                        select(UserRoleRow)
                        .where(UserRoleRow.workspace_id == workspace_id)
                        .where(UserRoleRow.user_id == user_id)
                    )
                )
                .scalars()
                .all()
            )
        return _row_to_user(row, list(role_rows))

    async def list(
        self,
        *,
        workspace_id: str,
    ) -> builtins.list[User]:
        async with self._sessionmaker() as s:
            user_rows = (
                (
                    await s.execute(
                        select(UserRow)
                        .where(UserRow.workspace_id == workspace_id)
                        .order_by(UserRow.created_at)
                    )
                )
                .scalars()
                .all()
            )
            role_rows = (
                (
                    await s.execute(
                        select(UserRoleRow).where(
                            UserRoleRow.workspace_id == workspace_id
                        )
                    )
                )
                .scalars()
                .all()
            )
        roles_by_user: dict[str, list[UserRoleRow]] = {}
        for rr in role_rows:
            roles_by_user.setdefault(rr.user_id, []).append(rr)
        return [
            _row_to_user(row, roles_by_user.get(row.id, []))
            for row in user_rows
        ]

    async def update(
        self,
        user_id: str,
        *,
        workspace_id: str,
        display_name: str | None = None,
    ) -> User:
        async with self._sessionmaker() as s, s.begin():
            row = await s.get(UserRow, (workspace_id, user_id))
            if row is None:
                raise StoreError(
                    f"user {user_id!r} not found in workspace {workspace_id!r}"
                )
            if display_name is not None:
                row.display_name = display_name
            role_rows = (
                (
                    await s.execute(
                        select(UserRoleRow)
                        .where(UserRoleRow.workspace_id == workspace_id)
                        .where(UserRoleRow.user_id == user_id)
                    )
                )
                .scalars()
                .all()
            )
        return _row_to_user(row, list(role_rows))

    async def delete(
        self,
        user_id: str,
        *,
        workspace_id: str,
    ) -> None:
        async with self._sessionmaker() as s, s.begin():
            row = await s.get(UserRow, (workspace_id, user_id))
            if row is None:
                raise StoreError(
                    f"user {user_id!r} not found in workspace {workspace_id!r}"
                )
            # FK has ON DELETE CASCADE; explicit DELETE on user_roles
            # left here as defence-in-depth so removing the FK in a
            # future migration doesn't leak orphan bindings.
            await s.execute(
                delete(UserRoleRow)
                .where(UserRoleRow.workspace_id == workspace_id)
                .where(UserRoleRow.user_id == user_id)
            )
            await s.delete(row)

    async def assign_role(
        self,
        user_id: str,
        role: Role,
        *,
        workspace_id: str,
    ) -> None:
        async with self._sessionmaker() as s, s.begin():
            user = await s.get(UserRow, (workspace_id, user_id))
            if user is None:
                raise StoreError(
                    f"user {user_id!r} not found in workspace {workspace_id!r}"
                )
            existing = await s.get(
                UserRoleRow, (workspace_id, user_id, role.value)
            )
            if existing is not None:
                return
            s.add(
                UserRoleRow(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    role=role.value,
                    organization_id=user.organization_id,
                    created_at=_utcnow(),
                )
            )

    async def revoke_role(
        self,
        user_id: str,
        role: Role,
        *,
        workspace_id: str,
    ) -> None:
        async with self._sessionmaker() as s, s.begin():
            row = await s.get(UserRoleRow, (workspace_id, user_id, role.value))
            if row is None:
                return
            await s.delete(row)

    async def roles_for(
        self,
        user_id: str,
        *,
        workspace_id: str,
    ) -> builtins.list[Role]:
        async with self._sessionmaker() as s:
            rows = (
                (
                    await s.execute(
                        select(UserRoleRow)
                        .where(UserRoleRow.workspace_id == workspace_id)
                        .where(UserRoleRow.user_id == user_id)
                    )
                )
                .scalars()
                .all()
            )
        return _sorted_roles([Role.parse(r.role) for r in rows])


__all__ = ["PostgresUserStore"]
