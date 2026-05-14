"""Unit tests for the RBAC primitives.

Covers:

* ``Role`` enum + ``Role.parse`` + ``Role.permits``
* ``User`` dataclass (system sentinel, ``has_role``, ``with_roles``)
* ``is_rbac_enabled`` env var parsing
* ``require_role`` factory wiring (gate, RBAC-off pass-through, 403 on
  empty intersection, 401 when ``X-Wake-User-Id`` missing under RBAC)

These tests stay framework-light: where FastAPI is used the route is
local to the test (no global state).
"""

# ``Depends(...)`` defaults are idiomatic FastAPI (B008).
# ruff: noqa: B008

from __future__ import annotations

from typing import Any

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from tests.unit.fakes import InMemoryUserStore
from wake.api.app import create_app
from wake.api.dependencies import (
    AppState,
    get_current_user,
    require_role,
)
from wake.rbac import (
    WAKE_RBAC_ENABLED_ENV,
    Role,
    User,
    is_rbac_enabled,
)

# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------


def test_role_values_stable() -> None:
    """Role string values must not drift — they are persisted."""
    assert Role.ADMIN.value == "admin"
    assert Role.OPERATOR.value == "operator"
    assert Role.VIEWER.value == "viewer"


def test_role_parse_canonical() -> None:
    assert Role.parse("admin") is Role.ADMIN
    assert Role.parse("operator") is Role.OPERATOR
    assert Role.parse("viewer") is Role.VIEWER


def test_role_parse_case_insensitive_and_stripped() -> None:
    assert Role.parse("  ADMIN  ") is Role.ADMIN
    assert Role.parse("Viewer") is Role.VIEWER


def test_role_parse_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        Role.parse("superuser")
    with pytest.raises(ValueError):
        Role.parse("")


def test_role_permits_matrix() -> None:
    # Reads always permitted.
    for r in Role:
        assert r.permits("read")
    # Writes: admin + operator only.
    assert Role.ADMIN.permits("write")
    assert Role.OPERATOR.permits("write")
    assert not Role.VIEWER.permits("write")
    # Admin-gated actions.
    assert Role.ADMIN.permits("admin")
    assert not Role.OPERATOR.permits("admin")
    assert not Role.VIEWER.permits("admin")
    assert Role.ADMIN.permits("rotate")
    assert not Role.OPERATOR.permits("rotate")


def test_role_permits_rejects_unknown_action() -> None:
    with pytest.raises(ValueError):
        Role.ADMIN.permits("delete-everything")


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------


def test_user_system_carries_every_role() -> None:
    u = User.system()
    assert u.id == "system"
    assert set(u.roles) == set(Role)


def test_user_has_role_intersects_correctly() -> None:
    u = User(id="alice", roles=(Role.OPERATOR,))
    assert u.has_role(Role.OPERATOR)
    assert u.has_role(Role.ADMIN, Role.OPERATOR)
    assert not u.has_role(Role.ADMIN)
    assert not u.has_role()


def test_user_with_roles_returns_copy() -> None:
    u = User(id="alice", roles=())
    u2 = u.with_roles((Role.ADMIN,))
    assert u.roles == ()
    assert u2.roles == (Role.ADMIN,)
    assert u2.id == "alice"


# ---------------------------------------------------------------------------
# is_rbac_enabled
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1", True),
        ("true", True),
        ("YES", True),
        (" on ", True),
        ("0", False),
        ("false", False),
        ("", False),
        ("maybe", False),
    ],
)
def test_is_rbac_enabled_parses(monkeypatch: pytest.MonkeyPatch, raw: str, expected: bool) -> None:
    monkeypatch.setenv(WAKE_RBAC_ENABLED_ENV, raw)
    assert is_rbac_enabled() is expected


def test_is_rbac_enabled_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(WAKE_RBAC_ENABLED_ENV, raising=False)
    assert is_rbac_enabled() is False


# ---------------------------------------------------------------------------
# require_role factory
# ---------------------------------------------------------------------------


def test_require_role_without_args_raises() -> None:
    with pytest.raises(ValueError):
        require_role()


# A tiny FastAPI app pinned per test so RBAC env mutations don't bleed.
def _build_user_app(user_store: InMemoryUserStore) -> FastAPI:
    app = create_app(user_store=user_store)
    app.state.wake = AppState(user_store=user_store)
    # Mount a probe route that uses the require_role + get_current_user
    # dependencies. Keeps the test focused on the gate, not a full
    # business route.
    @app.get("/probe/operator-or-admin")
    async def probe_op(
        user: User = Depends(require_role(Role.ADMIN, Role.OPERATOR)),
    ) -> dict[str, Any]:
        return {"user_id": user.id, "roles": [r.value for r in user.roles]}

    @app.get("/probe/admin-only")
    async def probe_admin(
        user: User = Depends(require_role(Role.ADMIN)),
    ) -> dict[str, Any]:
        return {"user_id": user.id}

    @app.get("/probe/me")
    async def probe_me(user: User = Depends(get_current_user)) -> dict[str, Any]:
        return {"user_id": user.id, "roles": [r.value for r in user.roles]}

    return app


@pytest.mark.asyncio
async def test_rbac_off_pass_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(WAKE_RBAC_ENABLED_ENV, raising=False)
    app = _build_user_app(InMemoryUserStore())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/probe/admin-only")
    # With RBAC off, system user passes every gate without a header.
    assert r.status_code == 200
    assert r.json()["user_id"] == "system"


