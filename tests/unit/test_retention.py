"""Retention / archive helper tests (Phase 7 — gap #5).

Two store-level helpers under test:

* ``purge_before(cutoff, dry_run=...)``  — count + bounded-batch
  delete of events older than cutoff.

* ``iter_for_archive(cutoff, batch_size=...)`` — async-iterator
  yielding event batches ordered by ``(session_id, seq)``.

CLI tests go in ``test_cli_retention.py`` (separate file) — here we
exercise the underlying store contract.
"""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from wake.core.event_log import EventLog
from wake.store import SQLiteStore
from wake.store.sqlite import EventRow


@pytest.fixture
async def env():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="wake-ret-test-")
    os.close(fd)
    s = SQLiteStore(f"sqlite+aiosqlite:///{path}")
    await s.initialize()
    log = EventLog(s.events)
    try:
        yield s, log
    finally:
        await s.close()
        os.unlink(path)


async def _backdate(store: SQLiteStore, event_id: str, when: datetime) -> None:
    """Force an event's ``created_at`` to a specific moment (test setup).

    Production code never rewrites created_at; this helper is a test
    fixture only.
    """
    async with store._sessionmaker() as s, s.begin():  # noqa: SLF001
        await s.execute(
            update(EventRow)
            .where(EventRow.id == event_id)
            .values(created_at=when.replace(tzinfo=None) if when.tzinfo else when)
        )


# ---------------------------------------------------------------------------
# purge_before
# ---------------------------------------------------------------------------


async def test_purge_before_dry_run_returns_count(env) -> None:
    store, log = env
    sid = "se-purge-dry"
    # Three events: 2 old (backdated), 1 fresh (now). Fresh events
    # need a cutoff strictly between them and the backdated ones —
    # we use the time **before** the fresh appends so the comparison
    # ``created_at < cutoff`` excludes the still-fresh row.
    now = datetime.now(UTC)
    e1 = await log.append(sid, "user.message", {"content": []})
    e2 = await log.append(sid, "assistant.message", {"content": []})
    e3 = await log.append(sid, "assistant.message", {"content": []})
    old = now - timedelta(days=180)
    fresh_future = now + timedelta(days=180)
    await _backdate(store, e1.id, old)
    await _backdate(store, e2.id, old)
    await _backdate(store, e3.id, fresh_future)

    # Cutoff between old (-180d) and fresh (+180d): catches only the
    # 2 backdated rows.
    result = await store.events.purge_before(now, dry_run=True)
    assert result.dry_run is True
    assert result.deleted == 2
    # Nothing actually deleted.
    assert await log.count(sid) == 3


async def test_purge_before_actually_deletes(env) -> None:
    store, log = env
    sid = "se-purge-real"
    now = datetime.now(UTC)
    e1 = await log.append(sid, "user.message", {"content": []})
    e2 = await log.append(sid, "assistant.message", {"content": []})
    fresh = await log.append(sid, "assistant.message", {"content": []})
    old = now - timedelta(days=200)
    fresh_future = now + timedelta(days=200)
    await _backdate(store, e1.id, old)
    await _backdate(store, e2.id, old)
    await _backdate(store, fresh.id, fresh_future)

    result = await store.events.purge_before(now, dry_run=False)
    assert result.dry_run is False
    assert result.deleted == 2

    after = await log.get(sid)
    assert len(after) == 1
    assert after[0].id == fresh.id


async def test_purge_before_batched_delete_handles_large_set(env) -> None:
    """Tiny batch_size proves the loop terminates correctly even when
    the delete window is larger than the batch."""
    store, log = env
    sid = "se-purge-batched"
    ids: list[str] = []
    for i in range(25):
        ev = await log.append(sid, "assistant.delta", {"text": f"{i}"})
        ids.append(ev.id)
    old = datetime.now(UTC) - timedelta(days=400)
    for eid in ids:
        await _backdate(store, eid, old)
    cutoff = datetime.now(UTC)

    result = await store.events.purge_before(cutoff, dry_run=False, batch_size=4)
    assert result.deleted == 25
    assert await log.count(sid) == 0


async def test_purge_before_workspace_scoped(env) -> None:
    store, log = env
    sid_a = "se-ws-a"
    sid_b = "se-ws-b"
    ev_a = await log.append(sid_a, "user.message", {"content": []}, workspace_id="ws-a")
    ev_b = await log.append(sid_b, "user.message", {"content": []}, workspace_id="ws-b")
    old = datetime.now(UTC) - timedelta(days=200)
    await _backdate(store, ev_a.id, old)
    await _backdate(store, ev_b.id, old)
    cutoff = datetime.now(UTC)

    # Only purge ws-a.
    result = await store.events.purge_before(cutoff, workspace_id="ws-a")
    assert result.deleted == 1
    # ws-b row untouched.
    assert await log.count(sid_b, workspace_id="ws-b") == 1


# ---------------------------------------------------------------------------
# iter_for_archive
# ---------------------------------------------------------------------------


async def test_iter_for_archive_streams_batches(env) -> None:
    store, log = env
    sid = "se-arc-stream"
    ids: list[str] = []
    for i in range(7):
        ev = await log.append(sid, "assistant.delta", {"text": f"{i}"})
        ids.append(ev.id)
    old = datetime.now(UTC) - timedelta(days=100)
    for eid in ids:
        await _backdate(store, eid, old)
    cutoff = datetime.now(UTC)

    batches: list[list] = []
    async for batch in await store.events.iter_for_archive(
        cutoff, batch_size=3
    ):
        batches.append(batch)

    # 7 rows / batch_size=3 → 3 batches (3 + 3 + 1).
    assert [len(b) for b in batches] == [3, 3, 1]
    # Ordering: every batch is sorted by (session_id, seq).
    all_events = [ev for batch in batches for ev in batch]
    seqs = [ev.seq for ev in all_events]
    assert seqs == sorted(seqs)


async def test_iter_for_archive_excludes_fresh_events(env) -> None:
    store, log = env
    sid = "se-arc-mixed"
    # 3 old + 2 fresh. Use a forward-stamp on fresh rows so the
    # cutoff at "now" cleanly separates them.
    now = datetime.now(UTC)
    fresh_future = now + timedelta(days=180)
    old_ev = []
    for i in range(3):
        ev = await log.append(sid, "user.message", {"content": []})
        old_ev.append(ev)
    fresh_ev = []
    for i in range(2):
        fe = await log.append(sid, "user.message", {"content": []})
        fresh_ev.append(fe)
    old = now - timedelta(days=180)
    for ev in old_ev:
        await _backdate(store, ev.id, old)
    for ev in fresh_ev:
        await _backdate(store, ev.id, fresh_future)

    total = 0
    async for batch in await store.events.iter_for_archive(now, batch_size=100):
        total += len(batch)
    assert total == 3
