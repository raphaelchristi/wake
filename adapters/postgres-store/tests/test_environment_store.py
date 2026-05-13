"""Behavioural tests for PostgresEnvironmentStore."""

from __future__ import annotations

from typing import Any

import pytest
from wake.store.base import StoreError

pytestmark = pytest.mark.asyncio


async def test_environment_crud(store: Any) -> None:
    env = await store.environments.create(name="default", config={"sandbox": {"backend": "docker"}})
    fetched = await store.environments.get(env.id)
    assert fetched is not None and fetched.name == "default"
    listed = await store.environments.list()
    assert len(listed) == 1
    await store.environments.archive(env.id)
    visible = await store.environments.list()
    assert visible == []
    archived = await store.environments.list(include_archived=True)
    assert archived[0].archived_at is not None
    await store.environments.delete(env.id)
    assert await store.environments.get(env.id) is None


async def test_environment_delete_missing_raises(store: Any) -> None:
    with pytest.raises(StoreError):
        await store.environments.delete("does-not-exist")


async def test_environment_config_jsonb_round_trip(store: Any) -> None:
    """JSONB stores arbitrary nested structures intact."""
    cfg = {
        "sandbox": {"backend": "docker", "limits": {"cpu": 2, "memory_gb": 4}},
        "envs": ["dev", "prod"],
        "packages": [{"name": "uv", "version": ">=0.5"}],
    }
    env = await store.environments.create(name="rich", config=cfg)
    fetched = await store.environments.get(env.id)
    assert fetched is not None
    assert fetched.config == cfg
