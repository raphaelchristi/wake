"""API tests for ``/v1/users`` CRUD + role assignment.

These tests run with ``WAKE_RBAC_ENABLED=true`` so the admin gate
exercises the real ``require_role(Role.ADMIN)`` dependency. An admin
seed user is created directly via the store before each test, then
the API client carries the ``X-Wake-User-Id`` header.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from wake.rbac import Role

if TYPE_CHECKING:
    from httpx import AsyncClient

    from tests.unit.fakes import InMemoryUserStore


ADMIN_ID = "admin1"
VIEWER_ID = "viewer1"
WORKSPACE = "default"


def _headers(user_id: str = ADMIN_ID, workspace_id: str = WORKSPACE) -> dict[str, str]:
    return {
        "X-Wake-User-Id": user_id,
        "X-Wake-Workspace-Id": workspace_id,
        "X-Wake-Organization-Id": "default",
    }


@pytest.fixture(autouse=True)
def _enable_rbac(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WAKE_RBAC_ENABLED", "true")


@pytest.fixture
async def seeded_users(app_components: dict[str, object]) -> InMemoryUserStore:
    """Pre-create an admin and a viewer so we can authenticate."""
    store: InMemoryUserStore = app_components["user_store"]  # type: ignore[assignment]
    await store.create(ADMIN_ID, display_name="Admin", workspace_id=WORKSPACE)
    await store.assign_role(ADMIN_ID, Role.ADMIN, workspace_id=WORKSPACE)
    await store.create(VIEWER_ID, display_name="Viewer", workspace_id=WORKSPACE)
    await store.assign_role(VIEWER_ID, Role.VIEWER, workspace_id=WORKSPACE)
    return store


# ---------------------------------------------------------------------------
# Create / list / get
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_can_create_user(
    client: AsyncClient,
    seeded_users: InMemoryUserStore,
) -> None:
    res = await client.post(
        "/v1/users",
        headers=_headers(),
        json={"id": "bob", "display_name": "Bob", "roles": ["operator"]},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["id"] == "bob"
    assert body["display_name"] == "Bob"
    assert body["roles"] == ["operator"]
    assert body["workspace_id"] == WORKSPACE


@pytest.mark.asyncio
async def test_admin_can_list_users(
    client: AsyncClient,
    seeded_users: InMemoryUserStore,
) -> None:
    res = await client.get("/v1/users", headers=_headers())
    assert res.status_code == 200
    ids = [u["id"] for u in res.json()["data"]]
    assert ADMIN_ID in ids and VIEWER_ID in ids


@pytest.mark.asyncio
async def test_admin_can_get_user(
    client: AsyncClient,
    seeded_users: InMemoryUserStore,
) -> None:
    res = await client.get(f"/v1/users/{VIEWER_ID}", headers=_headers())
    assert res.status_code == 200
    assert res.json()["id"] == VIEWER_ID
    assert "viewer" in res.json()["roles"]


@pytest.mark.asyncio
async def test_get_missing_user_returns_404(
    client: AsyncClient,
    seeded_users: InMemoryUserStore,
) -> None:
    res = await client.get("/v1/users/ghost", headers=_headers())
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_create_duplicate_returns_409(
    client: AsyncClient,
    seeded_users: InMemoryUserStore,
) -> None:
    res = await client.post(
        "/v1/users",
        headers=_headers(),
        json={"id": ADMIN_ID, "display_name": "dup"},
    )
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_create_reserved_id_returns_400(
    client: AsyncClient,
    seeded_users: InMemoryUserStore,
) -> None:
    res = await client.post(
        "/v1/users",
        headers=_headers(),
        json={"id": "system"},
    )
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# Update / delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_can_update_display_name(
    client: AsyncClient,
    seeded_users: InMemoryUserStore,
) -> None:
    res = await client.patch(
        f"/v1/users/{VIEWER_ID}",
        headers=_headers(),
        json={"display_name": "Alice Updated"},
    )
    assert res.status_code == 200
    assert res.json()["display_name"] == "Alice Updated"


@pytest.mark.asyncio
async def test_admin_can_delete_user(
    client: AsyncClient,
    seeded_users: InMemoryUserStore,
) -> None:
    res = await client.delete(f"/v1/users/{VIEWER_ID}", headers=_headers())
    assert res.status_code == 204
    # Confirm gone.
    res2 = await client.get(f"/v1/users/{VIEWER_ID}", headers=_headers())
    assert res2.status_code == 404


# ---------------------------------------------------------------------------
# Role assign / revoke
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_can_assign_role(
    client: AsyncClient,
    seeded_users: InMemoryUserStore,
) -> None:
    res = await client.post(
        f"/v1/users/{VIEWER_ID}/roles",
        headers=_headers(),
        json={"role": "operator"},
    )
    assert res.status_code == 200
    assert set(res.json()["roles"]) == {"operator", "viewer"}


@pytest.mark.asyncio
async def test_role_assign_idempotent(
    client: AsyncClient,
    seeded_users: InMemoryUserStore,
) -> None:
    """Assigning the same role twice is a 200 no-op."""
    for _ in range(2):
        res = await client.post(
            f"/v1/users/{VIEWER_ID}/roles",
            headers=_headers(),
            json={"role": "viewer"},
        )
        assert res.status_code == 200
    assert res.json()["roles"] == ["viewer"]


@pytest.mark.asyncio
async def test_admin_can_revoke_role(
    client: AsyncClient,
    seeded_users: InMemoryUserStore,
) -> None:
    res = await client.delete(
        f"/v1/users/{VIEWER_ID}/roles/viewer",
        headers=_headers(),
    )
    assert res.status_code == 200
    assert res.json()["roles"] == []


@pytest.mark.asyncio
async def test_revoke_missing_user_returns_404(
    client: AsyncClient,
    seeded_users: InMemoryUserStore,
) -> None:
    res = await client.delete(
        "/v1/users/ghost/roles/viewer",
        headers=_headers(),
    )
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# /me
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_me_returns_caller(
    client: AsyncClient,
    seeded_users: InMemoryUserStore,
) -> None:
    res = await client.get("/v1/users/me", headers=_headers(user_id=VIEWER_ID))
    assert res.status_code == 200
    assert res.json()["id"] == VIEWER_ID
    assert res.json()["roles"] == ["viewer"]


# ---------------------------------------------------------------------------
# Non-admin denial
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_viewer_cannot_create_user(
    client: AsyncClient,
    seeded_users: InMemoryUserStore,
) -> None:
    res = await client.post(
        "/v1/users",
        headers=_headers(user_id=VIEWER_ID),
        json={"id": "newone"},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_viewer_cannot_list_users(
    client: AsyncClient,
    seeded_users: InMemoryUserStore,
) -> None:
    res = await client.get("/v1/users", headers=_headers(user_id=VIEWER_ID))
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_viewer_cannot_revoke_role(
    client: AsyncClient,
    seeded_users: InMemoryUserStore,
) -> None:
    res = await client.delete(
        f"/v1/users/{VIEWER_ID}/roles/viewer",
        headers=_headers(user_id=VIEWER_ID),
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Workspace isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_in_workspace_a_cannot_act_on_workspace_b(
    client: AsyncClient,
    seeded_users: InMemoryUserStore,
) -> None:
    # Admin only seeded in WORKSPACE; calling against another workspace
    # surfaces as 401 (user is unknown there).
    res = await client.post(
        "/v1/users",
        headers=_headers(workspace_id="other"),
        json={"id": "bob"},
    )
    assert res.status_code == 401
