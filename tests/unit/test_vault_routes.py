"""Tests for the vault routes (mocked adapter)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


# ---------------------------------------------------------------------------
# Mock vault adapter (matches VaultAdapter ABC duck-type wise)
# ---------------------------------------------------------------------------


class _MockCredMeta:
    def __init__(
        self,
        vault_id: str,
        name: str,
        provider: str,
        scopes: list[str],
        created_at: datetime,
    ) -> None:
        self.vault_id = vault_id
        self.name = name
        self.provider = provider
        self.scopes = scopes
        self.created_at = created_at
        self.expires_at = None
        self.metadata: dict[str, Any] = {}


class MockVault:
    """In-process stand-in for a real ``VaultAdapter`` implementation."""

    def __init__(self) -> None:
        self.items: dict[str, _MockCredMeta] = {}
        self.add_calls: list[tuple[str, str, str]] = []
        self.revoked: list[str] = []

    async def list(self) -> list[_MockCredMeta]:  # noqa: A003
        return list(self.items.values())

    async def add(
        self,
        name: str,
        provider: str,
        value: str,
        scopes: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> _MockCredMeta:
        vault_id = f"vault_{len(self.items) + 1}"
        meta = _MockCredMeta(
            vault_id=vault_id,
            name=name,
            provider=provider,
            scopes=list(scopes or []),
            created_at=datetime.now(timezone.utc),
        )
        if metadata:
            meta.metadata = dict(metadata)
        self.items[vault_id] = meta
        self.add_calls.append((name, provider, value))
        return meta

    async def get_metadata(self, vault_id: str) -> _MockCredMeta:
        if vault_id not in self.items:
            raise KeyError(vault_id)
        return self.items[vault_id]

    async def revoke(self, vault_id: str) -> None:
        self.revoked.append(vault_id)
        self.items.pop(vault_id, None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def vault_app() -> tuple[FastAPI, MockVault]:
    from wake.api.app import create_app

    vault = MockVault()
    app = create_app(vault=vault)
    return app, vault


@pytest_asyncio.fixture
async def empty_app() -> FastAPI:
    from wake.api.app import create_app

    return create_app()  # no vault wired


@pytest_asyncio.fixture
async def vault_client(vault_app: tuple[FastAPI, MockVault]) -> AsyncClient:
    app, _ = vault_app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def empty_client(empty_app: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=empty_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Without vault wired (503 behavior)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_credentials_503_when_no_vault(empty_client: AsyncClient) -> None:
    res = await empty_client.get("/v1/vault/credentials")
    assert res.status_code == 503
    assert "Vault not configured" in res.text


@pytest.mark.asyncio
async def test_audit_503_when_no_vault(empty_client: AsyncClient) -> None:
    res = await empty_client.get("/v1/vault/audit")
    assert res.status_code == 503


@pytest.mark.asyncio
async def test_oauth_start_503_when_no_vault(empty_client: AsyncClient) -> None:
    res = await empty_client.post("/v1/vault/oauth/start", json={"provider": "github"})
    assert res.status_code == 503


# ---------------------------------------------------------------------------
# With vault wired
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_empty_credentials(vault_client: AsyncClient) -> None:
    res = await vault_client.get("/v1/vault/credentials")
    assert res.status_code == 200, res.text
    assert res.json() == {"data": []}


@pytest.mark.asyncio
async def test_list_credentials_after_add(
    vault_app: tuple[FastAPI, MockVault],
    vault_client: AsyncClient,
) -> None:
    _, vault = vault_app
    await vault.add(name="gh_test", provider="github", value="secret", scopes=["repo"])

    res = await vault_client.get("/v1/vault/credentials")
    assert res.status_code == 200
    data = res.json()["data"]
    assert len(data) == 1
    assert data[0]["name"] == "gh_test"
    assert data[0]["provider"] == "github"
    assert data[0]["scopes"] == ["repo"]
    # IMPORTANT: token value must never appear in the response.
    assert "secret" not in res.text
    assert "access_token" not in res.text


@pytest.mark.asyncio
async def test_oauth_start_unknown_provider(vault_client: AsyncClient) -> None:
    res = await vault_client.post(
        "/v1/vault/oauth/start", json={"provider": "twitter"}
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_oauth_start_missing_client_config(vault_client: AsyncClient) -> None:
    # No WAKE_OAUTH_GITHUB_CLIENT_ID env → 500
    res = await vault_client.post(
        "/v1/vault/oauth/start", json={"provider": "github"}
    )
    assert res.status_code == 500
    assert "OAuth client not configured" in res.text


@pytest.mark.asyncio
async def test_oauth_start_with_env_config(
    monkeypatch: pytest.MonkeyPatch,
    vault_client: AsyncClient,
) -> None:
    monkeypatch.setenv("WAKE_OAUTH_GITHUB_CLIENT_ID", "cid")
    monkeypatch.setenv("WAKE_OAUTH_GITHUB_CLIENT_SECRET", "secret")
    monkeypatch.setenv(
        "WAKE_OAUTH_GITHUB_REDIRECT_URI", "http://localhost:3000/oauth/callback"
    )
    res = await vault_client.post(
        "/v1/vault/oauth/start", json={"provider": "github", "scopes": ["repo"]}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["provider"] == "github"
    assert "client_id=cid" in body["auth_url"]
    assert body["state"]
    # Secret must never appear in response.
    assert "secret" not in body["auth_url"]


@pytest.mark.asyncio
async def test_oauth_callback_unknown_state(vault_client: AsyncClient) -> None:
    res = await vault_client.get(
        "/v1/vault/oauth/callback", params={"code": "c", "state": "missing"}
    )
    assert res.status_code == 400
    assert "unknown or expired state" in res.text


@pytest.mark.asyncio
async def test_oauth_callback_happy_path(
    monkeypatch: pytest.MonkeyPatch,
    vault_app: tuple[FastAPI, MockVault],
    vault_client: AsyncClient,
) -> None:
    monkeypatch.setenv("WAKE_OAUTH_GITHUB_CLIENT_ID", "cid")
    monkeypatch.setenv("WAKE_OAUTH_GITHUB_CLIENT_SECRET", "secret")

    # Start flow.
    res = await vault_client.post(
        "/v1/vault/oauth/start", json={"provider": "github"}
    )
    assert res.status_code == 200
    state = res.json()["state"]

    # Patch exchange_code on the in-memory flow object.
    app, vault = vault_app
    entry = app.state.wake.oauth_flows[state]
    flow = entry["flow"]

    async def fake_exchange(code: str, state: str | None = None) -> dict[str, Any]:  # noqa: ARG001
        return {"access_token": "ghp_abc123", "scope": "repo"}

    flow.exchange_code = fake_exchange  # type: ignore[method-assign]

    res = await vault_client.get(
        "/v1/vault/oauth/callback", params={"code": "supercode", "state": state}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["provider"] == "github"
    assert body["vault_id"].startswith("vault_")
    # Token never echoed.
    assert "ghp_abc123" not in res.text
    # Vault saw the add.
    assert len(vault.add_calls) == 1
    assert vault.add_calls[0][2] == "ghp_abc123"


@pytest.mark.asyncio
async def test_revoke_credential(
    vault_app: tuple[FastAPI, MockVault],
    vault_client: AsyncClient,
) -> None:
    _, vault = vault_app
    meta = await vault.add(name="gh", provider="github", value="x")
    res = await vault_client.delete(f"/v1/vault/credentials/{meta.vault_id}")
    assert res.status_code == 204
    assert meta.vault_id in vault.revoked


@pytest.mark.asyncio
async def test_rotate_missing_credential(vault_client: AsyncClient) -> None:
    res = await vault_client.post(
        "/v1/vault/credentials/vault_missing/rotate", json={}
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_rotate_initiates_new_oauth(
    monkeypatch: pytest.MonkeyPatch,
    vault_app: tuple[FastAPI, MockVault],
    vault_client: AsyncClient,
) -> None:
    monkeypatch.setenv("WAKE_OAUTH_GITHUB_CLIENT_ID", "cid")
    monkeypatch.setenv("WAKE_OAUTH_GITHUB_CLIENT_SECRET", "shh")

    _, vault = vault_app
    meta = await vault.add(name="gh", provider="github", value="x", scopes=["repo"])

    res = await vault_client.post(
        f"/v1/vault/credentials/{meta.vault_id}/rotate", json={}
    )
    assert res.status_code == 202, res.text
    body = res.json()
    assert body["provider"] == "github"
    assert "auth_url" in body


@pytest.mark.asyncio
async def test_audit_grows_with_actions(
    monkeypatch: pytest.MonkeyPatch,
    vault_app: tuple[FastAPI, MockVault],
    vault_client: AsyncClient,
) -> None:
    monkeypatch.setenv("WAKE_OAUTH_GITHUB_CLIENT_ID", "cid")
    monkeypatch.setenv("WAKE_OAUTH_GITHUB_CLIENT_SECRET", "shh")

    _, vault = vault_app
    meta = await vault.add(name="gh", provider="github", value="x")
    await vault_client.delete(f"/v1/vault/credentials/{meta.vault_id}")
    await vault_client.post(
        "/v1/vault/oauth/start", json={"provider": "github"}
    )

    res = await vault_client.get("/v1/vault/audit")
    assert res.status_code == 200
    entries = res.json()["data"]
    # Two events: revoked + oauth_start. (add() doesn't go through the
    # route, so it's not in the route-level audit.)
    decisions = [e["decision"] for e in entries]
    assert "revoked" in decisions
    assert "oauth_start" in decisions


@pytest.mark.asyncio
async def test_audit_filter_by_decision(
    monkeypatch: pytest.MonkeyPatch,
    vault_app: tuple[FastAPI, MockVault],
    vault_client: AsyncClient,
) -> None:
    monkeypatch.setenv("WAKE_OAUTH_GITHUB_CLIENT_ID", "cid")
    monkeypatch.setenv("WAKE_OAUTH_GITHUB_CLIENT_SECRET", "shh")

    _, vault = vault_app
    meta = await vault.add(name="gh", provider="github", value="x")
    await vault_client.delete(f"/v1/vault/credentials/{meta.vault_id}")
    await vault_client.post(
        "/v1/vault/oauth/start", json={"provider": "github"}
    )

    res = await vault_client.get("/v1/vault/audit", params={"decision": "revoked"})
    assert res.status_code == 200
    entries = res.json()["data"]
    assert all(e["decision"] == "revoked" for e in entries)
    assert len(entries) >= 1
