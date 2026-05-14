"""Tests for the vault routes (mocked adapter)."""

from __future__ import annotations

from datetime import UTC, datetime
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
        organization_id: str = "default",
        workspace_id: str = "default",
    ) -> None:
        self.vault_id = vault_id
        self.name = name
        self.provider = provider
        self.scopes = scopes
        self.created_at = created_at
        self.expires_at = None
        self.metadata: dict[str, Any] = {}
        self.organization_id = organization_id
        self.workspace_id = workspace_id


class MockVault:
    """In-process stand-in for a real ``VaultAdapter`` implementation.

    Tenant-aware (Phase 6.1 finding #1): ``list/get_metadata/revoke``
    filter by ``organization_id`` + ``workspace_id``. ``add`` records
    the tenant claim. Cross-tenant ``get_metadata`` raises ``KeyError``
    so the route can surface 404; cross-tenant ``revoke`` is a silent
    no-op (matches the InfisicalVault contract).
    """

    def __init__(self) -> None:
        self.items: dict[str, _MockCredMeta] = {}
        self.add_calls: list[tuple[str, str, str]] = []
        self.replace_calls: list[tuple[str, str]] = []  # (old_vault_id, new_value)
        self.revoked: list[str] = []

    def _matches(
        self, item: _MockCredMeta, organization_id: str, workspace_id: str
    ) -> bool:
        return (
            item.organization_id == organization_id
            and item.workspace_id == workspace_id
        )

    async def list(  # noqa: A003
        self,
        *,
        organization_id: str = "default",
        workspace_id: str = "default",
    ) -> list[_MockCredMeta]:
        return [
            i
            for i in self.items.values()
            if self._matches(i, organization_id, workspace_id)
        ]

    async def add(
        self,
        name: str,
        provider: str,
        value: str,
        scopes: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        *,
        organization_id: str = "default",
        workspace_id: str = "default",
    ) -> _MockCredMeta:
        vault_id = f"vault_{len(self.items) + len(self.replace_calls) + 1}"
        meta = _MockCredMeta(
            vault_id=vault_id,
            name=name,
            provider=provider,
            scopes=list(scopes or []),
            created_at=datetime.now(UTC),
            organization_id=organization_id,
            workspace_id=workspace_id,
        )
        if metadata:
            meta.metadata = dict(metadata)
        self.items[vault_id] = meta
        self.add_calls.append((name, provider, value))
        return meta

    async def replace(
        self,
        vault_id: str,
        value: str,
        *,
        name: str | None = None,
        provider: str | None = None,
        scopes: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        organization_id: str = "default",
        workspace_id: str = "default",
    ) -> _MockCredMeta:
        # Mirror the InfisicalVault.replace contract: add new, revoke old.
        # Tenant-scoped — cross-tenant replace ignores the old entry
        # (treated as missing) and still produces a new one.
        old = self.items.get(vault_id)
        if old is not None and not self._matches(old, organization_id, workspace_id):
            old = None
        effective_name = name or (old.name if old else f"cred_{len(self.items) + 1}")
        effective_provider = provider or (old.provider if old else "custom")
        effective_scopes = (
            scopes if scopes is not None else (list(old.scopes) if old else [])
        )
        effective_metadata: dict[str, Any] = dict(old.metadata) if old else {}
        if metadata:
            effective_metadata.update(metadata)
        effective_metadata.setdefault("rotated_from", vault_id)

        new = await self.add(
            name=effective_name,
            provider=effective_provider,
            value=value,
            scopes=effective_scopes,
            metadata=effective_metadata,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )
        # Revoke old (idempotent).
        if old is not None:
            self.revoked.append(vault_id)
            self.items.pop(vault_id, None)
        self.replace_calls.append((vault_id, value))
        return new

    async def get_metadata(
        self,
        vault_id: str,
        *,
        organization_id: str = "default",
        workspace_id: str = "default",
    ) -> _MockCredMeta:
        item = self.items.get(vault_id)
        if item is None or not self._matches(item, organization_id, workspace_id):
            raise KeyError(vault_id)
        return item

    async def revoke(
        self,
        vault_id: str,
        *,
        organization_id: str = "default",
        workspace_id: str = "default",
    ) -> None:
        item = self.items.get(vault_id)
        if item is None or not self._matches(item, organization_id, workspace_id):
            return  # cross-tenant or missing → silent no-op
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
    # Phase 5.1: state is now a signed token; bogus/legacy values fall into
    # the "invalid or expired OAuth state" bucket.
    assert "invalid or expired OAuth state" in res.text


