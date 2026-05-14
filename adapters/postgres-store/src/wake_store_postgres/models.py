"""SQLAlchemy ORM models for the Postgres store.

The schema mirrors the SQLite reference store byte-for-byte at the
column level so that behavioural tests can be reused. Postgres-specific
additions (partitioning on ``events``, BRIN index on ``created_at``,
NOTIFY trigger) live in the Alembic migration rather than the ORM
metadata — SQLAlchemy's DDL emitter would happily create the table but
*without* a partition strategy, which would silently leave the cluster
unpartitioned. The migration is the source of truth for DDL; the ORM
is only used for SELECT/INSERT/UPDATE.

Design notes
------------
- Column types use Postgres-flavoured ``JSONB`` for payload/meta fields
  (better indexable than text JSON, opaque to the application).
- ULIDs are stored as ``String(26)`` to keep cross-backend compatibility
  with the SQLite store.
- ``created_at`` columns are timestamp-with-tz on Postgres because
  Postgres' timestamps are bigger than SQLite's and the round-trip cost
  is negligible.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from wake.tenancy import DEFAULT_ORGANIZATION_ID, DEFAULT_WORKSPACE_ID


class Base(DeclarativeBase):
    """Shared declarative base for all Postgres ORM rows."""


class AgentRow(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_ORGANIZATION_ID
    )
    workspace_id: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_WORKSPACE_ID, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentVersionRow(Base):
    __tablename__ = "agent_versions"

    agent_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    system: Mapped[str | None] = mapped_column(String, nullable=True)
    tools: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    mcp_servers: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    skills: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EnvironmentRow(Base):
    __tablename__ = "environments"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_ORGANIZATION_ID
    )
    workspace_id: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_WORKSPACE_ID, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SessionRow(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_ORGANIZATION_ID
    )
    workspace_id: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_WORKSPACE_ID, index=True
    )
    agent_id: Mapped[str] = mapped_column(String(26), nullable=False)
    agent_version: Mapped[int] = mapped_column(Integer, nullable=False)
    environment_id: Mapped[str | None] = mapped_column(String(26), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="idle")
    container_id: Mapped[str | None] = mapped_column(String, nullable=True)
    workspace_path: Mapped[str | None] = mapped_column(String, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EventRow(Base):
    """Events live on a HASH-partitioned parent table.

    The ORM treats ``events`` as a single table — SQLAlchemy is unaware
    of partitioning, which is what we want: queries route to the right
    partition automatically and INSERTs propagate via Postgres' built-in
    partition pruning. The migration creates the partitions.

    Per-partition primary key includes ``session_id`` (the partition
    key) so partition pruning works for ``SELECT ... WHERE id = ?``
    when ``session_id`` is also supplied. We additionally enforce
    global uniqueness of ``id`` at the application layer (ULIDs are
    statistically unique) since global unique constraints across
    HASH-partitioned tables require either a btree per partition or
    Postgres 16's experimental support.
    """

    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_ORGANIZATION_ID
    )
    workspace_id: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_WORKSPACE_ID, index=True
    )
    session_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    parent_id: Mapped[str | None] = mapped_column(String(26), nullable=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UserRow(Base):
    """Workspace-scoped user catalog.

    Composite primary key ``(workspace_id, id)`` so the same user id
    can coexist as independent principals across workspaces.
    """

    __tablename__ = "users"

    workspace_id: Mapped[str] = mapped_column(String, primary_key=True)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_ORGANIZATION_ID
    )
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UserRoleRow(Base):
    """Many-to-many ``(workspace, user, role)`` binding table."""

    __tablename__ = "user_roles"

    workspace_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    role: Mapped[str] = mapped_column(String, primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_ORGANIZATION_ID
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = [
    "Base",
    "AgentRow",
    "AgentVersionRow",
    "EnvironmentRow",
    "SessionRow",
    "EventRow",
    "UserRow",
    "UserRoleRow",
]