@pytest.mark.asyncio
async def test_rbac_on_requires_user_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(WAKE_RBAC_ENABLED_ENV, "true")
    app = _build_user_app(InMemoryUserStore())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/probe/admin-only")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_rbac_on_unknown_user_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(WAKE_RBAC_ENABLED_ENV, "true")
    store = InMemoryUserStore()
    app = _build_user_app(store)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(
            "/probe/admin-only",
            headers={"X-Wake-User-Id": "ghost"},
        )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_rbac_on_admin_passes_admin_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(WAKE_RBAC_ENABLED_ENV, "true")
    store = InMemoryUserStore()
    await store.create("alice", workspace_id="default")
    await store.assign_role("alice", Role.ADMIN, workspace_id="default")
    app = _build_user_app(store)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(
            "/probe/admin-only",
            headers={"X-Wake-User-Id": "alice"},
        )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_rbac_on_viewer_forbidden_on_admin_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(WAKE_RBAC_ENABLED_ENV, "true")
    store = InMemoryUserStore()
    await store.create("bob", workspace_id="default")
    await store.assign_role("bob", Role.VIEWER, workspace_id="default")
    app = _build_user_app(store)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(
            "/probe/admin-only",
            headers={"X-Wake-User-Id": "bob"},
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_rbac_on_operator_passes_operator_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(WAKE_RBAC_ENABLED_ENV, "true")
    store = InMemoryUserStore()
    await store.create("carol", workspace_id="default")
    await store.assign_role("carol", Role.OPERATOR, workspace_id="default")
    app = _build_user_app(store)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(
            "/probe/operator-or-admin",
            headers={"X-Wake-User-Id": "carol"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "carol"
    assert "operator" in body["roles"]


@pytest.mark.asyncio
async def test_rbac_on_workspace_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    """A user in workspace A cannot authenticate in workspace B."""
    monkeypatch.setenv(WAKE_RBAC_ENABLED_ENV, "true")
    store = InMemoryUserStore()
    await store.create("dave", workspace_id="workspace_a")
    await store.assign_role("dave", Role.ADMIN, workspace_id="workspace_a")
    app = _build_user_app(store)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        ok = await ac.get(
            "/probe/admin-only",
            headers={
                "X-Wake-User-Id": "dave",
                "X-Wake-Workspace-Id": "workspace_a",
            },
        )
        ko = await ac.get(
            "/probe/admin-only",
            headers={
                "X-Wake-User-Id": "dave",
                "X-Wake-Workspace-Id": "workspace_b",
            },
        )
    assert ok.status_code == 200
    assert ko.status_code == 401  # unknown user in workspace_b


@pytest.mark.asyncio
async def test_rbac_on_me_endpoint_returns_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(WAKE_RBAC_ENABLED_ENV, "true")
    store = InMemoryUserStore()
    await store.create("eve", display_name="Eve", workspace_id="default")
    await store.assign_role("eve", Role.VIEWER, workspace_id="default")
    app = _build_user_app(store)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(
            "/probe/me",
            headers={"X-Wake-User-Id": "eve"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "eve"
    assert body["roles"] == ["viewer"]


@pytest.mark.asyncio
async def test_rbac_on_without_user_store_returns_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Operator turned RBAC on but never wired a UserStore."""
    monkeypatch.setenv(WAKE_RBAC_ENABLED_ENV, "true")
    app = create_app()  # no user_store

    @app.get("/probe/admin-only")
    async def probe_admin(
        user: User = Depends(require_role(Role.ADMIN)),
    ) -> dict[str, Any]:
        return {"user_id": user.id}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(
            "/probe/admin-only",
            headers={"X-Wake-User-Id": "alice"},
        )
    assert r.status_code == 503


# ---------------------------------------------------------------------------
# UserStore behaviour (fake-level — store-specific suites live elsewhere)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_store_create_rejects_reserved_id() -> None:
    from wake.store.base import StoreError

    store = InMemoryUserStore()
    with pytest.raises(StoreError):
        await store.create("system", workspace_id="default")


@pytest.mark.asyncio
async def test_user_store_assign_revoke_idempotent() -> None:
    store = InMemoryUserStore()
    await store.create("alice", workspace_id="default")
    await store.assign_role("alice", Role.ADMIN, workspace_id="default")
    await store.assign_role("alice", Role.ADMIN, workspace_id="default")  # no-op
    roles = await store.roles_for("alice", workspace_id="default")
    assert roles == [Role.ADMIN]
    await store.revoke_role("alice", Role.OPERATOR, workspace_id="default")  # no-op
    await store.revoke_role("alice", Role.ADMIN, workspace_id="default")
    assert (await store.roles_for("alice", workspace_id="default")) == []


@pytest.mark.asyncio
async def test_user_store_delete_cascades_roles() -> None:
    store = InMemoryUserStore()
    await store.create("alice", workspace_id="default")
    await store.assign_role("alice", Role.ADMIN, workspace_id="default")
    await store.assign_role("alice", Role.OPERATOR, workspace_id="default")
    await store.delete("alice", workspace_id="default")
    assert (await store.get("alice", workspace_id="default")) is None
    assert (await store.roles_for("alice", workspace_id="default")) == []


@pytest.mark.asyncio
async def test_user_store_workspace_isolation() -> None:
    store = InMemoryUserStore()
    await store.create("alice", workspace_id="workspace_a")
    await store.assign_role("alice", Role.ADMIN, workspace_id="workspace_a")
    # Same id exists independently in another workspace.
    await store.create("alice", workspace_id="workspace_b")
    a = await store.get("alice", workspace_id="workspace_a")
    b = await store.get("alice", workspace_id="workspace_b")
    assert a is not None and b is not None
    assert a.roles == (Role.ADMIN,)
    assert b.roles == ()