@pytest.mark.asyncio
async def test_oauth_callback_with_expired_state_returns_400(
    monkeypatch: pytest.MonkeyPatch,
    vault_client: AsyncClient,
) -> None:
    from wake.api import oauth_state as oauth_state_mod

    monkeypatch.setenv("WAKE_OAUTH_STATE_SECRET", "shared-secret-x")
    oauth_state_mod._reset_secret_cache()
    try:
        # Sign a state with a 1-second TTL, then freeze time forward.
        token = oauth_state_mod.sign_state({"provider": "github"}, ttl_seconds=1)
        import time as _time

        real_time = _time.time

        def fake_time() -> float:
            return real_time() + 30

        _time.time = fake_time  # type: ignore[assignment]
        try:
            res = await vault_client.get(
                "/v1/vault/oauth/callback",
                params={"code": "c", "state": token},
            )
            assert res.status_code == 400
            assert "expired" in res.text
        finally:
            _time.time = real_time  # type: ignore[assignment]
    finally:
        oauth_state_mod._reset_secret_cache()


@pytest.mark.asyncio
async def test_oauth_callback_with_invalid_state_returns_400(
    monkeypatch: pytest.MonkeyPatch,
    vault_client: AsyncClient,
) -> None:
    from wake.api import oauth_state as oauth_state_mod

    monkeypatch.setenv("WAKE_OAUTH_STATE_SECRET", "real-secret")
    oauth_state_mod._reset_secret_cache()
    try:
        good = oauth_state_mod.sign_state({"provider": "github"}, secret="other-secret")
        res = await vault_client.get(
            "/v1/vault/oauth/callback",
            params={"code": "c", "state": good},
        )
        assert res.status_code == 400
        assert "signature mismatch" in res.text
    finally:
        oauth_state_mod._reset_secret_cache()


@pytest.mark.asyncio
async def test_oauth_callback_happy_path(
    monkeypatch: pytest.MonkeyPatch,
    vault_app: tuple[FastAPI, MockVault],
    vault_client: AsyncClient,
) -> None:
    monkeypatch.setenv("WAKE_OAUTH_GITHUB_CLIENT_ID", "cid")
    monkeypatch.setenv("WAKE_OAUTH_GITHUB_CLIENT_SECRET", "secret")

    # Patch ``OAuthFlow.exchange_code`` at the class level — with stateless
    # state, the flow object that handles the callback is freshly built in
    # the route, so we can't grab it via app_state anymore.
    from wake_vault_infisical.oauth import OAuthFlow

    async def fake_exchange(self: OAuthFlow, code: str, state: str | None = None) -> dict[str, Any]:  # noqa: ARG001
        return {"access_token": "ghp_abc123", "scope": "repo"}

    monkeypatch.setattr(OAuthFlow, "exchange_code", fake_exchange)

    # Start flow.
    res = await vault_client.post(
        "/v1/vault/oauth/start", json={"provider": "github", "scopes": ["repo"]}
    )
    assert res.status_code == 200
    state = res.json()["state"]
    assert "." in state  # signed token shape: blob.sig

    _, vault = vault_app

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
    # And NOT a replace (no rotate).
    assert len(vault.replace_calls) == 0


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
    # The returned state is a signed token; decoding it should reveal
    # ``vault_id_to_rotate`` so the callback can route to vault.replace.
    from wake.api.oauth_state import verify_state

    decoded = verify_state(body["state"])
    assert decoded["vault_id_to_rotate"] == meta.vault_id
    assert decoded["provider"] == "github"
    assert decoded["scopes"] == ["repo"]


