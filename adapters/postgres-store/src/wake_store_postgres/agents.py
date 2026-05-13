"""PostgresAgentStore — versioned agent catalog.

Same versioning semantics as the SQLite reference store:

* ``create`` writes ``version = 1``.
* ``update`` content-hashes the merged config; if the hash matches the
  current version, the update is a no-op (returns the current).
  Otherwise a new version row is inserted and ``current_version`` bumps.
* ``archive`` sets ``archived_at`` on the parent agent row.

The implementation uses SQLAlchemy's async session for portability —
swapping for a hand-rolled asyncpg dialect would be marginally faster
but bring no behavioural benefit.
"""

# Public method parameter ``id`` matches the ABC contract.
# ruff: noqa: A002

from __future__ import annotations

import builtins
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from wake.store.base import AgentStore, StoreError
from wake.types import AgentConfig, McpServerConfig, ModelConfig, ToolConfig

from wake_store_postgres._helpers import content_hash, new_ulid, utcnow
from wake_store_postgres.models import AgentRow, AgentVersionRow

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# normalisation helpers — identical to SQLiteAgentStore
# ---------------------------------------------------------------------------


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


def _vrow_to_config(agent: AgentRow, v: AgentVersionRow) -> AgentConfig:
    return AgentConfig(
        id=agent.id,
        name=v.name,
        model=ModelConfig.model_validate(v.model),
        system=v.system,
        tools=[ToolConfig.model_validate(t) for t in v.tools],
        mcp_servers=[McpServerConfig.model_validate(m) for m in v.mcp_servers],
        skills=list(v.skills),
        description=v.description,
        metadata=dict(v.meta),
        version=v.version,
        created_at=agent.created_at,
        updated_at=v.created_at,
        archived_at=agent.archived_at,
    )


# ---------------------------------------------------------------------------
# PostgresAgentStore
# ---------------------------------------------------------------------------


class PostgresAgentStore(AgentStore):
    """Versioned agent catalog stored in Postgres."""

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
        chash = content_hash(content)
        now = utcnow()
        agent_id = new_ulid()
        async with self._sessionmaker() as s, s.begin():
            s.add(
                AgentRow(
                    id=agent_id,
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
        return AgentConfig(
            id=agent_id,
            name=name,
            model=model,
            system=system,
            tools=tools_norm,
            mcp_servers=mcp_norm,
            skills=skills_norm,
            description=description,
            metadata=meta_norm,
            version=1,
            created_at=now,
            updated_at=now,
            archived_at=None,
        )

    async def get(self, id: str, version: int | None = None) -> AgentConfig | None:
        async with self._sessionmaker() as s:
            agent = await s.get(AgentRow, id)
            if agent is None:
                return None
            target_version = version if version is not None else agent.current_version
            vrow = await s.get(AgentVersionRow, (id, target_version))
            if vrow is None:
                return None
            return _vrow_to_config(agent, vrow)

    async def update(self, id: str, **changes: Any) -> AgentConfig:
        async with self._sessionmaker() as s, s.begin():
            agent = await s.get(AgentRow, id)
            if agent is None:
                raise StoreError(f"agent {id!r} not found")
            current = await s.get(AgentVersionRow, (id, agent.current_version))
            if current is None:
                raise StoreError(f"agent {id!r} current version missing")
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
            new_hash = content_hash(new_payload)
            if new_hash == current.content_hash:
                log.info(
                    "agent.update.noop",
                    agent_id=id,
                    version=agent.current_version,
                )
                return _vrow_to_config(agent, current)
            new_version = agent.current_version + 1
            now = utcnow()
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
            new_row = await s.get(AgentVersionRow, (id, new_version))
            assert new_row is not None
            return _vrow_to_config(agent, new_row)

    async def list(self, *, include_archived: bool = False) -> builtins.list[AgentConfig]:
        async with self._sessionmaker() as s:
            stmt = select(AgentRow)
            if not include_archived:
                stmt = stmt.where(AgentRow.archived_at.is_(None))
            agents = (await s.execute(stmt.order_by(AgentRow.created_at))).scalars().all()
            out: builtins.list[AgentConfig] = []
            for a in agents:
                v = await s.get(AgentVersionRow, (a.id, a.current_version))
                if v is not None:
                    out.append(_vrow_to_config(a, v))
            return out

    async def list_versions(self, id: str) -> builtins.list[AgentConfig]:
        async with self._sessionmaker() as s:
            agent = await s.get(AgentRow, id)
            if agent is None:
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

    async def archive(self, id: str) -> AgentConfig:
        async with self._sessionmaker() as s, s.begin():
            agent = await s.get(AgentRow, id)
            if agent is None:
                raise StoreError(f"agent {id!r} not found")
            agent.archived_at = utcnow()
            vrow = await s.get(AgentVersionRow, (id, agent.current_version))
            assert vrow is not None
            log.info("agent.archived", agent_id=id)
            return _vrow_to_config(agent, vrow)


__all__ = ["PostgresAgentStore"]
