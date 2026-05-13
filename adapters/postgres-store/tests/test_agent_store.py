"""Behavioural tests for PostgresAgentStore — mirrors SQLite store suite."""

from __future__ import annotations

from typing import Any

import pytest
from wake.store.base import StoreError
from wake.types import McpServerConfig, ModelConfig, ToolConfig

pytestmark = pytest.mark.asyncio


async def test_agent_create_get(store: Any) -> None:
    agent = await store.agents.create(name="bot", model=ModelConfig(id="claude-opus-4-7"))
    assert agent.version == 1
    assert agent.archived_at is None
    fetched = await store.agents.get(agent.id)
    assert fetched is not None and fetched.id == agent.id


async def test_agent_update_noop_returns_same_version(store: Any) -> None:
    agent = await store.agents.create(
        name="bot",
        model=ModelConfig(id="claude"),
        system="be helpful",
        tools=[ToolConfig(type="bash")],
    )
    same = await store.agents.update(agent.id, name="bot")
    assert same.version == 1
    same2 = await store.agents.update(
        agent.id, system="be helpful", tools=[ToolConfig(type="bash")]
    )
    assert same2.version == 1


async def test_agent_update_creates_new_version(store: Any) -> None:
    agent = await store.agents.create(name="bot", model=ModelConfig(id="claude"))
    v2 = await store.agents.update(agent.id, system="new prompt")
    assert v2.version == 2
    v3 = await store.agents.update(agent.id, tools=[ToolConfig(type="bash")])
    assert v3.version == 3
    versions = await store.agents.list_versions(agent.id)
    assert [v.version for v in versions] == [1, 2, 3]


async def test_agent_get_specific_version(store: Any) -> None:
    agent = await store.agents.create(name="bot", model=ModelConfig(id="claude"))
    await store.agents.update(agent.id, system="v2 prompt")
    v1 = await store.agents.get(agent.id, version=1)
    assert v1 is not None and v1.system is None
    latest = await store.agents.get(agent.id)
    assert latest is not None and latest.version == 2


async def test_agent_archive_sets_archived_at(store: Any) -> None:
    agent = await store.agents.create(name="bot", model=ModelConfig(id="claude"))
    archived = await store.agents.archive(agent.id)
    assert archived.archived_at is not None


async def test_agent_list_excludes_archived_by_default(store: Any) -> None:
    a = await store.agents.create(name="a", model=ModelConfig(id="c"))
    b = await store.agents.create(name="b", model=ModelConfig(id="c"))
    await store.agents.archive(a.id)
    visible = await store.agents.list()
    assert {x.id for x in visible} == {b.id}
    all_ = await store.agents.list(include_archived=True)
    assert {x.id for x in all_} == {a.id, b.id}


async def test_agent_with_mcp_servers(store: Any) -> None:
    mcp = McpServerConfig(name="fs", transport="stdio", command="server")
    agent = await store.agents.create(name="bot", model=ModelConfig(id="c"), mcp_servers=[mcp])
    assert len(agent.mcp_servers) == 1 and agent.mcp_servers[0].name == "fs"


async def test_agent_update_missing_raises(store: Any) -> None:
    with pytest.raises(StoreError):
        await store.agents.update("missing", name="x")


async def test_agent_archive_missing_raises(store: Any) -> None:
    with pytest.raises(StoreError):
        await store.agents.archive("missing")
