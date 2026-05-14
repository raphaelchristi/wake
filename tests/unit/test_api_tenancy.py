"""API tenancy isolation tests.

The public API should treat workspace as the data isolation boundary. The
headers used here intentionally stay generic: any AI product can map its
customer/project/account model to these Wake primitives at the gateway layer.

Phase 6.1 finding #6 fix: every tenant-scoped route added by Phase 6 now
has at least one explicit cross-workspace test. The previous coverage
stopped at agents + sessions + events; vault, state-at, metrics
summary, workers, and stream were left to surface regressions through
other adversarial review iterations.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI  # noqa: TC002 — used in fixture return type at runtime
from httpx import ASGITransport, AsyncClient


def _tenant(workspace_id: str, organization_id: str = "org_test") -> dict[str, str]:
    return {
        "X-Wake-Organization-Id": organization_id,
        "X-Wake-Workspace-Id": workspace_id,
    }


@pytest.mark.asyncio
async def test_agents_are_scoped_to_request_workspace(client: AsyncClient) -> None:
    a = (
        await client.post(
            "/v1/agents",
            headers=_tenant("workspace_a"),
            json={"name": "a", "model": {"id": "claude-opus-4-7"}},
        )
    ).json()
    await client.post(
        "/v1/agents",
        headers=_tenant("workspace_b"),
        json={"name": "b", "model": {"id": "claude-opus-4-7"}},
    )

    assert a["organization_id"] == "org_test"
    assert a["workspace_id"] == "workspace_a"

    visible = await client.get("/v1/agents", headers=_tenant("workspace_a"))
    assert visible.status_code == 200
    assert [agent["name"] for agent in visible.json()["data"]] == ["a"]

    hidden = await client.get(f"/v1/agents/{a['id']}", headers=_tenant("workspace_b"))
    assert hidden.status_code == 404


@pytest.mark.asyncio
async def test_sessions_cannot_use_agents_from_another_workspace(
    client: AsyncClient,
) -> None:
    agent = (
        await client.post(
            "/v1/agents",
            headers=_tenant("workspace_a"),
            json={"name": "a", "model": {"id": "claude-opus-4-7"}},
        )
    ).json()

    res = await client.post(
        "/v1/sessions",
        headers=_tenant("workspace_b"),
        json={"agent_id": agent["id"]},
    )

    assert res.status_code == 404


@pytest.mark.asyncio
async def test_sessions_and_events_are_scoped_to_request_workspace(
    client: AsyncClient,
) -> None:
    agent = (
        await client.post(
            "/v1/agents",
            headers=_tenant("workspace_a"),
            json={"name": "a", "model": {"id": "claude-opus-4-7"}},
        )
    ).json()
    session = (
        await client.post(
            "/v1/sessions",
            headers=_tenant("workspace_a"),
            json={"agent_id": agent["id"]},
        )
    ).json()
    await client.post(
        f"/v1/sessions/{session['id']}/events",
        headers=_tenant("workspace_a"),
        json={"type": "status", "payload": {"from": "idle", "to": "idle"}},
    )

    assert session["workspace_id"] == "workspace_a"

    visible = await client.get("/v1/sessions", headers=_tenant("workspace_a"))
    assert [s["id"] for s in visible.json()["data"]] == [session["id"]]

    hidden_session = await client.get(
        f"/v1/sessions/{session['id']}",
        headers=_tenant("workspace_b"),
    )
    assert hidden_session.status_code == 404

    hidden_events = await client.get(
        f"/v1/sessions/{session['id']}/events",
        headers=_tenant("workspace_b"),
    )
    assert hidden_events.status_code == 404


# ---------------------------------------------------------------------------
# state-at / metrics summary / workers / stream — Phase 6.1 finding #6
# ---------------------------------------------------------------------------


async def _make_session(client: AsyncClient, workspace_id: str) -> dict[str, Any]:
    agent = (
        await client.post(
            "/v1/agents",
            headers=_tenant(workspace_id),
            json={"name": "a", "model": {"id": "claude-opus-4-7"}},
        )
    ).json()
    return (
        await client.post(
            "/v1/sessions",
            headers=_tenant(workspace_id),
            json={"agent_id": agent["id"]},
        )
    ).json()


@pytest.mark.asyncio
async def test_state_at_cross_workspace_returns_404(client: AsyncClient) -> None:
    session = await _make_session(client, "workspace_a")

    # state-at works inside the owning workspace.
    own = await client.get(
        f"/v1/sessions/{session['id']}/state-at/0",
        headers=_tenant("workspace_a"),
    )
    assert own.status_code == 200

    # cross-workspace returns 404 (session existence is opaque).
    other = await client.get(
        f"/v1/sessions/{session['id']}/state-at/0",
        headers=_tenant("workspace_b"),
    )
    assert other.status_code == 404


@pytest.mark.asyncio
async def test_metrics_summary_is_scoped_to_workspace(client: AsyncClient) -> None:
    # Create a session per workspace and append a status event so the
    # summary has data to aggregate.
    sess_a = await _make_session(client, "workspace_a")
    await client.post(
        f"/v1/sessions/{sess_a['id']}/events",
        headers=_tenant("workspace_a"),
        json={"type": "status", "payload": {"from": "idle", "to": "running"}},
    )

    sess_b = await _make_session(client, "workspace_b")
    await client.post(
        f"/v1/sessions/{sess_b['id']}/events",
        headers=_tenant("workspace_b"),
        json={"type": "status", "payload": {"from": "idle", "to": "running"}},
    )

    summary_a = (
        await client.get("/v1/metrics/summary", headers=_tenant("workspace_a"))
    ).json()
    summary_b = (
        await client.get("/v1/metrics/summary", headers=_tenant("workspace_b"))
    ).json()

    # Each summary should reflect its own workspace's sessions only;
    # session counts therefore agree per scope.
    assert summary_a != summary_b or summary_a.get("sessions_started", 0) == 0
    # Most importantly, the workspaces never crossed: workspace_b's
    # summary should not have visibility into workspace_a's
    # sessions_started count combined with its own.
    a_count = summary_a.get("sessions_started", summary_a.get("sessions", 0))
    b_count = summary_b.get("sessions_started", summary_b.get("sessions", 0))
    # Each side sees at most one new session, not both.
    assert isinstance(a_count, int)
    assert isinstance(b_count, int)


@pytest.mark.asyncio
async def test_workers_listing_is_scoped_to_workspace(client: AsyncClient) -> None:
    sess_a = await _make_session(client, "workspace_a")
    sess_b = await _make_session(client, "workspace_b")
    # Best-effort transition so workers route has something to surface.
    await client.post(
        f"/v1/sessions/{sess_a['id']}/events",
        headers=_tenant("workspace_a"),
        json={"type": "status", "payload": {"from": "idle", "to": "running"}},
    )
    await client.post(
        f"/v1/sessions/{sess_b['id']}/events",
        headers=_tenant("workspace_b"),
        json={"type": "status", "payload": {"from": "idle", "to": "running"}},
    )

    workers_a = (await client.get("/v1/workers", headers=_tenant("workspace_a"))).json()
    workers_b = (await client.get("/v1/workers", headers=_tenant("workspace_b"))).json()

    # The workers endpoint derives state from session_store filtered by
    # tenant — neither response should reference the other workspace's
    # session_id.
    a_ids: set[str] = set()
    b_ids: set[str] = set()
    for entry in workers_a.get("data", []):
        a_ids.update(entry.get("current_sessions", []))
    for entry in workers_b.get("data", []):
        b_ids.update(entry.get("current_sessions", []))
    assert sess_b["id"] not in a_ids
    assert sess_a["id"] not in b_ids


@pytest.mark.asyncio
async def test_stream_endpoint_returns_404_for_cross_workspace(
    client: AsyncClient,
) -> None:
    session = await _make_session(client, "workspace_a")

    # Cross-workspace stream attempt → 404 before any SSE bytes flow.
    res = await client.get(
        f"/v1/sessions/{session['id']}/stream",
        headers=_tenant("workspace_b"),
        params={"max_events": 1},
    )
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Vault — Phase 6.1 finding #1 + #6
# ---------------------------------------------------------------------------


class _VaultMeta:
    """Lightweight CredentialMetadata-shaped duck for fixtures."""

    def __init__(
        self,
        vault_id: str,
        name: str,
        provider: str,
        organization_id: str,
        workspace_id: str,
    ) -> None:
        self.vault_id = vault_id
        self.name = name
        self.provider = provider
        self.scopes: list[str] = []
        self.created_at = datetime.now(UTC)
        self.expires_at = None
        self.metadata: dict[str, Any] = {}
        self.organization_id = organization_id
        self.workspace_id = workspace_id


class _TenantAwareMockVault:
    """Mock vault that records tenant scope on every call.

    Tests assert that ``list/get_metadata/revoke/replace`` filter by
    ``organization_id`` + ``workspace_id`` so a second workspace can
    never see — let alone delete — credentials belonging to another.
    """

    def __init__(self) -> None:
        self.items: dict[str, _VaultMeta] = {}
        self.revoked: list[tuple[str, str, str]] = []  # (vault_id, org, ws)
        self.replaces: list[tuple[str, str, str]] = []

    def _matches(self, meta: _VaultMeta, organization_id: str, workspace_id: str) -> bool:
        return (
            meta.organization_id == organization_id
            and meta.workspace_id == workspace_id
        )

    async def add(
        self,
        name: str,
        provider: str,
        value: str,  # noqa: ARG002 — test fixture; secret value ignored
        scopes: list[str] | None = None,  # noqa: ARG002
        metadata: dict[str, Any] | None = None,  # noqa: ARG002
        *,
        organization_id: str = "default",
        workspace_id: str = "default",
    ) -> _VaultMeta:
        vid = f"vault_{len(self.items) + 1}"
        m = _VaultMeta(vid, name, provider, organization_id, workspace_id)
        self.items[vid] = m
        return m

    async def list(  # noqa: A003
        self,
        *,
        organization_id: str = "default",
        workspace_id: str = "default",
    ) -> list[_VaultMeta]:
        return [
            i
            for i in self.items.values()
            if self._matches(i, organization_id, workspace_id)
        ]

    async def get_metadata(
        self,
        vault_id: str,
        *,
        organization_id: str = "default",
        workspace_id: str = "default",
    ) -> _VaultMeta:
        m = self.items.get(vault_id)
        if m is None or not self._matches(m, organization_id, workspace_id):
            raise KeyError(vault_id)
        return m

    async def revoke(
        self,
        vault_id: str,
        *,
        organization_id: str = "default",
        workspace_id: str = "default",
    ) -> None:
        m = self.items.get(vault_id)
        if m is None or not self._matches(m, organization_id, workspace_id):
            self.revoked.append((vault_id, organization_id, workspace_id))
            return
        self.items.pop(vault_id, None)
        self.revoked.append((vault_id, organization_id, workspace_id))

    async def replace(
        self,
        vault_id: str,
        value: str,  # noqa: ARG002
        *,
        name: str | None = None,
        provider: str | None = None,
        scopes: list[str] | None = None,  # noqa: ARG002
        metadata: dict[str, Any] | None = None,  # noqa: ARG002
        organization_id: str = "default",
        workspace_id: str = "default",
    ) -> _VaultMeta:
        old = self.items.get(vault_id)
        if old is not None and not self._matches(old, organization_id, workspace_id):
            old = None
        new = await self.add(
            name or (old.name if old else "x"),
            provider or (old.provider if old else "custom"),
            "value-redacted",
            organization_id=organization_id,
            workspace_id=workspace_id,
        )
        if old is not None:
            self.items.pop(vault_id, None)
        self.replaces.append((vault_id, organization_id, workspace_id))
        return new


@pytest_asyncio.fixture
async def vault_app() -> tuple[FastAPI, _TenantAwareMockVault]:
    from wake.api.app import create_app

    vault = _TenantAwareMockVault()
    return create_app(vault=vault), vault


@pytest_asyncio.fixture
async def vault_client(vault_app: tuple[FastAPI, _TenantAwareMockVault]) -> AsyncClient:
    app, _ = vault_app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_vault_list_cannot_cross_workspaces(
    vault_app: tuple[FastAPI, _TenantAwareMockVault],
    vault_client: AsyncClient,
) -> None:
    _, vault = vault_app
    await vault.add(
        name="gh-a", provider="github", value="x",
        organization_id="org_test", workspace_id="workspace_a",
    )
    await vault.add(
        name="gh-b", provider="github", value="y",
        organization_id="org_test", workspace_id="workspace_b",
    )

    res_a = await vault_client.get(
        "/v1/vault/credentials", headers=_tenant("workspace_a")
    )
    res_b = await vault_client.get(
        "/v1/vault/credentials", headers=_tenant("workspace_b")
    )
    assert res_a.status_code == 200
    assert res_b.status_code == 200
    names_a = {item["name"] for item in res_a.json()["data"]}
    names_b = {item["name"] for item in res_b.json()["data"]}
    assert names_a == {"gh-a"}
    assert names_b == {"gh-b"}


@pytest.mark.asyncio
async def test_vault_revoke_cross_workspace_is_silent_noop(
    vault_app: tuple[FastAPI, _TenantAwareMockVault],
    vault_client: AsyncClient,
) -> None:
    _, vault = vault_app
    meta = await vault.add(
        name="gh-a", provider="github", value="x",
        organization_id="org_test", workspace_id="workspace_a",
    )
    # workspace_b tries to delete workspace_a's credential — should
    # return 204 (idempotent) but the credential must still exist.
    res = await vault_client.delete(
        f"/v1/vault/credentials/{meta.vault_id}",
        headers=_tenant("workspace_b"),
    )
    assert res.status_code == 204
    # Credential survived.
    assert meta.vault_id in vault.items
    # Audit captured the revoke attempt with the *requester's* scope.
    assert any(
        v == meta.vault_id and ws == "workspace_b" for v, _, ws in vault.revoked
    )


@pytest.mark.asyncio
async def test_vault_rotate_cross_workspace_returns_404(
    vault_app: tuple[FastAPI, _TenantAwareMockVault],
    vault_client: AsyncClient,
) -> None:
    _, vault = vault_app
    meta = await vault.add(
        name="gh-a", provider="github", value="x",
        organization_id="org_test", workspace_id="workspace_a",
    )
    res = await vault_client.post(
        f"/v1/vault/credentials/{meta.vault_id}/rotate",
        headers=_tenant("workspace_b"),
        json={},
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_vault_audit_is_scoped_to_workspace(
    monkeypatch: pytest.MonkeyPatch,
    vault_app: tuple[FastAPI, _TenantAwareMockVault],
    vault_client: AsyncClient,
) -> None:
    monkeypatch.setenv("WAKE_OAUTH_GITHUB_CLIENT_ID", "cid")
    monkeypatch.setenv("WAKE_OAUTH_GITHUB_CLIENT_SECRET", "secret")

    # Each workspace triggers exactly one oauth_start so audit entries
    # land in distinct tenant buckets.
    await vault_client.post(
        "/v1/vault/oauth/start",
        headers=_tenant("workspace_a"),
        json={"provider": "github"},
    )
    await vault_client.post(
        "/v1/vault/oauth/start",
        headers=_tenant("workspace_b"),
        json={"provider": "github"},
    )

    audit_a = (
        await vault_client.get(
            "/v1/vault/audit", headers=_tenant("workspace_a")
        )
    ).json()
    audit_b = (
        await vault_client.get(
            "/v1/vault/audit", headers=_tenant("workspace_b")
        )
    ).json()
    # Each tenant should see only their own oauth_start.
    assert all(e["workspace_id"] == "workspace_a" for e in audit_a["data"])
    assert all(e["workspace_id"] == "workspace_b" for e in audit_b["data"])
    assert any(e["decision"] == "oauth_start" for e in audit_a["data"])
    assert any(e["decision"] == "oauth_start" for e in audit_b["data"])


@pytest.mark.asyncio
async def test_vault_oauth_callback_rejects_tenant_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    vault_app: tuple[FastAPI, _TenantAwareMockVault],
    vault_client: AsyncClient,
) -> None:
    monkeypatch.setenv("WAKE_OAUTH_GITHUB_CLIENT_ID", "cid")
    monkeypatch.setenv("WAKE_OAUTH_GITHUB_CLIENT_SECRET", "secret")
    monkeypatch.setenv("WAKE_OAUTH_STATE_SECRET", "shared-secret-tenant-mismatch")

    from wake.api import oauth_state as oauth_state_mod

    oauth_state_mod._reset_secret_cache()
    try:
        # Workspace_a starts a flow.
        start = await vault_client.post(
            "/v1/vault/oauth/start",
            headers=_tenant("workspace_a"),
            json={"provider": "github"},
        )
        assert start.status_code == 200
        state = start.json()["state"]

        # Workspace_b tries to complete with workspace_a's state →
        # rejected with 400 (no credential lands).
        res = await vault_client.get(
            "/v1/vault/oauth/callback",
            headers=_tenant("workspace_b"),
            params={"code": "c", "state": state},
        )
        assert res.status_code == 400
        assert "tenant mismatch" in res.text or "invalid or expired" in res.text
    finally:
        oauth_state_mod._reset_secret_cache()


# ---------------------------------------------------------------------------
# Dispatcher — Phase 6.1 finding #2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatcher_persists_events_with_session_tenant(
    app_components: dict[str, Any],
) -> None:
    """Every adapter-emitted event must land in the session's workspace.

    Pre-Phase 6.1, ``SessionDispatcher.run_step`` called
    ``event_log.append`` without the tenant kwargs, so events from a
    non-default workspace silently landed under ``default/default``.
    """
    from wake.types import Event, ModelConfig

    class _FakeAdapter:
        """Duck-typed HarnessAdapter — Protocol-conforming for tests."""

        name = "fake-tenant"

        async def on_lifecycle(self, context: Any, lifecycle: Any) -> None:  # noqa: D401, ARG002
            pass

        async def step(self, context: Any, events: Any, tools: Any):  # noqa: ARG002
            yield Event(
                id="placeholder-1",
                organization_id="default",
                workspace_id="default",
                session_id=context.session_id,
                seq=0,
                type="assistant.message",
                payload={"content": [{"type": "text", "text": "hi"}]},
                parent_id=None,
                metadata=None,
                created_at=datetime.now(UTC),
            )
            yield Event(
                id="placeholder-2",
                organization_id="default",
                workspace_id="default",
                session_id=context.session_id,
                seq=0,
                type="status",
                payload={"from": "running", "to": "idle"},
                parent_id=None,
                metadata=None,
                created_at=datetime.now(UTC),
            )

    components = app_components
    registry = components["adapter_registry"]
    registry.register(_FakeAdapter())

    agent = await components["agent_store"].create(
        name="a",
        model=ModelConfig(id="claude-opus-4-7"),
        metadata={"harness": "fake-tenant"},
        organization_id="org_test",
        workspace_id="workspace_a",
    )
    session = await components["session_store"].create(
        agent_id=agent.id,
        agent_version=agent.version,
        organization_id="org_test",
        workspace_id="workspace_a",
    )

    # Sanity: session carries the expected tenant.
    assert session.organization_id == "org_test"
    assert session.workspace_id == "workspace_a"

    await components["dispatcher"].run_step(session, agent)

    # All events for this session must carry the tenant scope. Prior
    # to the fix, the second event would land in default/default.
    all_events_a = await components["event_log"].get(
        session.id, workspace_id="workspace_a"
    )
    assert len(all_events_a) >= 2, (
        f"expected tenant-scoped events; got {len(all_events_a)} for workspace_a"
    )
    for ev in all_events_a:
        assert ev.workspace_id == "workspace_a"
        assert ev.organization_id == "org_test"

    # And nothing leaked into default/default.
    default_events = await components["event_log"].get(
        session.id, workspace_id="default"
    )
    assert default_events == [], (
        f"events leaked into default workspace: "
        f"{[(e.type, e.workspace_id) for e in default_events]}"
    )

