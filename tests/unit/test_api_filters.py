"""Tests for the additive filter/pagination query params on GET /v1/sessions.

These exercise the Phase 5 (dashboard-shell) backend additions:

* ``agent``, ``status``, ``model``, ``since``, ``until``, ``q`` filters
* ``page`` / ``page_size`` pagination (offset-based)
* Backwards compatibility — calling ``GET /v1/sessions`` with no params still
  returns the legacy ``{ "data": [...] }`` envelope.

Also covers the ``verify_api_key`` dependency wired into the API routers.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest import mock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


async def _make_agent(client: AsyncClient, name: str = "test") -> dict[str, Any]:
    res = await client.post(
        "/v1/agents",
        json={"name": name, "model": {"id": "claude-opus-4-7"}},
    )
    return res.json()


async def _create_session(
    client: AsyncClient,
    agent_id: str,
    *,
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    res = await client.post(
        "/v1/sessions",
        json={
            "agent_id": agent_id,
            "metadata": metadata or {},
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


@pytest.mark.asyncio
async def test_list_sessions_no_filters_unchanged(client: AsyncClient) -> None:
    """Existing clients keep working — empty list still has the envelope."""
    res = await client.get("/v1/sessions")
    assert res.status_code == 200
    body = res.json()
    assert "data" in body
    assert body["data"] == []


@pytest.mark.asyncio
async def test_filter_by_agent(client: AsyncClient) -> None:
    a1 = await _make_agent(client, "alpha")
    a2 = await _make_agent(client, "beta")
    s1 = await _create_session(client, a1["id"])
    await _create_session(client, a2["id"])

    res = await client.get(f"/v1/sessions?agent={a1['id']}")
    assert res.status_code == 200
    data = res.json()["data"]
    assert len(data) == 1
    assert data[0]["id"] == s1["id"]


@pytest.mark.asyncio
async def test_filter_by_status(client: AsyncClient) -> None:
    agent = await _make_agent(client)
    running = await _create_session(client, agent["id"])
    terminated = await _create_session(client, agent["id"])

    # terminate one
    await client.post(f"/v1/sessions/{terminated['id']}/archive")

    res = await client.get("/v1/sessions?status=terminated")
    assert res.status_code == 200
    data = res.json()["data"]
    assert {s["id"] for s in data} == {terminated["id"]}

    res = await client.get("/v1/sessions?status=idle")
    data = res.json()["data"]
    assert {s["id"] for s in data} == {running["id"]}


@pytest.mark.asyncio
async def test_filter_by_model_metadata(client: AsyncClient) -> None:
    agent = await _make_agent(client)
    opus = await _create_session(client, agent["id"], metadata={"model": "claude-opus-4-7"})
    sonnet = await _create_session(client, agent["id"], metadata={"model": "claude-sonnet-4-7"})

    res = await client.get("/v1/sessions?model=opus")
    assert res.status_code == 200
    assert {s["id"] for s in res.json()["data"]} == {opus["id"]}

    res = await client.get("/v1/sessions?model=sonnet")
    assert {s["id"] for s in res.json()["data"]} == {sonnet["id"]}


@pytest.mark.asyncio
async def test_filter_q_substring(client: AsyncClient) -> None:
    agent = await _make_agent(client)
    tagged = await _create_session(
        client, agent["id"], metadata={"env": "prod", "tag": "needle-in-haystack"}
    )
    await _create_session(client, agent["id"], metadata={"env": "dev"})

    res = await client.get("/v1/sessions?q=needle")
    assert res.status_code == 200
    assert {s["id"] for s in res.json()["data"]} == {tagged["id"]}


@pytest.mark.asyncio
async def test_filter_since_until(client: AsyncClient) -> None:
    agent = await _make_agent(client)
    sess = await _create_session(client, agent["id"])

    far_future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    far_past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

    # since after the session created_at → empty.
    # Use params= so httpx encodes the ISO string (the ``+`` in tz offset
    # otherwise gets interpreted as a space).
    res = await client.get("/v1/sessions", params={"since": far_future})
    assert res.status_code == 200
    assert res.json()["data"] == []

    # since before → 1 session
    res = await client.get("/v1/sessions", params={"since": far_past})
    assert {s["id"] for s in res.json()["data"]} == {sess["id"]}

    # until before → empty
    res = await client.get("/v1/sessions", params={"until": far_past})
    assert res.json()["data"] == []


@pytest.mark.asyncio
async def test_pagination(client: AsyncClient) -> None:
    agent = await _make_agent(client)
    created_ids = [
        (await _create_session(client, agent["id"]))["id"] for _ in range(5)
    ]

    page1 = await client.get("/v1/sessions?page=1&page_size=2")
    page2 = await client.get("/v1/sessions?page=2&page_size=2")
    page3 = await client.get("/v1/sessions?page=3&page_size=2")
    page4 = await client.get("/v1/sessions?page=4&page_size=2")

    assert len(page1.json()["data"]) == 2
    assert len(page2.json()["data"]) == 2
    assert len(page3.json()["data"]) == 1
    assert page4.json()["data"] == []

    seen: list[str] = []
    for r in (page1, page2, page3):
        seen.extend(s["id"] for s in r.json()["data"])
    assert sorted(seen) == sorted(created_ids)


@pytest.mark.asyncio
async def test_page_size_bounds(client: AsyncClient) -> None:
    res = await client.get("/v1/sessions?page_size=0")
    assert res.status_code == 422
    res = await client.get("/v1/sessions?page_size=10000")
    assert res.status_code == 422
    res = await client.get("/v1/sessions?page=0")
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_status_invalid_returns_422(client: AsyncClient) -> None:
    res = await client.get("/v1/sessions?status=banana")
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# verify_api_key dependency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_api_key_noop_when_env_unset(client: AsyncClient) -> None:
    # No WAKE_API_KEY set → requests succeed without the header.
    res = await client.get("/v1/sessions")
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_verify_api_key_rejects_missing_header(app_components: dict[str, Any]) -> None:
    from wake.api.app import create_app

    # ``app_components`` is the shared fixture from conftest; it returns extra
    # keys (``event_store``) that aren't valid kwargs for ``create_app`` —
    # whitelist what we actually pass.
    create_app_kwargs = {
        k: v
        for k, v in app_components.items()
        if k
        in {
            "agent_store",
            "environment_store",
            "session_store",
            "event_log",
            "session_machine",
            "tool_registry",
            "sandbox",
            "adapter_registry",
            "dispatcher",
        }
    }

    with mock.patch.dict(os.environ, {"WAKE_API_KEY": "secret"}):
        app: FastAPI = create_app(**create_app_kwargs)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # no header → 401
            res = await ac.get("/v1/sessions")
            assert res.status_code == 401

            # /health is exempt → 200
            health = await ac.get("/health")
            assert health.status_code == 200

            # with the right header → 200
            ok = await ac.get("/v1/sessions", headers={"X-Wake-API-Key": "secret"})
            assert ok.status_code == 200

            # with the wrong header → 401
            bad = await ac.get("/v1/sessions", headers={"X-Wake-API-Key": "wrong"})
            assert bad.status_code == 401
