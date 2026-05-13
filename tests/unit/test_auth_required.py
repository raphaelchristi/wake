"""Tests for the canonical Wake auth modes.

Covers the four-state truth table documented in
``PHASE-5.1-CONTRACT.md`` / ``src/wake/api/dependencies.py::verify_api_key``:

| ``WAKE_API_KEY`` | ``WAKE_AUTH_REQUIRED`` | Outcome |
|---|---|---|
| unset            | unset / false           | no-op (dev mode) |
| set              | unset / true            | header must match |
| unset            | true                    | 503 "auth required but not configured" |
| set              | true                    | header must match |

Each test mutates only the env vars it cares about via ``monkeypatch`` so they
remain isolated.
"""

# ruff: noqa: TC002
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from wake.api.app import create_app
from wake.api.dependencies import WAKE_API_KEY_ENV, WAKE_AUTH_REQUIRED_ENV


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _empty_app() -> FastAPI:
    # We don't wire any stores — auth dep fires before route handlers, so a
    # 200 from a no-op verify means "auth passed" (the downstream route then
    # 501s because the store is missing, but that's not what we're testing).
    return create_app()


@pytest.mark.asyncio
async def test_no_key_no_required_dev_mode_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default config: no auth → request reaches downstream (which 501s)."""
    monkeypatch.delenv(WAKE_API_KEY_ENV, raising=False)
    monkeypatch.delenv(WAKE_AUTH_REQUIRED_ENV, raising=False)
    app = _empty_app()
    async with _client(app) as ac:
        res = await ac.get("/v1/agents")
    # Auth dep is a no-op → downstream returns 501 (store not configured),
    # not 401/503. The point is auth didn't block us.
    assert res.status_code == 501, res.text


@pytest.mark.asyncio
async def test_key_set_correct_header_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(WAKE_API_KEY_ENV, "secret-123")
    monkeypatch.delenv(WAKE_AUTH_REQUIRED_ENV, raising=False)
    app = _empty_app()
    async with _client(app) as ac:
        res = await ac.get("/v1/agents", headers={"X-Wake-API-Key": "secret-123"})
    assert res.status_code == 501, res.text  # auth passed → downstream 501


@pytest.mark.asyncio
async def test_key_set_wrong_header_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(WAKE_API_KEY_ENV, "secret-123")
    monkeypatch.delenv(WAKE_AUTH_REQUIRED_ENV, raising=False)
    app = _empty_app()
    async with _client(app) as ac:
        res = await ac.get("/v1/agents", headers={"X-Wake-API-Key": "wrong"})
    assert res.status_code == 401
    assert res.json()["detail"] == "invalid api key"


@pytest.mark.asyncio
async def test_key_set_missing_header_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(WAKE_API_KEY_ENV, "secret-123")
    monkeypatch.delenv(WAKE_AUTH_REQUIRED_ENV, raising=False)
    app = _empty_app()
    async with _client(app) as ac:
        res = await ac.get("/v1/agents")
    assert res.status_code == 401
    assert res.json()["detail"] == "missing api key"


@pytest.mark.asyncio
async def test_auth_required_no_key_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail-closed: WAKE_AUTH_REQUIRED=true without a key → 503."""
    monkeypatch.delenv(WAKE_API_KEY_ENV, raising=False)
    monkeypatch.setenv(WAKE_AUTH_REQUIRED_ENV, "true")
    app = _empty_app()
    async with _client(app) as ac:
        res = await ac.get("/v1/agents", headers={"X-Wake-API-Key": "anything"})
    assert res.status_code == 503
    assert res.json()["detail"] == "auth required but not configured"


@pytest.mark.asyncio
async def test_auth_required_with_key_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail-closed + key set: behaves exactly like the normal authenticated mode."""
    monkeypatch.setenv(WAKE_API_KEY_ENV, "secret-456")
    monkeypatch.setenv(WAKE_AUTH_REQUIRED_ENV, "true")
    app = _empty_app()
    async with _client(app) as ac:
        # Correct key → 501 downstream (auth passed)
        ok = await ac.get("/v1/agents", headers={"X-Wake-API-Key": "secret-456"})
        # Wrong key → 401
        bad = await ac.get("/v1/agents", headers={"X-Wake-API-Key": "nope"})
    assert ok.status_code == 501, ok.text
    assert bad.status_code == 401


@pytest.mark.asyncio
async def test_health_unaffected_by_auth_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    """``/health`` is mounted outside the auth dep — it must answer in every mode."""
    monkeypatch.setenv(WAKE_AUTH_REQUIRED_ENV, "true")
    monkeypatch.delenv(WAKE_API_KEY_ENV, raising=False)
    app = _empty_app()
    async with _client(app) as ac:
        res = await ac.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
