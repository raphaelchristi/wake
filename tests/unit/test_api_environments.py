"""Tests for environment CRUD routes."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_environment(client: AsyncClient) -> None:
    res = await client.post(
        "/v1/environments",
        json={"name": "default", "config": {"image": "python:3.12-slim"}},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["name"] == "default"
    assert body["config"]["image"] == "python:3.12-slim"


@pytest.mark.asyncio
async def test_list_environments(client: AsyncClient) -> None:
    await client.post("/v1/environments", json={"name": "a", "config": {}})
    await client.post("/v1/environments", json={"name": "b", "config": {}})
    res = await client.get("/v1/environments")
    assert res.status_code == 200
    assert len(res.json()["data"]) == 2


@pytest.mark.asyncio
async def test_get_environment(client: AsyncClient) -> None:
    created = (
        await client.post("/v1/environments", json={"name": "x", "config": {}})
    ).json()
    res = await client.get(f"/v1/environments/{created['id']}")
    assert res.status_code == 200
    assert res.json()["id"] == created["id"]


@pytest.mark.asyncio
async def test_get_unknown_environment(client: AsyncClient) -> None:
    res = await client.get("/v1/environments/missing")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_archive_environment(client: AsyncClient) -> None:
    created = (
        await client.post("/v1/environments", json={"name": "x", "config": {}})
    ).json()
    res = await client.post(f"/v1/environments/{created['id']}/archive")
    assert res.status_code == 200
    assert res.json()["archived_at"] is not None


@pytest.mark.asyncio
async def test_delete_environment(client: AsyncClient) -> None:
    created = (
        await client.post("/v1/environments", json={"name": "x", "config": {}})
    ).json()
    res = await client.delete(f"/v1/environments/{created['id']}")
    assert res.status_code == 204
    # subsequent get is 404
    res = await client.get(f"/v1/environments/{created['id']}")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_archive_unknown(client: AsyncClient) -> None:
    res = await client.post("/v1/environments/missing/archive")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_delete_unknown(client: AsyncClient) -> None:
    res = await client.delete("/v1/environments/missing")
    assert res.status_code == 404
