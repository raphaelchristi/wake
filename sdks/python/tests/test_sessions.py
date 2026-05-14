"""CRUD coverage for the ``sessions`` and ``agents`` resources."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from wake_ai_client import WakeClient

from conftest import agent_payload, event_payload, session_payload


@pytest.mark.asyncio
async def test_create_session_posts_body() -> None:
    recorded: list[httpx.Request] = []

    async def handler(req: httpx.Request) -> httpx.Response:
        recorded.append(req)
        return httpx.Response(201, json=session_payload(metadata={"trace": "abc"}))

    transport = httpx.MockTransport(handler)
    async with WakeClient(base_url="http://wake.test", transport=transport) as c:
        s = await c.sessions.create(
            agent_id="agent_01",
            metadata={"trace": "abc"},
        )

    assert s.id == "sess_01"
    assert s.agent_id == "agent_01"
    assert s.metadata == {"trace": "abc"}
    assert recorded[0].method == "POST"
    assert recorded[0].url.path == "/v1/sessions"


@pytest.mark.asyncio
async def test_list_sessions_passes_filters() -> None:
    captured: list[httpx.Request] = []

    async def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200, json={"data": [session_payload()]})

    transport = httpx.MockTransport(handler)
    async with WakeClient(base_url="http://wake.test", transport=transport) as c:
        results = await c.sessions.list(
            agent="agent_01",
            status="running",
            since=datetime(2026, 1, 1, tzinfo=UTC),
            page=2,
            page_size=25,
        )

    assert len(results) == 1
    qs = dict(captured[0].url.params)
    assert qs["agent"] == "agent_01"
    assert qs["status"] == "running"
    assert qs["page"] == "2"
    assert qs["page_size"] == "25"
    assert qs["since"].startswith("2026-01-01")


@pytest.mark.asyncio
async def test_get_session() -> None:
    async def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/sessions/sess_01"
        return httpx.Response(200, json=session_payload())

    transport = httpx.MockTransport(handler)
    async with WakeClient(base_url="http://wake.test", transport=transport) as c:
        s = await c.sessions.get("sess_01")
    assert s.status == "idle"


@pytest.mark.asyncio
async def test_delete_session_returns_none() -> None:
    async def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "DELETE"
        return httpx.Response(204)

    transport = httpx.MockTransport(handler)
    async with WakeClient(base_url="http://wake.test", transport=transport) as c:
        result = await c.sessions.delete("sess_01")
    assert result is None


@pytest.mark.asyncio
async def test_interrupt_session() -> None:
    async def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/sessions/sess_01/interrupt"
        return httpx.Response(200, json=session_payload(status="terminated"))

    transport = httpx.MockTransport(handler)
    async with WakeClient(base_url="http://wake.test", transport=transport) as c:
        s = await c.sessions.interrupt("sess_01")
    assert s.status == "terminated"


@pytest.mark.asyncio
async def test_append_event_kicks_dispatcher() -> None:
    async def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/sessions/sess_01/events"
        return httpx.Response(202, json=event_payload(seq=1, type="user.message"))

    transport = httpx.MockTransport(handler)
    async with WakeClient(base_url="http://wake.test", transport=transport) as c:
        ev = await c.sessions.append_event(
            "sess_01",
            type="user.message",
            payload={"text": "hello"},
        )
    assert ev.type == "user.message"
    assert ev.seq == 1


@pytest.mark.asyncio
async def test_list_events() -> None:
    async def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [event_payload(0), event_payload(1)]},
        )

    transport = httpx.MockTransport(handler)
    async with WakeClient(base_url="http://wake.test", transport=transport) as c:
        evs = await c.sessions.list_events("sess_01", since=0)
    assert [e.seq for e in evs] == [0, 1]


# -- Agents resource ---------------------------------------------------------


@pytest.mark.asyncio
async def test_create_agent() -> None:
    async def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert req.url.path == "/v1/agents"
        return httpx.Response(201, json=agent_payload())

    transport = httpx.MockTransport(handler)
    async with WakeClient(base_url="http://wake.test", transport=transport) as c:
        a = await c.agents.create(
            name="researcher",
            model={"id": "claude-opus-4-7"},
            system="You are helpful.",
        )
    assert a.id == "agent_01"
    assert a.version == 1


@pytest.mark.asyncio
async def test_list_agents() -> None:
    async def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [agent_payload()]})

    transport = httpx.MockTransport(handler)
    async with WakeClient(base_url="http://wake.test", transport=transport) as c:
        agents = await c.agents.list()
    assert len(agents) == 1


@pytest.mark.asyncio
async def test_get_agent_with_version() -> None:
    captured: list[httpx.Request] = []

    async def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200, json=agent_payload(version=3))

    transport = httpx.MockTransport(handler)
    async with WakeClient(base_url="http://wake.test", transport=transport) as c:
        a = await c.agents.get("agent_01", version=3)
    assert a.version == 3
    assert captured[0].url.params["version"] == "3"


@pytest.mark.asyncio
async def test_update_agent_bumps_version() -> None:
    async def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "PATCH"
        return httpx.Response(200, json=agent_payload(version=2, name="renamed"))

    transport = httpx.MockTransport(handler)
    async with WakeClient(base_url="http://wake.test", transport=transport) as c:
        a = await c.agents.update("agent_01", name="renamed")
    assert a.version == 2
    assert a.name == "renamed"


@pytest.mark.asyncio
async def test_list_agent_versions() -> None:
    async def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [agent_payload(version=v) for v in (1, 2, 3)]},
        )

    transport = httpx.MockTransport(handler)
    async with WakeClient(base_url="http://wake.test", transport=transport) as c:
        versions = await c.agents.list_versions("agent_01")
    assert [a.version for a in versions] == [1, 2, 3]


@pytest.mark.asyncio
async def test_archive_agent() -> None:
    async def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/agents/agent_01/archive"
        return httpx.Response(200, json=agent_payload())

    transport = httpx.MockTransport(handler)
    async with WakeClient(base_url="http://wake.test", transport=transport) as c:
        a = await c.agents.archive("agent_01")
    assert a.id == "agent_01"
