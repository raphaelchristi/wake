"""Behavioural tests for PostgresEventStore.

The contract requires identical observable behaviour to the SQLite
reference store. We assert this by re-running the same checks the
SQLite store passes in ``tests/unit/test_event_log.py`` against the
Postgres backend.
"""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.asyncio


async def test_append_assigns_monotonic_seq(store: Any) -> None:
    sid = "01H0000000000000000000ABCD"
    e0 = await store.events.append(sid, "user.message", {"text": "hi"})
    e1 = await store.events.append(sid, "assistant.message", {"text": "hello"})
    e2 = await store.events.append(sid, "status", {"state": "running"})
    assert e0.seq == 0
    assert e1.seq == 1
    assert e2.seq == 2
    # ULIDs are 26 chars Crockford base32.
    assert len(e0.id) == 26
    assert e0.id != e1.id


async def test_seq_is_per_session(store: Any) -> None:
    s1 = "01H1111111111111111111ABCD"
    s2 = "01H2222222222222222222ABCD"
    a = await store.events.append(s1, "user.message", {"t": 1})
    b = await store.events.append(s2, "user.message", {"t": 1})
    c = await store.events.append(s1, "user.message", {"t": 2})
    assert a.seq == 0
    assert b.seq == 0
    assert c.seq == 1


async def test_get_returns_since(store: Any) -> None:
    sid = "01HSINCE000000000000000000"
    for i in range(5):
        await store.events.append(sid, "status", {"n": i})
    rows = await store.events.get(sid, since=2)
    seqs = [r.seq for r in rows]
    assert seqs == [2, 3, 4]


async def test_get_one_finds_by_ulid(store: Any) -> None:
    sid = "01HGETONE0000000000000ABCD"
    ev = await store.events.append(sid, "user.message", {"t": "x"})
    fetched = await store.events.get_one(ev.id)
    assert fetched is not None
    assert fetched.id == ev.id
    assert fetched.payload == {"t": "x"}


async def test_get_one_missing_returns_none(store: Any) -> None:
    assert await store.events.get_one("01HNONE0000000000000000000") is None


async def test_count(store: Any) -> None:
    sid = "01HCOUNT00000000000000ABCD"
    assert await store.events.count(sid) == 0
    for _ in range(3):
        await store.events.append(sid, "status", {})
    assert await store.events.count(sid) == 3


async def test_parent_id_and_metadata_round_trip(store: Any) -> None:
    sid = "01HPARENT00000000000000ABCD"
    p = await store.events.append(sid, "user.message", {"t": "p"})
    c = await store.events.append(
        sid, "tool_use", {"id": "tu_1"}, parent_id=p.id, metadata={"k": "v"}
    )
    assert c.parent_id == p.id
    assert c.metadata == {"k": "v"}


async def test_concurrent_appends_keep_seq_monotonic(store: Any) -> None:
    """Append 50 events in parallel — seqs must still be 0..49 in order.

    This exercises the cross-process advisory-lock-based seq allocator.
    With the SQLite store an in-process asyncio.Lock suffices; with
    Postgres we rely on ``pg_advisory_xact_lock(hashtext(session_id))``.
    """
    import asyncio

    sid = "01HCONC0000000000000000ABCD"
    n = 50
    results = await asyncio.gather(
        *(store.events.append(sid, "status", {"i": i}) for i in range(n))
    )
    seqs = sorted(r.seq for r in results)
    assert seqs == list(range(n))
    # And the on-disk count matches.
    assert await store.events.count(sid) == n
