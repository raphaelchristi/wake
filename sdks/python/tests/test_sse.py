"""SSE streaming tests.

We exercise the stream by feeding raw SSE frames through ``httpx.MockTransport``
— ``httpx-sse`` parses them on top of the real httpx response, so this gives
us realistic coverage without spinning a server.
"""

from __future__ import annotations

import json

import httpx
import pytest

from wake_ai_client import WakeClient
from wake_ai_client.exceptions import WakeNotFoundError
from wake_ai_client.types import Event

from conftest import event_payload


def _sse_frame(event: str, data: dict | None = None, id_: str | None = None) -> str:
    out: list[str] = []
    if id_:
        out.append(f"id: {id_}")
    out.append(f"event: {event}")
    out.append(f"data: {json.dumps(data or {})}")
    out.append("")
    return "\n".join(out) + "\n"


def _sse_stream(*frames: str) -> bytes:
    return "".join(frames).encode("utf-8")


@pytest.mark.asyncio
async def test_stream_yields_events() -> None:
    body = _sse_stream(
        _sse_frame("event", event_payload(0), id_="evt_00"),
        _sse_frame("event", event_payload(1, type="assistant.delta"), id_="evt_01"),
    )

    async def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={"Content-Type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    async with WakeClient(base_url="http://wake.test", transport=transport) as c:
        collected: list[Event] = []
        async for ev in c.sessions.stream("sess_01"):
            collected.append(ev)
    assert [e.seq for e in collected] == [0, 1]
    assert collected[1].type == "assistant.delta"


@pytest.mark.asyncio
async def test_stream_filters_heartbeats() -> None:
    body = _sse_stream(
        _sse_frame("heartbeat", {"ts": "2026-01-01T00:00:00+00:00"}),
        _sse_frame("event", event_payload(0), id_="evt_00"),
        _sse_frame("heartbeat", {"ts": "2026-01-01T00:00:01+00:00"}),
        _sse_frame("event", event_payload(1), id_="evt_01"),
    )

    async def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={"Content-Type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    async with WakeClient(base_url="http://wake.test", transport=transport) as c:
        seen: list[Event] = []
        async for ev in c.sessions.stream("sess_01"):
            seen.append(ev)
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_stream_reconnects_after_transport_failure() -> None:
    """On a transport drop the iterator must reconnect transparently."""
    second_body = _sse_stream(
        _sse_frame("event", event_payload(0), id_="evt_00"),
        _sse_frame("event", event_payload(1), id_="evt_01"),
    )
    call = {"n": 0}

    async def handler(req: httpx.Request) -> httpx.Response:
        call["n"] += 1
        if call["n"] == 1:
            # First connection drops before any frame is received.
            raise httpx.RemoteProtocolError("conn reset", request=req)
        return httpx.Response(
            200,
            content=second_body,
            headers={"Content-Type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    async with WakeClient(base_url="http://wake.test", transport=transport) as c:
        collected: list[Event] = []
        async for ev in c.sessions.stream("sess_01"):
            collected.append(ev)
            if len(collected) >= 2:
                break

    assert [e.seq for e in collected] == [0, 1]
    # Two HTTP attempts: first failed, second succeeded.
    assert call["n"] == 2


@pytest.mark.asyncio
async def test_stream_forwards_last_event_id_on_reconnect() -> None:
    """After yielding an event, a reconnect must carry ``Last-Event-ID``."""
    body_1 = _sse_stream(_sse_frame("event", event_payload(0), id_="evt_00"))
    body_2 = _sse_stream(_sse_frame("event", event_payload(1), id_="evt_01"))
    call = {"n": 0}
    headers_seen: list[str | None] = []

    async def handler(req: httpx.Request) -> httpx.Response:
        call["n"] += 1
        headers_seen.append(req.headers.get("Last-Event-ID"))
        if call["n"] == 1:
            return httpx.Response(
                200,
                content=body_1,
                headers={"Content-Type": "text/event-stream"},
            )
        if call["n"] == 2:
            raise httpx.RemoteProtocolError("drop", request=req)
        return httpx.Response(
            200,
            content=body_2,
            headers={"Content-Type": "text/event-stream"},
        )

    # We use a custom client whose iter_session_stream is invoked manually so
    # we can survive the clean EOF after call 1 by re-iterating.
    transport = httpx.MockTransport(handler)
    async with WakeClient(base_url="http://wake.test", transport=transport) as c:
        # Manually drive the SSE helper, advancing across the clean EOF.
        from wake_ai_client.sse import iter_session_stream

        events: list[Event] = []
        # First pass: collect evt_00, the stream cleanly EOFs.
        async for ev in iter_session_stream(c, "sess_01"):
            events.append(ev)
        # Second pass: now resume with Last-Event-ID = evt_00.
        async for ev in iter_session_stream(c, "sess_01", last_event_id="evt_00"):
            events.append(ev)
            if len(events) >= 2:
                break

    assert [e.seq for e in events] == [0, 1]
    # First call had no Last-Event-ID; second pass forwarded evt_00.
    assert headers_seen[0] is None
    assert "evt_00" in headers_seen[1:]


@pytest.mark.asyncio
async def test_stream_4xx_raises() -> None:
    async def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "session not found"})

    transport = httpx.MockTransport(handler)
    async with WakeClient(base_url="http://wake.test", transport=transport) as c:
        with pytest.raises(WakeNotFoundError):
            async for _ in c.sessions.stream("missing"):
                pass


@pytest.mark.asyncio
async def test_stream_since_passed_as_query_param() -> None:
    captured: list[httpx.Request] = []

    async def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(
            200,
            content=_sse_stream(),
            headers={"Content-Type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    async with WakeClient(base_url="http://wake.test", transport=transport) as c:
        async for _ in c.sessions.stream("sess_01", since=5):
            pass
    assert captured[0].url.params["since"] == "5"
    assert captured[0].headers["Accept"] == "text/event-stream"
