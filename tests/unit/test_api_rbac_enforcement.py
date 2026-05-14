"""Cross-route RBAC enforcement matrix.

For every authenticated route we care about, this suite walks each
role and asserts the status code class:

* Admin: 2xx on every route.
* Operator: 2xx on writes that allow it (agents/sessions/events
  writes); 403 on admin-only routes (vault rotate, users CRUD).
* Viewer: 403 on any write; 2xx (or 404 when target missing) on
  reads.

The matrix lives as a parameterized test so adding a new gated route
is a single-line entry. Every case is wired to a real route handler;
this gives confidence that the contract decorators are present (a
common regression vector — easy to forget the decorator on new
routes).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from wake.rbac import Role

if TYPE_CHECKING:
    from httpx import AsyncClient

    from tests.unit.fakes import InMemoryAgentStore, InMemoryUserStore


WORKSPACE = "default"


def _headers(user_id: str) -> dict[str, str]:
    return {
        "X-Wake-User-Id": user_id,
        "X-Wake-Workspace-Id": WORKSPACE,
        "X-Wake-Organization-Id": "default",
    }


@pytest.fixture(autouse=True)
def _enable_rbac(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WAKE_RBAC_ENABLED", "true")


@pytest.fixture
async def seeded(app_components: dict[str, Any]) -> dict[str, Any]:
    """Seed one user per role + a baseline agent so reads have data."""
    users: InMemoryUserStore = app_components["user_store"]
    for uid, role in (
        ("admin1", Role.ADMIN),
        ("operator1", Role.OPERATOR),
        ("viewer1", Role.VIEWER),
    ):
        await users.create(uid, workspace_id=WORKSPACE)
        await users.assign_role(uid, role, workspace_id=WORKSPACE)

    # A baseline agent visible to every read.
    agents: InMemoryAgentStore = app_components["agent_store"]
    agent = await agents.create(
        name="seed",
        model={"id": "claude-opus-4-7"},  # type: ignore[arg-type]
        workspace_id=WORKSPACE,
        organization_id="default",
    )
    return {"agent_id": agent.id, "user_store": users}


# Matrix of route × method × expected status per role. Status entries
# are tuples ``(2xx-like-bound, 4xx-on-mismatch)`` — we accept any 2xx
# when the role is allowed, and exactly 403 when forbidden. Some reads
# accept 200/404 (404 when the resource id we use does not exist).
ROLES = ("admin1", "operator1", "viewer1")


def _admin_only_status(role: str) -> int:
    return 403 if role != "admin1" else 200


def _write_status(role: str) -> int:
    return 403 if role == "viewer1" else 200


# Reads — admin/operator/viewer all allowed; admin/operator/viewer
# all get 2xx (with empty body where applicable).
@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_read_agents_allowed_for_all_roles(
    client: AsyncClient,
    seeded: dict[str, Any],
    role: str,
) -> None:
    res = await client.get("/v1/agents", headers=_headers(role))
    assert res.status_code == 200, role


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_read_environments_allowed_for_all_roles(
    client: AsyncClient,
    seeded: dict[str, Any],
    role: str,
) -> None:
    res = await client.get("/v1/environments", headers=_headers(role))
    assert res.status_code == 200, role


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_read_sessions_allowed_for_all_roles(
    client: AsyncClient,
    seeded: dict[str, Any],
    role: str,
) -> None:
    res = await client.get("/v1/sessions", headers=_headers(role))
    assert res.status_code == 200, role


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_metrics_allowed_for_all_roles(
    client: AsyncClient,
    seeded: dict[str, Any],
    role: str,
) -> None:
    res = await client.get("/v1/metrics/summary", headers=_headers(role))
    assert res.status_code == 200, role


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_workers_allowed_for_all_roles(
    client: AsyncClient,
    seeded: dict[str, Any],
    role: str,
) -> None:
    res = await client.get("/v1/workers", headers=_headers(role))
    assert res.status_code == 200, role


# ---------------------------------------------------------------------------
# Writes: agents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_create_agent_role_gate(
    client: AsyncClient,
    seeded: dict[str, Any],
    role: str,
) -> None:
    res = await client.post(
        "/v1/agents",
        headers=_headers(role),
        json={"name": "gated", "model": {"id": "claude-opus-4-7"}},
    )
    expected = 201 if role != "viewer1" else 403
    assert res.status_code == expected, (role, res.text)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_patch_agent_role_gate(
    client: AsyncClient,
    seeded: dict[str, Any],
    role: str,
) -> None:
    res = await client.patch(
        f"/v1/agents/{seeded['agent_id']}",
        headers=_headers(role),
        json={"system": f"by-{role}"},
    )
    expected = 200 if role != "viewer1" else 403
    assert res.status_code == expected, (role, res.text)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_archive_agent_role_gate(
    client: AsyncClient,
    seeded: dict[str, Any],
    role: str,
) -> None:
    res = await client.post(
        f"/v1/agents/{seeded['agent_id']}/archive",
        headers=_headers(role),
    )
    if role == "viewer1":
        assert res.status_code == 403
    else:
        assert res.status_code in (200, 404), (role, res.text)


# ---------------------------------------------------------------------------
# Writes: environments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_create_environment_role_gate(
    client: AsyncClient,
    seeded: dict[str, Any],
    role: str,
) -> None:
    res = await client.post(
        "/v1/environments",
        headers=_headers(role),
        json={"name": "env-x", "config": {}},
    )
    expected = 201 if role != "viewer1" else 403
    assert res.status_code == expected, (role, res.text)


# ---------------------------------------------------------------------------
# Writes: sessions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_create_session_role_gate(
    client: AsyncClient,
    seeded: dict[str, Any],
    role: str,
) -> None:
    res = await client.post(
        "/v1/sessions",
        headers=_headers(role),
        json={"agent_id": seeded["agent_id"]},
    )
    if role == "viewer1":
        assert res.status_code == 403
    else:
        assert res.status_code == 201, (role, res.text)


# ---------------------------------------------------------------------------
# Vault — admin only on writes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_vault_rotate_admin_only(
    client: AsyncClient,
    seeded: dict[str, Any],
    role: str,
) -> None:
    # No vault wired in tests, but the role gate runs first. Admin
    # gets through to 503; non-admin gets 403.
    res = await client.post(
        "/v1/vault/credentials/abc/rotate",
        headers=_headers(role),
        json={},
    )
    if role == "admin1":
        assert res.status_code == 503  # vault not configured
    else:
        assert res.status_code == 403, (role, res.text)


# ---------------------------------------------------------------------------
# Users CRUD — admin only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_users_list_admin_only(
    client: AsyncClient,
    seeded: dict[str, Any],
    role: str,
) -> None:
    res = await client.get("/v1/users", headers=_headers(role))
    expected = 200 if role == "admin1" else 403
    assert res.status_code == expected, (role, res.text)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_users_create_admin_only(
    client: AsyncClient,
    seeded: dict[str, Any],
    role: str,
) -> None:
    res = await client.post(
        "/v1/users",
        headers=_headers(role),
        json={"id": f"new-{role}"},
    )
    expected = 201 if role == "admin1" else 403
    assert res.status_code == expected, (role, res.text)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_users_assign_role_admin_only(
    client: AsyncClient,
    seeded: dict[str, Any],
    role: str,
) -> None:
    res = await client.post(
        "/v1/users/viewer1/roles",
        headers=_headers(role),
        json={"role": "operator"},
    )
    expected = 200 if role == "admin1" else 403
    assert res.status_code == expected, (role, res.text)


# ---------------------------------------------------------------------------
# /me — open to every authenticated principal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ROLES)
async def test_me_open_to_all_roles(
    client: AsyncClient,
    seeded: dict[str, Any],
    role: str,
) -> None:
    res = await client.get("/v1/users/me", headers=_headers(role))
    assert res.status_code == 200, role
    assert res.json()["id"] == role


# ---------------------------------------------------------------------------
# Backward-compat: with RBAC off, every endpoint behaves like Phase 5
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rbac_off_back_compat(
    client: AsyncClient,
    app_components: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With RBAC off (no header), writes succeed under system user."""
    monkeypatch.setenv("WAKE_RBAC_ENABLED", "false")
    res = await client.post(
        "/v1/agents",
        headers={"X-Wake-Workspace-Id": WORKSPACE},
        json={"name": "compat", "model": {"id": "claude-opus-4-7"}},
    )
    assert res.status_code == 201
