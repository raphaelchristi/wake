"""SSE stream endpoint tests.

We exercise the endpoint via ASGI + httpx streaming. To avoid hanging on
long-running event streams, each test uses asyncio.wait_for or finishes by
forcing the request to close.
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient


async def _make_session(client: AsyncClient) -> str:
    agent = (
        await client.post(
            "/v1/agents",
            json={"name": "x", "model": {"id": "claude-opus-4-7"}},
        )
    ).json()
    sess = (
        await client.post("/v1/sessions", json={"agent_id": agent["id"]})
    ).json()
    return sess["id"]


@pytest.mark.asyncio
async def test_sse_unknown_session(client: AsyncClient) -> None:
    r = await client.get("/v1/sessions/missing/stream")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_sse_backlog_replay(client: AsyncClient, app_components: dict) -> None:
    sid = await _make_session(client)
    log = app_components["event_log"]
    await log.append(sid, "user.message", {"content": [{"type": "text", "text": "hi"}]})
    await log.append(
        sid,
        "assistant.message",
        {"content": [{"type": "text", "text": "yo"}]},
    )

    async def _collect() -> str:
        chunks: list[bytes] = []
        async with client.stream(
            "GET", f"/v1/sessions/{sid}/stream?max_events=2"
        ) as r:
            assert r.status_code == 200
            async for chunk in r.aiter_bytes():
                chunks.append(chunk)
        return b"".join(chunks).decode()

    text = await asyncio.wait_for(_collect(), timeout=5.0)
    assert text.count("event: event") >= 2
    assert "assistant.message" in text
    assert "user.message" in text


@pytest.mark.asyncio
async def test_sse_live_event(client: AsyncClient, app_components: dict) -> None:
    sid = await _make_session(client)
    log = app_components["event_log"]

    async def _emit_later() -> None:
        await asyncio.sleep(0.1)
        await log.append(sid, "user.message", {"content": []})

    async def _consume() -> bytes:
        collected = b""
        async with client.stream(
            "GET", f"/v1/sessions/{sid}/stream?max_events=1"
        ) as r:
            assert r.status_code == 200
            async for chunk in r.aiter_bytes():
                collected += chunk
        return collected

    emitter = asyncio.create_task(_emit_later())
    try:
        data = await asyncio.wait_for(_consume(), timeout=5.0)
        assert b"user.message" in data
    finally:
        emitter.cancel()
        try:
            await emitter
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_sse_resume_via_since(client: AsyncClient, app_components: dict) -> None:
    sid = await _make_session(client)
    log = app_components["event_log"]
    e1 = await log.append(sid, "user.message", {"content": []})
    e2 = await log.append(sid, "assistant.message", {"content": []})

    async def _collect() -> str:
        chunks: list[bytes] = []
        async with client.stream(
            "GET", f"/v1/sessions/{sid}/stream?since={e2.seq}&max_events=1"
        ) as r:
            assert r.status_code == 200
            async for chunk in r.aiter_bytes():
                chunks.append(chunk)
        return b"".join(chunks).decode()

    text = await asyncio.wait_for(_collect(), timeout=5.0)
    # Should skip e1, include e2
    assert e2.id in text
    assert e1.id not in text
