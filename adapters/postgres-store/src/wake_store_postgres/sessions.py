"""PostgresSessionStore — session lifecycle metadata."""

# Public method parameter ``id`` matches the ABC contract.
# ruff: noqa: A002

from __future__ import annotations

import builtins

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from wake.store.base import SessionStore, StoreError
from wake.tenancy import DEFAULT_ORGANIZATION_ID, DEFAULT_WORKSPACE_ID
from wake.types import Session, SessionStatus

from wake_store_postgres._helpers import new_ulid, utcnow
from wake_store_postgres.models import SessionRow

log = structlog.get_logger(__name__)


def _row_to_session(row: SessionRow) -> Session:
    return Session(
        id=row.id,
        organization_id=row.organization_id,
        workspace_id=row.workspace_id,
        agent_id=row.agent_id,
        agent_version=row.agent_version,
        environment_id=row.environment_id,
        status=row.status,  # type: ignore[arg-type]
        container_id=row.container_id,
        workspace_path=row.workspace_path,
        metadata=dict(row.meta),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class PostgresSessionStore(SessionStore):
    """Postgres-backed session lifecycle catalog."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def create(
        self,
        agent_id: str,
        agent_version: int,
        environment_id: str | None = None,
        metadata: dict[str, str] | None = None,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> Session:
        sid = new_ulid()
        now = utcnow()
        async with self._sessionmaker() as s, s.begin():
            s.add(
                SessionRow(
                    id=sid,
                    organization_id=organization_id,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    agent_version=agent_version,
                    environment_id=environment_id,
                    status="idle",
                    container_id=None,
                    workspace_path=None,
                    meta=dict(metadata or {}),
                    created_at=now,
                    updated_at=now,
                )
            )
        return Session(
            id=sid,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            agent_version=agent_version,
            environment_id=environment_id,
            status="idle",
            container_id=None,
            workspace_path=None,
            metadata=dict(metadata or {}),
            created_at=now,
            updated_at=now,
        )

    async def get(self, id: str, *, workspace_id: str | None = None) -> Session | None:
        async with self._sessionmaker() as s:
            row = await s.get(SessionRow, id)
            if row is not None and workspace_id is not None and row.workspace_id != workspace_id:
                return None
        return _row_to_session(row) if row else None

    async def list(
        self,
        *,
        status: SessionStatus | None = None,
        workspace_id: str | None = None,
    ) -> builtins.list[Session]:
        async with self._sessionmaker() as s:
            stmt = select(SessionRow).order_by(SessionRow.created_at)
            if workspace_id is not None:
                stmt = stmt.where(SessionRow.workspace_id == workspace_id)
            if status is not None:
                stmt = stmt.where(SessionRow.status == status)
            rows = (await s.execute(stmt)).scalars().all()
        return [_row_to_session(r) for r in rows]

    async def update_status(
        self, id: str, status: SessionStatus, *, workspace_id: str | None = None
    ) -> Session:
        async with self._sessionmaker() as s, s.begin():
            row = await s.get(SessionRow, id)
            if row is None or (workspace_id is not None and row.workspace_id != workspace_id):
                raise StoreError(f"session {id!r} not found")
            row.status = status
            row.updated_at = utcnow()
            return _row_to_session(row)

    async def set_container(
        self,
        id: str,
        container_id: str | None,
        workspace_path: str | None = None,
        workspace_id: str | None = None,
    ) -> Session:
        async with self._sessionmaker() as s, s.begin():
            row = await s.get(SessionRow, id)
            if row is None or (workspace_id is not None and row.workspace_id != workspace_id):
                raise StoreError(f"session {id!r} not found")
            row.container_id = container_id
            if workspace_path is not None:
                row.workspace_path = workspace_path
            row.updated_at = utcnow()
            return _row_to_session(row)

    async def delete(self, id: str, *, workspace_id: str | None = None) -> None:
        async with self._sessionmaker() as s, s.begin():
            row = await s.get(SessionRow, id)
            if row is None or (workspace_id is not None and row.workspace_id != workspace_id):
                raise StoreError(f"session {id!r} not found")
            await s.delete(row)


__all__ = ["PostgresSessionStore"]
