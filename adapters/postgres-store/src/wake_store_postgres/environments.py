"""PostgresEnvironmentStore — environments catalog (no versioning)."""

# Public method parameter ``id`` matches the ABC contract.
# ruff: noqa: A002

from __future__ import annotations

import builtins
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from wake.store.base import EnvironmentStore, StoreError
from wake.tenancy import DEFAULT_ORGANIZATION_ID, DEFAULT_WORKSPACE_ID
from wake.types import EnvironmentConfig

from wake_store_postgres._helpers import new_ulid, utcnow
from wake_store_postgres.models import EnvironmentRow

log = structlog.get_logger(__name__)


def _row_to_env(row: EnvironmentRow) -> EnvironmentConfig:
    return EnvironmentConfig(
        id=row.id,
        organization_id=row.organization_id,
        workspace_id=row.workspace_id,
        name=row.name,
        config=dict(row.config),
        created_at=row.created_at,
        archived_at=row.archived_at,
    )


class PostgresEnvironmentStore(EnvironmentStore):
    """Postgres-backed environment catalog."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def create(
        self,
        name: str,
        config: dict[str, Any],
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> EnvironmentConfig:
        env_id = new_ulid()
        now = utcnow()
        async with self._sessionmaker() as s, s.begin():
            s.add(
                EnvironmentRow(
                    id=env_id,
                    organization_id=organization_id,
                    workspace_id=workspace_id,
                    name=name,
                    config=config,
                    created_at=now,
                    archived_at=None,
                )
            )
        return EnvironmentConfig(
            id=env_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
            name=name,
            config=config,
            created_at=now,
            archived_at=None,
        )

    async def get(self, id: str, *, workspace_id: str | None = None) -> EnvironmentConfig | None:
        async with self._sessionmaker() as s:
            row = await s.get(EnvironmentRow, id)
            if row is not None and workspace_id is not None and row.workspace_id != workspace_id:
                return None
        return _row_to_env(row) if row else None

    async def list(
        self, *, include_archived: bool = False, workspace_id: str | None = None
    ) -> builtins.list[EnvironmentConfig]:
        async with self._sessionmaker() as s:
            stmt = select(EnvironmentRow).order_by(EnvironmentRow.created_at)
            if workspace_id is not None:
                stmt = stmt.where(EnvironmentRow.workspace_id == workspace_id)
            if not include_archived:
                stmt = stmt.where(EnvironmentRow.archived_at.is_(None))
            rows = (await s.execute(stmt)).scalars().all()
        return [_row_to_env(r) for r in rows]

    async def archive(self, id: str, *, workspace_id: str | None = None) -> EnvironmentConfig:
        async with self._sessionmaker() as s, s.begin():
            row = await s.get(EnvironmentRow, id)
            if row is None or (workspace_id is not None and row.workspace_id != workspace_id):
                raise StoreError(f"environment {id!r} not found")
            row.archived_at = utcnow()
            return _row_to_env(row)

    async def delete(self, id: str, *, workspace_id: str | None = None) -> None:
        async with self._sessionmaker() as s, s.begin():
            row = await s.get(EnvironmentRow, id)
            if row is None or (workspace_id is not None and row.workspace_id != workspace_id):
                raise StoreError(f"environment {id!r} not found")
            await s.delete(row)


__all__ = ["PostgresEnvironmentStore"]
