"""Smoke tests for ``WakeClient`` construction + auth + retries."""

from __future__ import annotations

import httpx
import pytest

from wake_ai_client import (
    WakeAPIError,
    WakeAuthError,
    WakeClient,
    WakeNotFoundError,
    WakeRateLimitError,
    WakeServerError,
    WakeTransportError,
)


def test_base_url_required() -> None:
    with pytest.raises(ValueError):
        WakeClient(base_url="")


@pytest.mark.asyncio
async def test_base_url_normalizes_trailing_slash() -> None:
    async with WakeClient(base_url="http://wake.test/") as c:
        assert c.base_url == "http://wake.test"


@pytest.mark.asyncio
async def test_api_key_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WAKE_API_KEY", "env-key")
    async with WakeClient(base_url="http://wake.test") as c:
        # default header carries env key
        assert c._default_headers()["X-Wake-API-Key"] == "env-key"


@pytest.mark.asyncio
async def test_api_key_explicit_none_disables_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WAKE_API_KEY", "env-key")
    async with WakeClient(base_url="http://wake.test", api_key=None) as c:
        assert "X-Wake-API-Key" not in c._default_headers()


@pytest.mark.asyncio
async def test_tenant_headers_injected() -> None:
    recorded: list[httpx.Request] = []

    async def handler(req: httpx.Request) -> httpx.Response:
        recorded.append(req)
        return httpx.Response(200, json={"data": []})

    transport = httpx.MockTransport(handler)
    async with WakeClient(
        base_url="http://wake.test",
        api_key="k",
        organization_id="org-x",
        workspace_id="ws-y",
        user_id="user-z",
        transport=transport,
    ) as c:
        await c.agents.list()

    assert recorded[0].headers["X-Wake-API-Key"] == "k"
    assert recorded[0].headers["X-Wake-Organization-Id"] == "org-x"
    assert recorded[0].headers["X-Wake-Workspace-Id"] == "ws-y"
    assert recorded[0].headers["X-Wake-User-Id"] == "user-z"


@pytest.mark.asyncio
async def test_404_raises_not_found() -> None:
    async def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "agent not found"})

    transport = httpx.MockTransport(handler)
    async with WakeClient(base_url="http://wake.test", transport=transport) as c:
        with pytest.raises(WakeNotFoundError) as exc:
            await c.agents.get("missing")
        assert exc.value.status_code == 404
        assert "agent not found" in str(exc.value)


@pytest.mark.asyncio
async def test_401_raises_auth_error() -> None:
    async def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "missing api key"})

    transport = httpx.MockTransport(handler)
    async with WakeClient(base_url="http://wake.test", transport=transport) as c:
        with pytest.raises(WakeAuthError):
            await c.agents.list()


@pytest.mark.asyncio
async def test_retry_on_5xx_then_success() -> None:
    calls = {"n": 0}

    async def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json={"detail": "transient"})
        return httpx.Response(200, json={"data": []})

    transport = httpx.MockTransport(handler)
    async with WakeClient(
        base_url="http://wake.test",
        transport=transport,
        max_retries=3,
    ) as c:
        agents = await c.agents.list()
    assert agents == []
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_retry_exhausted_raises_server_error() -> None:
    calls = {"n": 0}

    async def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, json={"detail": "boom"})

    transport = httpx.MockTransport(handler)
    async with WakeClient(
        base_url="http://wake.test",
        transport=transport,
        max_retries=2,
    ) as c:
        with pytest.raises(WakeServerError):
            await c.agents.list()
    assert calls["n"] == 3  # initial + 2 retries


@pytest.mark.asyncio
async def test_429_honors_retry_after() -> None:
    calls = {"n": 0}

    async def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                429,
                json={"detail": "rate limited"},
                headers={"Retry-After": "0"},
            )
        return httpx.Response(200, json={"data": []})

    transport = httpx.MockTransport(handler)
    async with WakeClient(
        base_url="http://wake.test",
        transport=transport,
        max_retries=2,
    ) as c:
        await c.agents.list()
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_429_no_retry_raises_rate_limit_error() -> None:
    async def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"detail": "rate limited"},
            headers={"Retry-After": "0"},
        )

    transport = httpx.MockTransport(handler)
    async with WakeClient(
        base_url="http://wake.test",
        transport=transport,
        max_retries=0,
    ) as c:
        with pytest.raises(WakeRateLimitError) as exc:
            await c.agents.list()
        assert exc.value.retry_after == 0.0


@pytest.mark.asyncio
async def test_mutating_verb_does_not_retry_by_default() -> None:
    calls = {"n": 0}

    async def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, json={"detail": "fail"})

    transport = httpx.MockTransport(handler)
    async with WakeClient(
        base_url="http://wake.test",
        transport=transport,
        max_retries=3,
    ) as c:
        with pytest.raises(WakeServerError):
            await c.sessions.create(agent_id="a")
    # POST does not retry unless opted in
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_transport_error_translates() -> None:
    async def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("DNS dead")

    transport = httpx.MockTransport(handler)
    async with WakeClient(
        base_url="http://wake.test",
        transport=transport,
        max_retries=0,
    ) as c:
        with pytest.raises(WakeTransportError):
            await c.agents.list()


@pytest.mark.asyncio
async def test_idempotency_key_forwarded() -> None:
    recorded: list[httpx.Request] = []

    async def handler(req: httpx.Request) -> httpx.Response:
        recorded.append(req)
        return httpx.Response(
            202,
            json={
                "id": "evt_01",
                "session_id": "sess_01",
                "seq": 0,
                "type": "user.message",
                "payload": {"text": "hi"},
                "created_at": "2026-01-01T00:00:00+00:00",
            },
        )

    transport = httpx.MockTransport(handler)
    async with WakeClient(base_url="http://wake.test", transport=transport) as c:
        await c.sessions.append_event(
            "sess_01",
            type="user.message",
            payload={"text": "hi"},
            idempotency_key="abc-123",
        )
    assert recorded[0].headers["Idempotency-Key"] == "abc-123"


@pytest.mark.asyncio
async def test_arbitrary_4xx_raises_generic_api_error() -> None:
    async def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(418, json={"detail": "i'm a teapot"})

    transport = httpx.MockTransport(handler)
    async with WakeClient(
        base_url="http://wake.test",
        transport=transport,
    ) as c:
        with pytest.raises(WakeAPIError) as exc:
            await c.agents.list()
        assert exc.value.status_code == 418