@pytest.mark.asyncio
async def test_rotate_replaces_credential(
    monkeypatch: pytest.MonkeyPatch,
    vault_app: tuple[FastAPI, MockVault],
    vault_client: AsyncClient,
) -> None:
    """End-to-end rotate: callback after rotate-start must invoke replace."""
    monkeypatch.setenv("WAKE_OAUTH_GITHUB_CLIENT_ID", "cid")
    monkeypatch.setenv("WAKE_OAUTH_GITHUB_CLIENT_SECRET", "shh")

    from wake_vault_infisical.oauth import OAuthFlow

    async def fake_exchange(self: OAuthFlow, code: str, state: str | None = None) -> dict[str, Any]:  # noqa: ARG001
        return {"access_token": "ghp_NEW_token_xyz", "scope": "repo"}

    monkeypatch.setattr(OAuthFlow, "exchange_code", fake_exchange)

    app, vault = vault_app
    old = await vault.add(name="gh", provider="github", value="OLD_token", scopes=["repo"])

    # Step 1: kick rotate.
    res = await vault_client.post(
        f"/v1/vault/credentials/{old.vault_id}/rotate", json={}
    )
    assert res.status_code == 202, res.text
    state = res.json()["state"]

    # Step 2: simulate provider redirect to callback with the same state.
    res = await vault_client.get(
        "/v1/vault/oauth/callback",
        params={"code": "fresh-code", "state": state},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    # New credential returned.
    assert body["provider"] == "github"
    assert body["vault_id"] != old.vault_id
    # Old credential gone.
    assert old.vault_id not in vault.items
    # vault.replace was used (not vault.add).
    assert len(vault.replace_calls) == 1
    assert vault.replace_calls[0][0] == old.vault_id
    assert vault.replace_calls[0][1] == "ghp_NEW_token_xyz"
    # Old token revoked.
    assert old.vault_id in vault.revoked

    # Audit log carries both ``rotate_started`` (from rotate endpoint) and
    # ``rotated`` (from callback). Older ``oauth_success`` MUST NOT appear
    # because this is a rotate, not an initial add.
    res = await vault_client.get("/v1/vault/audit")
    decisions = [e["decision"] for e in res.json()["data"]]
    assert "rotate_started" in decisions
    assert "rotated" in decisions
    assert "oauth_success" not in decisions


@pytest.mark.asyncio
async def test_oauth_callback_works_across_replicas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A state issued by replica A is accepted by replica B (shared secret)."""
    monkeypatch.setenv("WAKE_OAUTH_GITHUB_CLIENT_ID", "cid")
    monkeypatch.setenv("WAKE_OAUTH_GITHUB_CLIENT_SECRET", "shh")
    monkeypatch.setenv("WAKE_OAUTH_STATE_SECRET", "shared-secret-across-replicas")

    from wake.api import oauth_state as oauth_state_mod

    oauth_state_mod._reset_secret_cache()

    from wake_vault_infisical.oauth import OAuthFlow

    async def fake_exchange(self: OAuthFlow, code: str, state: str | None = None) -> dict[str, Any]:  # noqa: ARG001
        return {"access_token": "ghp_replicaB_token", "scope": "repo"}

    monkeypatch.setattr(OAuthFlow, "exchange_code", fake_exchange)

    from wake.api.app import create_app

    try:
        # --- Replica A: start the flow ---------------------------------
        vault_a = MockVault()
        app_a = create_app(vault=vault_a)
        transport_a = ASGITransport(app=app_a)
        async with AsyncClient(transport=transport_a, base_url="http://a") as client_a:
            res = await client_a.post(
                "/v1/vault/oauth/start", json={"provider": "github"}
            )
            assert res.status_code == 200
            state = res.json()["state"]

        # --- Replica B: handle the callback ----------------------------
        vault_b = MockVault()
        app_b = create_app(vault=vault_b)
        transport_b = ASGITransport(app=app_b)
        async with AsyncClient(transport=transport_b, base_url="http://b") as client_b:
            res = await client_b.get(
                "/v1/vault/oauth/callback",
                params={"code": "c", "state": state},
            )
            assert res.status_code == 200, res.text
            body = res.json()
            assert body["provider"] == "github"

        # Vault on replica B saw the add; replica A never did.
        assert len(vault_b.add_calls) == 1
        assert len(vault_a.add_calls) == 0
    finally:
        oauth_state_mod._reset_secret_cache()


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
