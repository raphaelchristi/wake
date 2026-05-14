"""Tests for SQLite store implementations.

Covers:
- Agents: create, get, update (no-op + new version), list_versions, archive
- Environments: CRUD + archive + delete
- Sessions: create, status update, container metadata, list filter
"""

from __future__ import annotations

import os
import tempfile

import pytest

from wake.store import SQLiteStore
from wake.store.base import StoreError
from wake.types import McpServerConfig, ModelConfig, ToolConfig


@pytest.fixture
async def store() -> SQLiteStore:
    # File-backed temp DB — in-memory SQLite has poor concurrent
    # visibility semantics via aiosqlite even with StaticPool.
    fd, path = tempfile.mkstemp(suffix=".db", prefix="wake-test-")
    os.close(fd)
    s = SQLiteStore(f"sqlite+aiosqlite:///{path}")
    await s.initialize()
    try:
        yield s
    finally:
        await s.close()
        os.unlink(path)


# -------------------------------------------------------------------- Agents


async def test_agent_create_get(store: SQLiteStore) -> None:
    agent = await store.agents.create(name="bot", model=ModelConfig(id="claude-opus-4-7"))
    assert agent.version == 1
    assert agent.archived_at is None
    fetched = await store.agents.get(agent.id)
    assert fetched is not None and fetched.id == agent.id


async def test_agent_update_noop_returns_same_version(store: SQLiteStore) -> None:
    agent = await store.agents.create(
        name="bot",
        model=ModelConfig(id="claude"),
        system="be helpful",
        tools=[ToolConfig(type="bash")],
    )
    same = await store.agents.update(agent.id, name="bot")
    assert same.version == 1, "no actual change must not bump version"
    same2 = await store.agents.update(
        agent.id, system="be helpful", tools=[ToolConfig(type="bash")]
    )
    assert same2.version == 1


async def test_agent_update_creates_new_version(store: SQLiteStore) -> None:
    agent = await store.agents.create(name="bot", model=ModelConfig(id="claude"))
    v2 = await store.agents.update(agent.id, system="new prompt")
    assert v2.version == 2
    v3 = await store.agents.update(agent.id, tools=[ToolConfig(type="bash")])
    assert v3.version == 3
    versions = await store.agents.list_versions(agent.id)
    assert [v.version for v in versions] == [1, 2, 3]


async def test_agent_get_specific_version(store: SQLiteStore) -> None:
    agent = await store.agents.create(name="bot", model=ModelConfig(id="claude"))
    await store.agents.update(agent.id, system="v2 prompt")
    v1 = await store.agents.get(agent.id, version=1)
    assert v1 is not None and v1.system is None
    latest = await store.agents.get(agent.id)
    assert latest is not None and latest.version == 2


async def test_agent_archive_sets_archived_at(store: SQLiteStore) -> None:
    agent = await store.agents.create(name="bot", model=ModelConfig(id="claude"))
    archived = await store.agents.archive(agent.id)
    assert archived.archived_at is not None


async def test_agent_list_excludes_archived_by_default(store: SQLiteStore) -> None:
    a = await store.agents.create(name="a", model=ModelConfig(id="c"))
    b = await store.agents.create(name="b", model=ModelConfig(id="c"))
    await store.agents.archive(a.id)
    visible = await store.agents.list()
    assert {x.id for x in visible} == {b.id}
    all_ = await store.agents.list(include_archived=True)
    assert {x.id for x in all_} == {a.id, b.id}


async def test_agent_store_filters_by_workspace(store: SQLiteStore) -> None:
    a = await store.agents.create(
        name="a",
        model=ModelConfig(id="c"),
        organization_id="org",
        workspace_id="workspace_a",
    )
    b = await store.agents.create(
        name="b",
        model=ModelConfig(id="c"),
        organization_id="org",
        workspace_id="workspace_b",
    )

    assert (await store.agents.get(a.id, workspace_id="workspace_a")) is not None
    assert await store.agents.get(a.id, workspace_id="workspace_b") is None
    visible = await store.agents.list(workspace_id="workspace_a")
    assert [agent.id for agent in visible] == [a.id]
    assert (await store.agents.update(a.id, workspace_id="workspace_a", system="x")).version == 2
    with pytest.raises(StoreError):
        await store.agents.update(a.id, workspace_id="workspace_b", system="hidden")
    assert await store.agents.list_versions(b.id, workspace_id="workspace_a") == []


async def test_agent_with_mcp_servers(store: SQLiteStore) -> None:
    mcp = McpServerConfig(name="fs", transport="stdio", command="server")
    agent = await store.agents.create(name="bot", model=ModelConfig(id="c"), mcp_servers=[mcp])
    assert len(agent.mcp_servers) == 1 and agent.mcp_servers[0].name == "fs"


# --------------------------------------------------------------- Environments


async def test_environment_crud(store: SQLiteStore) -> None:
    env = await store.environments.create(name="default", config={"sandbox": {"backend": "docker"}})
    fetched = await store.environments.get(env.id)
    assert fetched is not None and fetched.name == "default"
    listed = await store.environments.list()
    assert len(listed) == 1
    await store.environments.archive(env.id)
    visible = await store.environments.list()
    assert visible == []
    archived = await store.environments.list(include_archived=True)
    assert archived[0].archived_at is not None
    await store.environments.delete(env.id)
    assert await store.environments.get(env.id) is None


