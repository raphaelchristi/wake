"""Retention helpers on the Postgres store (Phase 7 — gap #5).

Opt-in: skipped when Docker is unavailable.

Mirrors the SQLite ``tests/unit/test_retention.py`` shape: backdate
events by direct SQL update, then exercise ``purge_before`` /
``iter_for_archive`` / ``compact_session``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update


async def _backdate(store, event_id: str, when: datetime) -> None:
    """Test-only helper — directly rewrite ``created_at``."""
    from wake_store_postgres.models import EventRow

    async with store._sessionmaker() as s, s.begin():
        await s.execute(
            update(EventRow).where(EventRow.id == event_id).values(created_at=when)
        )


@pytest.mark.asyncio
async def test_purge_before_dry_run(store) -> None:
    sid = "se-pg-purge-dry"
    now = datetime.now(UTC)
    e1 = await store.events.append(sid, "user.message", {"content": []})
    e2 = await store.events.append(sid, "assistant.message", {"content": []})
    fresh = await store.events.append(sid, "assistant.message", {"content": []})
    old = now - timedelta(days=180)
    fresh_future = now + timedelta(days=180)
    await _backdate(store, e1.id, old)
    await _backdate(store, e2.id, old)
    await _backdate(store, fresh.id, fresh_future)

    result = await store.events.purge_before(now, dry_run=True)
    assert result.dry_run is True
    assert result.deleted == 2
    assert await store.events.count(sid) == 3


@pytest.mark.asyncio
async def test_purge_before_actually_deletes(store) -> None:
    sid = "se-pg-purge-real"
    now = datetime.now(UTC)
    e1 = await store.events.append(sid, "user.message", {"content": []})
    e2 = await store.events.append(sid, "assistant.message", {"content": []})
    fresh = await store.events.append(sid, "assistant.message", {"content": []})
    old = now - timedelta(days=200)
    fresh_future = now + timedelta(days=200)
    await _backdate(store, e1.id, old)
    await _backdate(store, e2.id, old)
    await _backdate(store, fresh.id, fresh_future)

    result = await store.events.purge_before(now, dry_run=False, batch_size=1)
    assert result.dry_run is False
    assert result.deleted == 2
    assert await store.events.count(sid) == 1


@pytest.mark.asyncio
async def test_iter_for_archive(store) -> None:
    sid = "se-pg-archive"
    now = datetime.now(UTC)
    fresh_future = now + timedelta(days=180)
    old_ev = []
    for _ in range(4):
        ev = await store.events.append(sid, "assistant.delta", {"text": "x"})
        old_ev.append(ev)
    for _ in range(2):
        ev = await store.events.append(sid, "assistant.delta", {"text": "y"})
        await _backdate(store, ev.id, fresh_future)
    old = now - timedelta(days=100)
    for ev in old_ev:
        await _backdate(store, ev.id, old)

    total = 0
    async for batch in await store.events.iter_for_archive(now, batch_size=10):
        total += len(batch)
    assert total == 4


@pytest.mark.asyncio
async def test_compact_session_postgres(store) -> None:
    sid = "se-pg-compact"
    await store.events.append(
        sid, "user.message", {"content": [{"type": "text", "text": "hi"}]}
    )
    for i in range(10):
        await store.events.append(sid, "assistant.delta", {"text": f"{i}"})
    result = await store.events.compact_session(sid)
    assert result.deltas_removed == 10
    assert result.snapshots_emitted == 1
    after = await store.events.get(sid)
    assert any(e.type == "assistant.message" and e.metadata and e.metadata.get("compacted") for e in after)
