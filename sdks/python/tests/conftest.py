"""Shared test fixtures for ``wake_ai_client`` tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import pytest_asyncio

from wake_ai_client import WakeClient


def _iso(value: datetime | None = None) -> str:
    return (value or datetime.now(UTC)).isoformat()


def session_payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "sess_01",
        "organization_id": "org-test",
        "workspace_id": "ws-test",
        "agent_id": "agent_01",
        "agent_version": 1,
        "status": "idle",
        "metadata": {},
        "created_at": _iso(),
        "updated_at": _iso(),
    }
    base.update(overrides)
    return base


def agent_payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "agent_01",
        "organization_id": "org-test",
        "workspace_id": "ws-test",
        "name": "test-agent",
        "model": {"id": "claude-opus-4-7", "speed": "standard", "provider": "anthropic"},
        "tools": [],
        "mcp_servers": [],
        "skills": [],
        "metadata": {},
        "version": 1,
        "created_at": _iso(),
        "updated_at": _iso(),
    }
    base.update(overrides)
    return base


def event_payload(seq: int = 0, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": f"evt_{seq:02d}",
        "session_id": "sess_01",
        "seq": seq,
        "type": "assistant.message",
        "payload": {"text": f"hello {seq}"},
        "created_at": _iso(),
    }
    base.update(overrides)
    return base


@pytest_asyncio.fixture
async def mock_client(
    request: pytest.FixtureRequest,
) -> AsyncIterator[tuple[WakeClient, list[httpx.Request]]]:
    """Yield ``(client, recorded_requests)``.

    The handler can be customized per-test by parametrizing or by passing
    ``handler=...`` indirectly through ``request.param``.
    """
    recorded: list[httpx.Request] = []
    handler = getattr(request, "param", None)

    async def default_handler(req: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(404, json={"detail": "not stubbed"})

    if handler is None:
        handler = default_handler

    async def wrapped(req: httpx.Request) -> httpx.Response:
        recorded.append(req)
        return await handler(req)

    transport = httpx.MockTransport(wrapped)
    client = WakeClient(
        base_url="http://wake.test",
        api_key="sk-test",
        organization_id="org-test",
        workspace_id="ws-test",
        transport=transport,
        max_retries=2,
    )
    try:
        yield client, recorded
    finally:
        await client.aclose()
