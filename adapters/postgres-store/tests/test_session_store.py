"""Behavioural tests for PostgresSessionStore."""

from __future__ import annotations

from typing import Any

import pytest
from wake.store.base import StoreError

pytestmark = pytest.mark.asyncio


async def test_session_create_default_idle(store: Any) -> None:
    s = await store.sessions.create(agent_id="ag", agent_version=1)
    assert s.status == "idle"
    assert s.container_id is None


async def test_session_update_status(store: Any) -> None:
    s = await store.sessions.create(agent_id="ag", agent_version=1)
    running = await store.sessions.update_status(s.id, "running")
    assert running.status == "running"


async def test_session_set_container(store: Any) -> None:
    s = await store.sessions.create(agent_id="ag", agent_version=1)
    updated = await store.sessions.set_container(s.id, container_id="ctn_123", workspace_path="/w")
    assert updated.container_id == "ctn_123"
    assert updated.workspace_path == "/w"


async def test_session_list_by_status(store: Any) -> None:
    s1 = await store.sessions.create(agent_id="ag", agent_version=1)
    s2 = await store.sessions.create(agent_id="ag", agent_version=1)
    await store.sessions.update_status(s2.id, "running")
    idle_only = await store.sessions.list(status="idle")
    assert {x.id for x in idle_only} == {s1.id}
    running_only = await store.sessions.list(status="running")
    assert {x.id for x in running_only} == {s2.id}


async def test_session_delete(store: Any) -> None:
    s = await store.sessions.create(agent_id="ag", agent_version=1)
    await store.sessions.delete(s.id)
    assert await store.sessions.get(s.id) is None


async def test_missing_session_status_update_raises(store: Any) -> None:
    with pytest.raises(StoreError):
        await store.sessions.update_status("nope", "running")
