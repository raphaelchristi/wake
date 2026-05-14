"""Postgres-backed UserStore behavioural tests.

Mirrors ``tests/unit/test_store.py`` UserStore section so Postgres
parity is enforced. Skipped (via the module-level ``store`` fixture)
when Docker is unavailable, matching the rest of the postgres-store
suite.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from wake_store_postgres import PostgresStore


pytestmark = pytest.mark.asyncio


async def test_user_create_and_get(store: PostgresStore) -> None:
    from wake.rbac import Role

    u = await store.users.create(
        "alice", display_name="Alice", workspace_id="default"
    )
    assert u.id == "alice"
    fetched = await store.users.get("alice", workspace_id="default")
    assert fetched is not None
    assert fetched.display_name == "Alice"
    # Wrong workspace returns None.
    assert (await store.users.get("alice", workspace_id="other")) is None

    await store.users.assign_role("alice", Role.ADMIN, workspace_id="default")
    await store.users.assign_role("alice", Role.ADMIN, workspace_id="default")  # noop
    await store.users.assign_role("alice", Role.OPERATOR, workspace_id="default")
    roles = await store.users.roles_for("alice", workspace_id="default")
    assert roles == [Role.ADMIN, Role.OPERATOR]


async def test_user_create_rejects_reserved_id(store: PostgresStore) -> None:
    from wake.store.base import StoreError

    with pytest.raises(StoreError):
        await store.users.create("system", workspace_id="default")


async def test_user_create_rejects_duplicate(store: PostgresStore) -> None:
    from wake.store.base import StoreError

    await store.users.create("bob", workspace_id="default")
    with pytest.raises(StoreError):
        await store.users.create("bob", workspace_id="default")


async def test_user_list_and_workspace_isolation(store: PostgresStore) -> None:
    from wake.rbac import Role

    await store.users.create("alice", workspace_id="ws_a")
    await store.users.create("bob", workspace_id="ws_a")
    await store.users.create("alice", workspace_id="ws_b")

    await store.users.assign_role("alice", Role.ADMIN, workspace_id="ws_a")
    await store.users.assign_role("alice", Role.VIEWER, workspace_id="ws_b")

    listed_a = await store.users.list(workspace_id="ws_a")
    assert sorted(u.id for u in listed_a) == ["alice", "bob"]
    listed_b = await store.users.list(workspace_id="ws_b")
    assert [u.id for u in listed_b] == ["alice"]

    a = await store.users.get("alice", workspace_id="ws_a")
    b = await store.users.get("alice", workspace_id="ws_b")
    assert a is not None and a.roles == (Role.ADMIN,)
    assert b is not None and b.roles == (Role.VIEWER,)


async def test_user_update_display_name(store: PostgresStore) -> None:
    await store.users.create("alice", workspace_id="default")
    updated = await store.users.update(
        "alice", workspace_id="default", display_name="Alice Renamed"
    )
    assert updated.display_name == "Alice Renamed"


async def test_user_delete_cascades_roles(store: PostgresStore) -> None:
    from wake.rbac import Role

    await store.users.create("alice", workspace_id="default")
    await store.users.assign_role("alice", Role.ADMIN, workspace_id="default")
    await store.users.delete("alice", workspace_id="default")
    assert (await store.users.get("alice", workspace_id="default")) is None
    assert (await store.users.roles_for("alice", workspace_id="default")) == []


async def test_user_revoke_role_idempotent(store: PostgresStore) -> None:
    from wake.rbac import Role

    await store.users.create("alice", workspace_id="default")
    await store.users.revoke_role("alice", Role.ADMIN, workspace_id="default")
    await store.users.assign_role("alice", Role.ADMIN, workspace_id="default")
    await store.users.revoke_role("alice", Role.ADMIN, workspace_id="default")
    assert (await store.users.roles_for("alice", workspace_id="default")) == []


async def test_user_assign_role_to_unknown_raises(store: PostgresStore) -> None:
    from wake.rbac import Role
    from wake.store.base import StoreError

    with pytest.raises(StoreError):
        await store.users.assign_role(
            "ghost", Role.ADMIN, workspace_id="default"
        )
