"""Tests for session lifecycle + event routes."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _make_agent(client: AsyncClient) -> dict:
    res = await client.post(
        "/v1/agents",
        json={"name": "test", "model": {"id": "claude-opus-4-7"}},
    )
    return res.json()


@pytest.mark.asyncio
async def test_create_session(client: AsyncClient) -> None:
    agent = await _make_agent(client)
    res = await client.post(
        "/v1/sessions",
        json={"agent_id": agent["id"]},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["agent_id"] == agent["id"]
    assert body["agent_version"] == 1
    assert body["status"] == "idle"


@pytest.mark.asyncio
async def test_create_session_unknown_agent(client: AsyncClient) -> None:
    res = await client.post("/v1/sessions", json={"agent_id": "missing"})
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_list_sessions(client: AsyncClient) -> None:
    agent = await _make_agent(client)
    await client.post("/v1/sessions", json={"agent_id": agent["id"]})
    await client.post("/v1/sessions", json={"agent_id": agent["id"]})
    res = await client.get("/v1/sessions")
    assert res.status_code == 200
    assert len(res.json()["data"]) == 2


@pytest.mark.asyncio
async def test_get_session(client: AsyncClient) -> None:
    agent = await _make_agent(client)
    created = (
        await client.post("/v1/sessions", json={"agent_id": agent["id"]})
    ).json()
    res = await client.get(f"/v1/sessions/{created['id']}")
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_get_unknown_session(client: AsyncClient) -> None:
    res = await client.get("/v1/sessions/missing")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_append_event_persists(client: AsyncClient) -> None:
    agent = await _make_agent(client)
    sess = (await client.post("/v1/sessions", json={"agent_id": agent["id"]})).json()

    res = await client.post(
        f"/v1/sessions/{sess['id']}/events",
        json={
            "type": "user.message",
            "payload": {"content": [{"type": "text", "text": "hi"}]},
        },
    )
    assert res.status_code == 202, res.text
    body = res.json()
    assert body["type"] == "user.message"
    assert body["seq"] == 0

    listed = await client.get(f"/v1/sessions/{sess['id']}/events")
    assert listed.status_code == 200
    data = listed.json()["data"]
    assert any(e["type"] == "user.message" for e in data)


@pytest.mark.asyncio
async def test_list_events_since(client: AsyncClient) -> None:
    agent = await _make_agent(client)
    sess = (await client.post("/v1/sessions", json={"agent_id": agent["id"]})).json()
    await client.post(
        f"/v1/sessions/{sess['id']}/events",
        json={"type": "status", "payload": {"from": "idle", "to": "idle"}},
    )
    await client.post(
        f"/v1/sessions/{sess['id']}/events",
        json={"type": "status", "payload": {"from": "idle", "to": "idle"}},
    )
    res = await client.get(f"/v1/sessions/{sess['id']}/events?since=1")
    assert res.status_code == 200
    data = res.json()["data"]
    assert all(e["seq"] >= 1 for e in data)


@pytest.mark.asyncio
async def test_append_event_unknown_session(client: AsyncClient) -> None:
    res = await client.post(
        "/v1/sessions/missing/events",
        json={"type": "user.message", "payload": {}},
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_interrupt_session(client: AsyncClient) -> None:
    agent = await _make_agent(client)
    sess = (await client.post("/v1/sessions", json={"agent_id": agent["id"]})).json()
    res = await client.post(f"/v1/sessions/{sess['id']}/interrupt")
    assert res.status_code == 200
    assert res.json()["status"] == "terminated"


@pytest.mark.asyncio
async def test_interrupt_unknown(client: AsyncClient) -> None:
    res = await client.post("/v1/sessions/missing/interrupt")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_archive_session(client: AsyncClient) -> None:
    agent = await _make_agent(client)
    sess = (await client.post("/v1/sessions", json={"agent_id": agent["id"]})).json()
    res = await client.post(f"/v1/sessions/{sess['id']}/archive")
    assert res.status_code == 200
    assert res.json()["status"] == "terminated"


@pytest.mark.asyncio
async def test_delete_session(client: AsyncClient) -> None:
    agent = await _make_agent(client)
    sess = (await client.post("/v1/sessions", json={"agent_id": agent["id"]})).json()
    res = await client.delete(f"/v1/sessions/{sess['id']}")
    assert res.status_code == 204
    res = await client.get(f"/v1/sessions/{sess['id']}")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_append_to_terminated_session_409(client: AsyncClient) -> None:
    agent = await _make_agent(client)
    sess = (await client.post("/v1/sessions", json={"agent_id": agent["id"]})).json()
    await client.post(f"/v1/sessions/{sess['id']}/interrupt")
    res = await client.post(
        f"/v1/sessions/{sess['id']}/events",
        json={"type": "user.message", "payload": {}},
    )
    assert res.status_code == 409