async def test_environment_delete_missing_raises(store: SQLiteStore) -> None:
    with pytest.raises(StoreError):
        await store.environments.delete("does-not-exist")


# -------------------------------------------------------------------- Sessions


async def test_session_create_default_idle(store: SQLiteStore) -> None:
    s = await store.sessions.create(agent_id="ag", agent_version=1)
    assert s.status == "idle"
    assert s.container_id is None


async def test_session_update_status(store: SQLiteStore) -> None:
    s = await store.sessions.create(agent_id="ag", agent_version=1)
    running = await store.sessions.update_status(s.id, "running")
    assert running.status == "running"


async def test_session_set_container(store: SQLiteStore) -> None:
    s = await store.sessions.create(agent_id="ag", agent_version=1)
    updated = await store.sessions.set_container(s.id, container_id="ctn_123", workspace_path="/w")
    assert updated.container_id == "ctn_123"
    assert updated.workspace_path == "/w"


async def test_session_list_by_status(store: SQLiteStore) -> None:
    s1 = await store.sessions.create(agent_id="ag", agent_version=1)
    s2 = await store.sessions.create(agent_id="ag", agent_version=1)
    await store.sessions.update_status(s2.id, "running")
    idle_only = await store.sessions.list(status="idle")
    assert {x.id for x in idle_only} == {s1.id}
    running_only = await store.sessions.list(status="running")
    assert {x.id for x in running_only} == {s2.id}


async def test_session_store_filters_by_workspace(store: SQLiteStore) -> None:
    a = await store.sessions.create(
        agent_id="ag",
        agent_version=1,
        organization_id="org",
        workspace_id="workspace_a",
    )
    await store.sessions.create(
        agent_id="ag",
        agent_version=1,
        organization_id="org",
        workspace_id="workspace_b",
    )

    assert (await store.sessions.get(a.id, workspace_id="workspace_a")) is not None
    assert await store.sessions.get(a.id, workspace_id="workspace_b") is None
    visible = await store.sessions.list(workspace_id="workspace_a")
    assert [session.id for session in visible] == [a.id]
    assert (
        await store.sessions.update_status(
            a.id,
            "running",
            workspace_id="workspace_a",
        )
    ).status == "running"
    with pytest.raises(StoreError):
        await store.sessions.update_status(
            a.id,
            "idle",
            workspace_id="workspace_b",
        )


async def test_session_delete(store: SQLiteStore) -> None:
    s = await store.sessions.create(agent_id="ag", agent_version=1)
    await store.sessions.delete(s.id)
    assert await store.sessions.get(s.id) is None


async def test_missing_session_status_update_raises(store: SQLiteStore) -> None:
    with pytest.raises(StoreError):
        await store.sessions.update_status("nope", "running")


async def test_agent_update_missing_raises(store: SQLiteStore) -> None:
    with pytest.raises(StoreError):
        await store.agents.update("missing", name="x")


async def test_agent_archive_missing_raises(store: SQLiteStore) -> None:
    with pytest.raises(StoreError):
        await store.agents.archive("missing")


# -------------------------------------------- AgentService / EnvironmentService


async def test_agent_service_create_with_string_model(store: SQLiteStore) -> None:
    from wake.core.agent import AgentService

    svc = AgentService(store.agents)
    agent = await svc.create(name="bot", model="claude-opus-4-7")
    assert agent.model.id == "claude-opus-4-7"
    assert agent.model.provider == "anthropic"


async def test_agent_service_create_with_dict_model(store: SQLiteStore) -> None:
    from wake.core.agent import AgentService

    svc = AgentService(store.agents)
    agent = await svc.create(
        name="bot",
        model={"id": "claude", "provider": "anthropic", "speed": "fast"},
    )
    assert agent.model.speed == "fast"


async def test_agent_service_update_archive_list(store: SQLiteStore) -> None:
    from wake.core.agent import AgentService

    svc = AgentService(store.agents)
    a = await svc.create(name="bot", model=ModelConfig(id="c"))
    v2 = await svc.update(a.id, model="claude-haiku")
    assert v2.version == 2 and v2.model.id == "claude-haiku"
    versions = await svc.list_versions(a.id)
    assert len(versions) == 2
    fetched = await svc.get(a.id, version=1)
    assert fetched is not None and fetched.version == 1
    listed = await svc.list()
    assert any(x.id == a.id for x in listed)
    archived = await svc.archive(a.id)
    assert archived.archived_at is not None


async def test_environment_service_facade(store: SQLiteStore) -> None:
    from wake.core.environment import EnvironmentService

    svc = EnvironmentService(store.environments)
    env = await svc.create("e", {"backend": "docker"})
    assert env.config == {"backend": "docker"}
    listed = await svc.list()
    assert len(listed) == 1
    fetched = await svc.get(env.id)
    assert fetched is not None
    archived = await svc.archive(env.id)
    assert archived.archived_at is not None
    archived_listed = await svc.list(include_archived=True)
    assert len(archived_listed) == 1
    await svc.delete(env.id)
    assert await svc.get(env.id) is None


async def test_environment_service_empty_config_default(store: SQLiteStore) -> None:
    from wake.core.environment import EnvironmentService

    svc = EnvironmentService(store.environments)
    env = await svc.create("e")
    assert env.config == {}
