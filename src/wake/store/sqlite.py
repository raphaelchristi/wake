"""Default SQLite storage backend.

Provides ``SQLiteStore``, which bundles concrete implementations of the
four store interfaces against a single async SQLite database via
SQLAlchemy 2.x + aiosqlite.

Design notes
------------
- The schema mirrors ``docs/SPEC-EVENT-SCHEMA.md`` v0.1.0.
- Event ``seq`` is allocated atomically inside a transaction by reading
  the current MAX(seq) for the session and inserting MAX+1. SQLite
  serialises writes so this is safe; concurrent appends are queued.
- Agent versions are stored as separate rows in ``agent_versions``. The
  ``agents`` table holds only id/name/archived_at — version-specific
  fields live in ``agent_versions``.
- ``subscribe`` uses a 100ms polling loop. This is acceptable for Phase 1;
  Postgres backend (Phase 4) will use LISTEN/NOTIFY.
"""

# `id` shadows a builtin but the PHASE-1-CONTRACT mandates this parameter
# name on every store method.
# ruff: noqa: A002, TC003

from __future__ import annotations

import asyncio
import builtins
import hashlib
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
    select,
    text,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool
from ulid import ULID

from wake.rbac import Role, User
from wake.store.base import (
    AgentStore,
    EnvironmentStore,
    EventStore,
    SessionStore,
    StoreError,
    UserStore,
)
from wake.tenancy import DEFAULT_ORGANIZATION_ID, DEFAULT_WORKSPACE_ID
from wake.types import (
    AgentConfig,
    EnvironmentConfig,
    Event,
    EventType,
    McpServerConfig,
    ModelConfig,
    Session,
    SessionStatus,
    ToolConfig,
)

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


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
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AgentVersionRow(Base):
    __tablename__ = "agent_versions"

    agent_id: Mapped[str] = mapped_column(String(26), ForeignKey("agents.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    system: Mapped[str | None] = mapped_column(String, nullable=True)
    tools: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    mcp_servers: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    skills: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


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
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


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
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class UserRow(Base):
    __tablename__ = "users"

    # Composite primary key on (workspace_id, id) so the same user_id
    # can live in two workspaces as two independent principals.
    workspace_id: Mapped[str] = mapped_column(
        String, primary_key=True, default=DEFAULT_WORKSPACE_ID
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_ORGANIZATION_ID
    )
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class UserRoleRow(Base):
    __tablename__ = "user_roles"

    # Composite primary key — one row per (workspace, user, role).
    workspace_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    role: Mapped[str] = mapped_column(String, primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_ORGANIZATION_ID
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class EventRow(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_ORGANIZATION_ID
    )
    workspace_id: Mapped[str] = mapped_column(
        String, nullable=False, default=DEFAULT_WORKSPACE_ID, index=True
    )
    session_id: Mapped[str] = mapped_column(String(26), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    parent_id: Mapped[str | None] = mapped_column(String(26), nullable=True, index=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Phase 7 idempotency (Tier 1 gap #4): nullable column with a
    # UNIQUE partial index ``(workspace_id, session_id, idempotency_key)
    # WHERE idempotency_key IS NOT NULL`` installed in initialize().
    # NULL never collides — backward-compat with callers that do not
    # opt into dedupe.
    idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_ulid() -> str:
    return str(ULID())


def _utcnow() -> datetime:
    # SQLite stores naive datetimes; we standardise on UTC-naive for
    # round-trip stability and convert to aware UTC at the boundary.
    return datetime.now(UTC).replace(tzinfo=None)


def _aware(dt: datetime) -> datetime:
    """Return a UTC-aware datetime even if stored naive."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _content_hash(payload: dict[str, Any]) -> str:
    """Stable hash for agent versioning."""
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# Top-level SQLiteStore
# ---------------------------------------------------------------------------


class SQLiteStore:
    """Bundle of all four SQLite-backed stores sharing one engine.

    Usage::

        store = SQLiteStore("sqlite+aiosqlite:///./wake.db")
        await store.initialize()
        agent = await store.agents.create(name="x", model=ModelConfig(id="claude"))
    """

    def __init__(self, url: str = "sqlite+aiosqlite:///:memory:") -> None:
        self.url = url
        # In-memory SQLite is per-connection: a fresh connection sees an
        # empty database. We pin to a single connection via StaticPool so
        # all queries in a process share state. For file-backed URLs this
        # is harmless (still one connection at a time, serialised writes).
        engine_kwargs: dict[str, Any] = {"future": True}
        if ":memory:" in url:
            engine_kwargs["poolclass"] = StaticPool
            engine_kwargs["connect_args"] = {"check_same_thread": False}
        self.engine: AsyncEngine = create_async_engine(url, **engine_kwargs)
        self._sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)
        self.events: SQLiteEventStore = SQLiteEventStore(self._sessionmaker)
        self.agents: SQLiteAgentStore = SQLiteAgentStore(self._sessionmaker)
        self.environments: SQLiteEnvironmentStore = SQLiteEnvironmentStore(self._sessionmaker)
        self.sessions: SQLiteSessionStore = SQLiteSessionStore(self._sessionmaker)
        self.users: SQLiteUserStore = SQLiteUserStore(self._sessionmaker)

    async def initialize(self) -> None:
        """Create tables if they don't exist."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Recommended pragmas for SQLite durability + concurrency.
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.execute(text("PRAGMA foreign_keys=ON"))
            # Phase 7 idempotency (Tier 1 gap #4): UNIQUE partial
            # index on (workspace_id, session_id, idempotency_key).
            # SQLite 3.8+ supports partial indexes; Wake's minimum
            # SQLite (3.35+, for RETURNING) is comfortably ahead.
            await conn.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS
                        uq_events_idempotency
                        ON events (workspace_id, session_id, idempotency_key)
                        WHERE idempotency_key IS NOT NULL
                    """
                )
            )

    async def close(self) -> None:
        await self.engine.dispose()


# ---------------------------------------------------------------------------
# EventStore implementation
# ---------------------------------------------------------------------------


class SQLiteEventStore(EventStore):
    """SQLite-backed append-only event log."""

    # Polling interval for `subscribe`. Public so tests can override.
    poll_interval_s: float = 0.05

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker
        # Per-process notify primitive to short-circuit polling on append.
        # Each session gets its own asyncio.Event; created lazily.
        self._notifiers: dict[str, asyncio.Event] = {}
        # Per-session-id lock to serialise append: the (MAX(seq) + 1)
        # allocation pattern is only atomic if no other coroutine reads
        # MAX between our SELECT and INSERT. Cheap and bulletproof for
        # the single-process Phase 1 backend.
        self._append_locks: dict[str, asyncio.Lock] = {}

    def _notifier(self, session_id: str) -> asyncio.Event:
        ev = self._notifiers.get(session_id)
        if ev is None:
            ev = asyncio.Event()
            self._notifiers[session_id] = ev
        return ev

    def _append_lock(self, session_id: str) -> asyncio.Lock:
        lock = self._append_locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._append_locks[session_id] = lock
        return lock

    async def append(
        self,
        session_id: str,
        event_type: EventType,
        payload: dict[str, Any],
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
        *,
        idempotency_key: str | None = None,
    ) -> Event:
        now = _utcnow()
        event_id = _new_ulid()
        # Phase 7: mirror the dedupe key into metadata so the
        # persisted event carries the signal in plain sight. Stores
        # consumed via the bare EventStore API (not the EventLog
        # facade) get the same observability surface for free.
        meta_to_store = metadata
        if idempotency_key is not None:
            meta_to_store = dict(metadata or {})
            meta_to_store.setdefault("idempotency_key", idempotency_key)
        async with self._append_lock(session_id):
            # Phase 7 idempotency (Tier 1 gap #4): when the caller
            # supplies a key, check first for an existing row carrying
            # the same ``(workspace_id, session_id, idempotency_key)``
            # tuple. If found we return that event unchanged — the
            # UNIQUE partial index would reject the insert anyway, but
            # checking first lets us return the dedupe target without
            # surfacing IntegrityError to callers.
            if idempotency_key is not None:
                existing = await self._find_by_idempotency_key(
                    workspace_id=workspace_id,
                    session_id=session_id,
                    idempotency_key=idempotency_key,
                )
                if existing is not None:
                    log.debug(
                        "event.append.idempotent_dedupe",
                        session_id=session_id,
                        idempotency_key=idempotency_key,
                        existing_id=existing.id,
                    )
                    return existing
            async with self._sessionmaker() as s, s.begin():
                # Allocate next seq.
                current_max = await s.scalar(
                    select(func.max(EventRow.seq)).where(EventRow.session_id == session_id)
                )
                next_seq = 0 if current_max is None else int(current_max) + 1
                row = EventRow(
                    id=event_id,
                    organization_id=organization_id,
                    workspace_id=workspace_id,
                    session_id=session_id,
                    seq=next_seq,
                    type=event_type,
                    payload=payload,
                    parent_id=parent_id,
                    meta=meta_to_store,
                    idempotency_key=idempotency_key,
                    created_at=now,
                )
                s.add(row)
            log.debug(
                "event.appended",
                session_id=session_id,
                event_id=event_id,
                seq=next_seq,
                event_type=event_type,
            )
            # Wake subscribers.
            notifier = self._notifier(session_id)
            notifier.set()
            # Reset so future appends wake again. asyncio.Event must be
            # cleared *after* listeners react; we hand them a fresh one
            # by replacing the slot.
            self._notifiers[session_id] = asyncio.Event()
        return Event(
            id=event_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
            session_id=session_id,
            seq=next_seq,
            type=event_type,
            payload=payload,
            parent_id=parent_id,
            metadata=meta_to_store,
            created_at=_aware(now),
        )

    async def _find_by_idempotency_key(
        self,
        *,
        workspace_id: str,
        session_id: str,
        idempotency_key: str,
    ) -> Event | None:
        """Return the event carrying ``idempotency_key`` for the scope.

        Returns ``None`` when no prior event carries the key. Used by
        ``append`` to short-circuit duplicate writes.
        """
        async with self._sessionmaker() as s:
            stmt = (
                select(EventRow)
                .where(EventRow.workspace_id == workspace_id)
                .where(EventRow.session_id == session_id)
                .where(EventRow.idempotency_key == idempotency_key)
                .limit(1)
            )
            row = (await s.execute(stmt)).scalar_one_or_none()
        return _row_to_event(row) if row is not None else None

    async def get(
        self,
        session_id: str,
        since: int = 0,
        *,
        workspace_id: str | None = None,
    ) -> list[Event]:
        async with self._sessionmaker() as s:
            stmt = (
                select(EventRow)
                .where(EventRow.session_id == session_id)
                .where(EventRow.seq >= since)
            )
            if workspace_id is not None:
                stmt = stmt.where(EventRow.workspace_id == workspace_id)
            rows = (await s.execute(stmt.order_by(EventRow.seq))).scalars().all()
        return [_row_to_event(r) for r in rows]

    async def get_one(self, event_id: str, *, workspace_id: str | None = None) -> Event | None:
        async with self._sessionmaker() as s:
            stmt = select(EventRow).where(EventRow.id == event_id)
            if workspace_id is not None:
                stmt = stmt.where(EventRow.workspace_id == workspace_id)
            row = (await s.execute(stmt)).scalar_one_or_none()
        return _row_to_event(row) if row else None

    async def subscribe(
        self,
        session_id: str,
        since: int = 0,
        *,
        workspace_id: str | None = None,
    ) -> AsyncIterator[Event]:
        return self._subscribe_impl(session_id, since, workspace_id=workspace_id)

    async def _subscribe_impl(
        self, session_id: str, since: int, *, workspace_id: str | None
    ) -> AsyncIterator[Event]:
        cursor = since
        while True:
            backlog = await self.get(session_id, since=cursor, workspace_id=workspace_id)
            for ev in backlog:
                yield ev
                cursor = ev.seq + 1
            # Wait for next append or timeout (polling fallback for tests
            # that may not share the in-process notifier).
            notifier = self._notifier(session_id)
            try:
                await asyncio.wait_for(notifier.wait(), timeout=self.poll_interval_s)
            except TimeoutError:
                continue

    async def count(self, session_id: str, *, workspace_id: str | None = None) -> int:
        async with self._sessionmaker() as s:
            stmt = (
                select(func.count()).select_from(EventRow).where(EventRow.session_id == session_id)
            )
            if workspace_id is not None:
                stmt = stmt.where(EventRow.workspace_id == workspace_id)
            n = await s.scalar(stmt)
        return int(n or 0)


def _row_to_event(row: EventRow) -> Event:
    return Event(
        id=row.id,
        organization_id=row.organization_id,
        workspace_id=row.workspace_id,
        session_id=row.session_id,
        seq=row.seq,
        type=row.type,  # type: ignore[arg-type]
        payload=row.payload,
        parent_id=row.parent_id,
        metadata=row.meta,
        created_at=_aware(row.created_at),
    )


# ---------------------------------------------------------------------------
# AgentStore implementation
# ---------------------------------------------------------------------------


def _agent_content_payload(
    *,
    name: str,
    model: ModelConfig,
    system: str | None,
    tools: list[ToolConfig],
    mcp_servers: list[McpServerConfig],
    skills: list[dict[str, Any]],
    description: str | None,
    metadata: dict[str, str],
) -> dict[str, Any]:
    """Build the canonical dict used for content hashing."""
    return {
        "name": name,
        "model": model.model_dump(),
        "system": system,
        "tools": [t.model_dump() for t in tools],
        "mcp_servers": [m.model_dump() for m in mcp_servers],
        "skills": skills,
        "description": description,
        "metadata": metadata,
    }


def _normalise_tools(raw: list[Any] | None) -> list[ToolConfig]:
    if not raw:
        return []
    out: list[ToolConfig] = []
    for t in raw:
        if isinstance(t, ToolConfig):
            out.append(t)
        elif isinstance(t, dict):
            out.append(ToolConfig.model_validate(t))
        else:
            raise StoreError(f"unsupported tool entry: {type(t).__name__}")
    return out


def _normalise_mcp(raw: list[Any] | None) -> list[McpServerConfig]:
    if not raw:
        return []
    out: list[McpServerConfig] = []
    for m in raw:
        if isinstance(m, McpServerConfig):
            out.append(m)
        elif isinstance(m, dict):
            out.append(McpServerConfig.model_validate(m))
        else:
            raise StoreError(f"unsupported mcp entry: {type(m).__name__}")
    return out


def _normalise_model(raw: Any) -> ModelConfig:
    if isinstance(raw, ModelConfig):
        return raw
    if isinstance(raw, dict):
        return ModelConfig.model_validate(raw)
    raise StoreError(f"unsupported model entry: {type(raw).__name__}")


class SQLiteAgentStore(AgentStore):
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def create(
        self,
        name: str,
        model: ModelConfig,
        *,
        system: str | None = None,
        tools: list[Any] | None = None,
        mcp_servers: list[Any] | None = None,
        skills: list[dict[str, Any]] | None = None,
        description: str | None = None,
        metadata: dict[str, str] | None = None,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> AgentConfig:
        tools_norm = _normalise_tools(tools)
        mcp_norm = _normalise_mcp(mcp_servers)
        skills_norm = list(skills or [])
        meta_norm = dict(metadata or {})
        content = _agent_content_payload(
            name=name,
            model=model,
            system=system,
            tools=tools_norm,
            mcp_servers=mcp_norm,
            skills=skills_norm,
            description=description,
            metadata=meta_norm,
        )
        chash = _content_hash(content)
        now = _utcnow()
        agent_id = _new_ulid()
        async with self._sessionmaker() as s, s.begin():
            s.add(
                AgentRow(
                    id=agent_id,
                    organization_id=organization_id,
                    workspace_id=workspace_id,
                    name=name,
                    current_version=1,
                    created_at=now,
                    archived_at=None,
                )
            )
            s.add(
                AgentVersionRow(
                    agent_id=agent_id,
                    version=1,
                    name=name,
                    model=model.model_dump(),
                    system=system,
                    tools=[t.model_dump() for t in tools_norm],
                    mcp_servers=[m.model_dump() for m in mcp_norm],
                    skills=skills_norm,
                    description=description,
                    meta=meta_norm,
                    content_hash=chash,
                    created_at=now,
                )
            )
        log.info("agent.created", agent_id=agent_id, name=name)
        return _build_agent_config(
            agent_id=agent_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
            version=1,
            name=name,
            model=model,
            system=system,
            tools=tools_norm,
            mcp_servers=mcp_norm,
            skills=skills_norm,
            description=description,
            metadata=meta_norm,
            created_at=now,
            updated_at=now,
            archived_at=None,
        )

    async def get(
        self,
        id: str,
        version: int | None = None,
        *,
        workspace_id: str | None = None,
    ) -> AgentConfig | None:
        async with self._sessionmaker() as s:
            agent = await s.get(AgentRow, id)
            if agent is None:
                return None
            if workspace_id is not None and agent.workspace_id != workspace_id:
                return None
            target_version = version if version is not None else agent.current_version
            vrow = await s.get(AgentVersionRow, (id, target_version))
            if vrow is None:
                return None
            return _vrow_to_config(agent, vrow)

    async def update(
        self, id: str, *, workspace_id: str | None = None, **changes: Any
    ) -> AgentConfig:
        async with self._sessionmaker() as s, s.begin():
            agent = await s.get(AgentRow, id)
            if agent is None or (workspace_id is not None and agent.workspace_id != workspace_id):
                raise StoreError(f"agent {id!r} not found")
            current = await s.get(AgentVersionRow, (id, agent.current_version))
            if current is None:
                raise StoreError(f"agent {id!r} current version missing")
            # Build merged content.
            merged_tools = _normalise_tools(changes.get("tools", current.tools))
            merged_mcp = _normalise_mcp(changes.get("mcp_servers", current.mcp_servers))
            merged_model = _normalise_model(changes.get("model", current.model))
            merged = {
                "name": changes.get("name", current.name),
                "model": merged_model,
                "system": changes.get("system", current.system),
                "tools": merged_tools,
                "mcp_servers": merged_mcp,
                "skills": changes.get("skills", current.skills),
                "description": changes.get("description", current.description),
                "metadata": changes.get("metadata", current.meta),
            }
            new_payload = _agent_content_payload(
                name=merged["name"],
                model=merged["model"],
                system=merged["system"],
                tools=merged["tools"],
                mcp_servers=merged["mcp_servers"],
                skills=merged["skills"],
                description=merged["description"],
                metadata=merged["metadata"],
            )
            new_hash = _content_hash(new_payload)
            if new_hash == current.content_hash:
                # No-op: return existing version.
                log.info("agent.update.noop", agent_id=id, version=agent.current_version)
                return _vrow_to_config(agent, current)
            new_version = agent.current_version + 1
            now = _utcnow()
            s.add(
                AgentVersionRow(
                    agent_id=id,
                    version=new_version,
                    name=merged["name"],
                    model=merged["model"].model_dump(),
                    system=merged["system"],
                    tools=[t.model_dump() for t in merged["tools"]],
                    mcp_servers=[m.model_dump() for m in merged["mcp_servers"]],
                    skills=list(merged["skills"]),
                    description=merged["description"],
                    meta=dict(merged["metadata"]),
                    content_hash=new_hash,
                    created_at=now,
                )
            )
            agent.current_version = new_version
            agent.name = merged["name"]
            log.info("agent.updated", agent_id=id, version=new_version)
            # Need to fetch refreshed version row for return value.
            new_row = await s.get(AgentVersionRow, (id, new_version))
            assert new_row is not None
            return _vrow_to_config(agent, new_row)

    async def list(
        self, *, include_archived: bool = False, workspace_id: str | None = None
    ) -> builtins.list[AgentConfig]:
        async with self._sessionmaker() as s:
            stmt = select(AgentRow)
            if workspace_id is not None:
                stmt = stmt.where(AgentRow.workspace_id == workspace_id)
            if not include_archived:
                stmt = stmt.where(AgentRow.archived_at.is_(None))
            agents = (await s.execute(stmt.order_by(AgentRow.created_at))).scalars().all()
            out: builtins.list[AgentConfig] = []
            for a in agents:
                v = await s.get(AgentVersionRow, (a.id, a.current_version))
                if v is not None:
                    out.append(_vrow_to_config(a, v))
            return out

    async def list_versions(
        self, id: str, *, workspace_id: str | None = None
    ) -> builtins.list[AgentConfig]:
        async with self._sessionmaker() as s:
            agent = await s.get(AgentRow, id)
            if agent is None:
                return []
            if workspace_id is not None and agent.workspace_id != workspace_id:
                return []
            rows = (
                (
                    await s.execute(
                        select(AgentVersionRow)
                        .where(AgentVersionRow.agent_id == id)
                        .order_by(AgentVersionRow.version)
                    )
                )
                .scalars()
                .all()
            )
            return [_vrow_to_config(agent, r) for r in rows]

    async def archive(self, id: str, *, workspace_id: str | None = None) -> AgentConfig:
        async with self._sessionmaker() as s, s.begin():
            agent = await s.get(AgentRow, id)
            if agent is None or (workspace_id is not None and agent.workspace_id != workspace_id):
                raise StoreError(f"agent {id!r} not found")
            agent.archived_at = _utcnow()
            vrow = await s.get(AgentVersionRow, (id, agent.current_version))
            assert vrow is not None
            log.info("agent.archived", agent_id=id)
            return _vrow_to_config(agent, vrow)


def _vrow_to_config(agent: AgentRow, v: AgentVersionRow) -> AgentConfig:
    return _build_agent_config(
        agent_id=agent.id,
        organization_id=agent.organization_id,
        workspace_id=agent.workspace_id,
        version=v.version,
        name=v.name,
        model=ModelConfig.model_validate(v.model),
        system=v.system,
        tools=[ToolConfig.model_validate(t) for t in v.tools],
        mcp_servers=[McpServerConfig.model_validate(m) for m in v.mcp_servers],
        skills=list(v.skills),
        description=v.description,
        metadata=dict(v.meta),
        created_at=agent.created_at,
        updated_at=v.created_at,
        archived_at=agent.archived_at,
    )


def _build_agent_config(
    *,
    agent_id: str,
    organization_id: str,
    workspace_id: str,
    version: int,
    name: str,
    model: ModelConfig,
    system: str | None,
    tools: list[ToolConfig],
    mcp_servers: list[McpServerConfig],
    skills: list[dict[str, Any]],
    description: str | None,
    metadata: dict[str, str],
    created_at: datetime,
    updated_at: datetime,
    archived_at: datetime | None,
) -> AgentConfig:
    return AgentConfig(
        id=agent_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        name=name,
        model=model,
        system=system,
        tools=tools,
        mcp_servers=mcp_servers,
        skills=skills,
        description=description,
        metadata=metadata,
        version=version,
        created_at=_aware(created_at),
        updated_at=_aware(updated_at),
        archived_at=_aware(archived_at) if archived_at else None,
    )


# ---------------------------------------------------------------------------
# EnvironmentStore implementation
# ---------------------------------------------------------------------------


class SQLiteEnvironmentStore(EnvironmentStore):
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
        env_id = _new_ulid()
        now = _utcnow()
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
            created_at=_aware(now),
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
            row.archived_at = _utcnow()
            return _row_to_env(row)

    async def delete(self, id: str, *, workspace_id: str | None = None) -> None:
        async with self._sessionmaker() as s, s.begin():
            row = await s.get(EnvironmentRow, id)
            if row is None or (workspace_id is not None and row.workspace_id != workspace_id):
                raise StoreError(f"environment {id!r} not found")
            await s.delete(row)


def _row_to_env(row: EnvironmentRow) -> EnvironmentConfig:
    return EnvironmentConfig(
        id=row.id,
        organization_id=row.organization_id,
        workspace_id=row.workspace_id,
        name=row.name,
        config=dict(row.config),
        created_at=_aware(row.created_at),
        archived_at=_aware(row.archived_at) if row.archived_at else None,
    )


# ---------------------------------------------------------------------------
# SessionStore implementation
# ---------------------------------------------------------------------------


class SQLiteSessionStore(SessionStore):
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
        sid = _new_ulid()
        now = _utcnow()
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
            created_at=_aware(now),
            updated_at=_aware(now),
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
            row.updated_at = _utcnow()
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
            row.updated_at = _utcnow()
            return _row_to_session(row)

    async def delete(self, id: str, *, workspace_id: str | None = None) -> None:
        async with self._sessionmaker() as s, s.begin():
            row = await s.get(SessionRow, id)
            if row is None or (workspace_id is not None and row.workspace_id != workspace_id):
                raise StoreError(f"session {id!r} not found")
            await s.delete(row)


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
        created_at=_aware(row.created_at),
        updated_at=_aware(row.updated_at),
    )


# ---------------------------------------------------------------------------
# UserStore implementation
# ---------------------------------------------------------------------------


# ``SYSTEM_USER_ID`` is reserved: the in-memory sentinel produced by
# ``User.system()``. Persisting it would shadow the disabled-RBAC
# fallback identity and lead to confusing audit trails.
SYSTEM_USER_ID = "system"


class SQLiteUserStore(UserStore):
    """SQLite-backed user + workspace-role catalog."""

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
        log.info(
            "user.created",
            user_id=user_id,
            workspace_id=workspace_id,
        )
        return User(
            id=user_id,
            display_name=display_name,
            roles=(),
            organization_id=organization_id,
            workspace_id=workspace_id,
            created_at=_aware(now),
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
            # Fetch every role row for the workspace in one shot then
            # bucket per user_id — avoids an N+1 query per user.
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
            # Cascade roles by hand — keeping the schema portable
            # (SQLite + Postgres) without relying on ON DELETE CASCADE.
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
            for rr in role_rows:
                await s.delete(rr)
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
                return  # idempotent
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
                return  # idempotent
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


def _row_to_user(row: UserRow, role_rows: list[UserRoleRow]) -> User:
    roles = _sorted_roles(
        [Role.parse(r.role) for r in role_rows if r.user_id == row.id]
    )
    return User(
        id=row.id,
        display_name=row.display_name,
        roles=tuple(roles),
        organization_id=row.organization_id,
        workspace_id=row.workspace_id,
        created_at=_aware(row.created_at),
    )


def _sorted_roles(roles: builtins.list[Role]) -> builtins.list[Role]:
    """Stable role ordering: matches Enum declaration order."""
    order = {r: i for i, r in enumerate(Role)}
    # De-dup defensively (idempotent assign protects but defensive
    # ordering keeps tests deterministic even with bad data).
    return sorted(set(roles), key=lambda r: order[r])
