"""Tests for the production app factory (``wake.api.bootstrap``).

These tests use the SQLite backend exclusively — Postgres wiring is
covered by ``adapters/postgres-store/tests`` and exercising it here
would force a live Postgres dependency on the unit suite. We *do*
verify the env-var-driven branches and that an end-to-end roundtrip
(POST /v1/agents → POST /v1/sessions → GET /v1/sessions) succeeds
against the assembled app.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from wake.api import bootstrap


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Force every test into a clean env with a per-test SQLite file."""
    db = tmp_path / "wake.db"
    monkeypatch.setenv(bootstrap.WAKE_DATABASE_URL_ENV, f"sqlite+aiosqlite:///{db}")
    # Sandbox + vault default to off so the tests never reach docker /
    # Infisical SDKs.
    monkeypatch.setenv(bootstrap.WAKE_SANDBOX_BACKEND_ENV, "none")
    monkeypatch.setenv(bootstrap.WAKE_VAULT_PROVIDER_ENV, "none")


@pytest_asyncio.fixture
async def prod_app() -> FastAPI:
    return await bootstrap.create_production_app()


@pytest_asyncio.fixture
async def prod_client(prod_app: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=prod_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_creates_app_with_sqlite_default_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Bootstrap should fall back to the file-default SQLite DSN."""
    monkeypatch.delenv(bootstrap.WAKE_DATABASE_URL_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    store = await bootstrap.build_store()
    assert type(store).__name__ == "SQLiteStore"
    # Default DSN places the file in CWD.
    assert "wake.db" in store.url


@pytest.mark.asyncio
async def test_reads_database_url_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    explicit = tmp_path / "custom.db"
    monkeypatch.setenv(
        bootstrap.WAKE_DATABASE_URL_ENV, f"sqlite+aiosqlite:///{explicit}"
    )
    store = await bootstrap.build_store()
    assert str(explicit) in store.url


@pytest.mark.asyncio
async def test_sandbox_disabled_when_backend_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(bootstrap.WAKE_SANDBOX_BACKEND_ENV, "none")
    assert bootstrap.build_sandbox() is None


@pytest.mark.asyncio
async def test_vault_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(bootstrap.WAKE_VAULT_PROVIDER_ENV, "none")
    assert bootstrap.build_vault() is None


@pytest.mark.asyncio
async def test_build_components_returns_full_wiring() -> None:
    components = await bootstrap.build_components()
    assert components["store"] is not None
    assert components["event_log"] is not None
    assert components["session_machine"] is not None
    assert components["adapter_registry"] is not None
    assert components["dispatcher"] is not None
    # Sandbox + vault may be None when the env says so.
    assert "sandbox" in components
    assert "vault" in components
    # Cleanup the underlying engine.
    close = getattr(components["store"], "close", None)
    if close is not None:
        await close()


@pytest.mark.asyncio
async def test_health_reports_components_wired(prod_client: AsyncClient) -> None:
    """`/health` should reflect that real components are wired."""
    resp = await prod_client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    components = body["components"]
    assert components["agent_store"] is True
    assert components["session_store"] is True
    assert components["event_log"] is True
    assert components["dispatcher"] is True
    assert components["adapter_registry"] is True


@pytest.mark.asyncio
async def test_create_session_via_test_client(prod_client: AsyncClient) -> None:
    """End-to-end smoke: agent → session → list."""
    # /v1/agents
    agent_res = await prod_client.post(
        "/v1/agents",
        json={"name": "bootstrap-test", "model": {"id": "claude-opus-4-7"}},
    )
    assert agent_res.status_code == 201, agent_res.text
    agent = agent_res.json()

    # /v1/sessions
    sess_res = await prod_client.post(
        "/v1/sessions", json={"agent_id": agent["id"]}
    )
    assert sess_res.status_code == 201, sess_res.text
    session = sess_res.json()
    assert session["agent_id"] == agent["id"]
    assert session["status"] == "idle"

    # GET /v1/sessions should return at least the one we just created.
    list_res = await prod_client.get("/v1/sessions")
    assert list_res.status_code == 200
    listed = list_res.json()["data"]
    assert any(s["id"] == session["id"] for s in listed)


@pytest.mark.asyncio
async def test_create_production_app_returns_fastapi() -> None:
    app = await bootstrap.create_production_app()
    assert isinstance(app, FastAPI)
    # Routes from every router should be mounted.
    paths = {r.path for r in app.routes}  # type: ignore[attr-defined]
    assert "/health" in paths
    assert "/v1/sessions" in paths
    assert "/v1/agents" in paths
