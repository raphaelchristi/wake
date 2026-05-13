"""Tests for agent CRUD routes."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    res = await client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "components" in body


@pytest.mark.asyncio
async def test_create_agent(client: AsyncClient) -> None:
    res = await client.post(
        "/v1/agents",
        json={
            "name": "test",
            "model": {"id": "claude-opus-4-7"},
            "system": "be helpful",
            "tools": [{"type": "bash"}],
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["name"] == "test"
    assert body["model"]["id"] == "claude-opus-4-7"
    assert body["version"] == 1
    assert body["id"].startswith("agent_")


@pytest.mark.asyncio
async def test_list_agents(client: AsyncClient) -> None:
    await client.post(
        "/v1/agents",
        json={"name": "a", "model": {"id": "claude-opus-4-7"}},
    )
    await client.post(
        "/v1/agents",
        json={"name": "b", "model": {"id": "claude-opus-4-7"}},
    )
    res = await client.get("/v1/agents")
    assert res.status_code == 200
    body = res.json()
    assert len(body["data"]) == 2


@pytest.mark.asyncio
async def test_get_agent_not_found(client: AsyncClient) -> None:
    res = await client.get("/v1/agents/missing")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_update_agent_bumps_version(client: AsyncClient) -> None:
    created = (
        await client.post(
            "/v1/agents",
            json={"name": "x", "model": {"id": "claude-opus-4-7"}},
        )
    ).json()
    res = await client.patch(
        f"/v1/agents/{created['id']}",
        json={"system": "new prompt"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["version"] == 2
    assert body["system"] == "new prompt"


@pytest.mark.asyncio
async def test_archive_agent(client: AsyncClient) -> None:
    created = (
        await client.post(
            "/v1/agents",
            json={"name": "x", "model": {"id": "claude-opus-4-7"}},
        )
    ).json()
    res = await client.post(f"/v1/agents/{created['id']}/archive")
    assert res.status_code == 200
    assert res.json()["archived_at"] is not None


@pytest.mark.asyncio
async def test_list_agent_versions(client: AsyncClient) -> None:
    created = (
        await client.post(
            "/v1/agents",
            json={"name": "x", "model": {"id": "claude-opus-4-7"}},
        )
    ).json()
    await client.patch(
        f"/v1/agents/{created['id']}", json={"system": "v2"}
    )
    await client.patch(
        f"/v1/agents/{created['id']}", json={"system": "v3"}
    )
    res = await client.get(f"/v1/agents/{created['id']}/versions")
    assert res.status_code == 200
    body = res.json()
    assert len(body["data"]) == 3
    assert [a["version"] for a in body["data"]] == [1, 2, 3]


@pytest.mark.asyncio
async def test_update_unknown_agent(client: AsyncClient) -> None:
    res = await client.patch("/v1/agents/missing", json={"system": "x"})
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_archive_unknown_agent(client: AsyncClient) -> None:
    res = await client.post("/v1/agents/missing/archive")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_versions_unknown_agent(client: AsyncClient) -> None:
    res = await client.get("/v1/agents/missing/versions")
    assert res.status_code == 404
