"""Phase 7 — idempotency_key dedupe coverage (Postgres backend).

Mirrors ``tests/unit/test_idempotency.py`` against the real Postgres
event store + migration 0004 (UNIQUE partial index on
``(workspace_id, session_id, idempotency_key) WHERE idempotency_key
IS NOT NULL`` per partition).

Skipped automatically when Docker / testcontainers are not available.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytestmark = pytest.mark.asyncio


async def test_no_key_creates_unique_events(store: Any) -> None:
    sid = "01HSESSION0000000000000PG1"
    e1 = await store.events.append(sid, "user.message", {"t": "1"})
    e2 = await store.events.append(sid, "user.message", {"t": "2"})
    e3 = await store.events.append(sid, "user.message", {"t": "3"})
    assert {e1.seq, e2.seq, e3.seq} == {0, 1, 2}
    assert len({e1.id, e2.id, e3.id}) == 3


async def test_repeat_key_returns_existing_event(store: Any) -> None:
    sid = "01HSESSION0000000000000PG2"
    first = await store.events.append(
        sid, "user.message", {"t": "hi"}, idempotency_key="k-pg-1"
    )
    second = await store.events.append(
        sid, "user.message", {"t": "ignored"}, idempotency_key="k-pg-1"
    )
    assert first.id == second.id
    assert first.seq == second.seq
    rows = await store.events.get(sid)
    assert len(rows) == 1
    # Mirror also visible in persisted metadata.
    assert (rows[0].metadata or {}).get("idempotency_key") == "k-pg-1"


async def test_different_sessions_do_not_collide(store: Any) -> None:
    s1 = "01HSESSION0000000000000PG3"
    s2 = "01HSESSION0000000000000PG4"
    e1 = await store.events.append(
        s1, "user.message", {"t": "a"}, idempotency_key="shared"
    )
    e2 = await store.events.append(
        s2, "user.message", {"t": "b"}, idempotency_key="shared"
    )
    assert e1.id != e2.id


async def test_different_workspaces_do_not_collide(store: Any) -> None:
    sid = "01HSESSION0000000000000PG5"
    e_alpha = await store.events.append(
        sid,
        "user.message",
        {"t": "a"},
        workspace_id="alpha",
        idempotency_key="shared",
    )
    e_beta = await store.events.append(
        sid,
        "user.message",
        {"t": "b"},
        workspace_id="beta",
        idempotency_key="shared",
    )
    assert e_alpha.id != e_beta.id


async def test_null_keys_never_collide(store: Any) -> None:
    sid = "01HSESSION0000000000000PG6"
    a = await store.events.append(sid, "user.message", {"t": "a"})
    b = await store.events.append(sid, "user.message", {"t": "b"})
    c = await store.events.append(sid, "user.message", {"t": "c"})
    assert len({a.id, b.id, c.id}) == 3
    rows = await store.events.get(sid)
    assert all((r.metadata or {}).get("idempotency_key") is None for r in rows)


async def test_concurrent_appends_dedupe(store: Any) -> None:
    """Two concurrent appends with the same key collapse to one row.

    Postgres serialises via ``pg_advisory_xact_lock`` keyed on
    ``hashtext(session_id)`` so the second writer's pre-check sees
    the first writer's committed row.
    """
    sid = "01HSESSION0000000000000PG7"

    async def _append() -> str:
        ev = await store.events.append(
            sid, "user.message", {"t": "x"}, idempotency_key="race"
        )
        return ev.id

    ids = await asyncio.gather(_append(), _append(), _append())
    assert len(set(ids)) == 1
    rows = await store.events.get(sid)
    assert len(rows) == 1
