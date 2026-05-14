"""Phase 7 — idempotency_key dedupe coverage.

Acceptance criteria (ops-throughput contract):

* No key → normal append, each call creates a new event.
* With key → first call creates, second call returns existing.
* Different sessions DON'T collide (key scope is per-session).
* Different workspaces DON'T collide (key scope is per-tenant).
* NULL keys NEVER collide with each other.
* Metadata mirrors the key on the persisted event.
* SQLite + in-memory + EventLog facade all behave identically.

The Postgres equivalent lives in
``adapters/postgres-store/tests/test_idempotency.py``.
"""

from __future__ import annotations

import pytest

from tests.unit.fakes import InMemoryEventStore
from wake.core.event_log import EventLog
from wake.store.sqlite import SQLiteStore

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def sqlite_store() -> SQLiteStore:
    store = SQLiteStore()
    await store.initialize()
    return store


# ---------------------------------------------------------------------------
# Backend-parametrised happy path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend", ["sqlite", "memory"])
async def test_no_key_creates_unique_events(
    backend: str, sqlite_store: SQLiteStore
) -> None:
    """Without an idempotency_key every append is a new row."""
    store = sqlite_store.events if backend == "sqlite" else InMemoryEventStore()
    sid = "01HSESSION00000000000000NK"
    e1 = await store.append(sid, "user.message", {"t": "1"})
    e2 = await store.append(sid, "user.message", {"t": "2"})
    e3 = await store.append(sid, "user.message", {"t": "3"})
    assert {e1.id, e2.id, e3.id} == {e1.id, e2.id, e3.id}
    assert len({e1.id, e2.id, e3.id}) == 3
    assert e1.seq == 0
    assert e2.seq == 1
    assert e3.seq == 2


@pytest.mark.parametrize("backend", ["sqlite", "memory"])
async def test_repeat_key_returns_existing_event(
    backend: str, sqlite_store: SQLiteStore
) -> None:
    """Second call with same key returns the first event unchanged."""
    store = sqlite_store.events if backend == "sqlite" else InMemoryEventStore()
    sid = "01HSESSION0000000000000RPT"
    first = await store.append(
        sid, "user.message", {"t": "hi"}, idempotency_key="key-1"
    )
    second = await store.append(
        sid, "user.message", {"t": "hi-attempt-2"}, idempotency_key="key-1"
    )
    assert second.id == first.id
    assert second.seq == first.seq
    # The store ignored the second payload, preserving the canonical
    # first event. (No double-write semantics.)
    assert second.payload == {"t": "hi"}
    # Only one row in the log.
    rows = await store.get(sid)
    assert len(rows) == 1


@pytest.mark.parametrize("backend", ["sqlite", "memory"])
async def test_different_sessions_do_not_collide(
    backend: str, sqlite_store: SQLiteStore
) -> None:
    """Same key, different session_id → two independent events."""
    store = sqlite_store.events if backend == "sqlite" else InMemoryEventStore()
    s1 = "01HSESSION0000000000000DS1"
    s2 = "01HSESSION0000000000000DS2"
    e1 = await store.append(s1, "user.message", {"t": "a"}, idempotency_key="shared")
    e2 = await store.append(s2, "user.message", {"t": "b"}, idempotency_key="shared")
    assert e1.id != e2.id
    assert e1.session_id == s1
    assert e2.session_id == s2


@pytest.mark.parametrize("backend", ["sqlite", "memory"])
async def test_different_workspaces_do_not_collide(
    backend: str, sqlite_store: SQLiteStore
) -> None:
    """Same key, same session_id, different workspace_id → independent."""
    store = sqlite_store.events if backend == "sqlite" else InMemoryEventStore()
    sid = "01HSESSION0000000000000DW1"
    e_alpha = await store.append(
        sid,
        "user.message",
        {"t": "a"},
        workspace_id="alpha",
        idempotency_key="shared",
    )
    e_beta = await store.append(
        sid,
        "user.message",
        {"t": "b"},
        workspace_id="beta",
        idempotency_key="shared",
    )
    assert e_alpha.id != e_beta.id


@pytest.mark.parametrize("backend", ["sqlite", "memory"])
async def test_null_keys_never_collide(
    backend: str, sqlite_store: SQLiteStore
) -> None:
    """No idempotency key on either call → both succeed independently."""
    store = sqlite_store.events if backend == "sqlite" else InMemoryEventStore()
    sid = "01HSESSION0000000000000NN1"
    a = await store.append(sid, "user.message", {"t": "a"})
    b = await store.append(sid, "user.message", {"t": "b"})
    c = await store.append(sid, "user.message", {"t": "c"})
    assert a.id != b.id != c.id
    rows = await store.get(sid)
    assert len(rows) == 3
    # No idempotency metadata is invented out of thin air.
    assert all((r.metadata or {}).get("idempotency_key") is None for r in rows)


@pytest.mark.parametrize("backend", ["sqlite", "memory"])
async def test_key_mirrored_into_metadata(
    backend: str, sqlite_store: SQLiteStore
) -> None:
    """The dedupe key is visible on the persisted event's metadata."""
    store = sqlite_store.events if backend == "sqlite" else InMemoryEventStore()
    sid = "01HSESSION0000000000000MM1"
    e = await store.append(
        sid, "user.message", {"t": "a"}, idempotency_key="trace-xyz"
    )
    assert (e.metadata or {}).get("idempotency_key") == "trace-xyz"


# ---------------------------------------------------------------------------
# EventLog facade — single source of truth for callers
# ---------------------------------------------------------------------------


async def test_event_log_facade_honours_idempotency(
    sqlite_store: SQLiteStore,
) -> None:
    log_facade = EventLog(sqlite_store.events)
    sid = "01HSESSION0000000000000ELG"
    a = await log_facade.append(sid, "user.message", {"t": "x"}, idempotency_key="k1")
    b = await log_facade.append(
        sid, "user.message", {"t": "x"}, idempotency_key="k1"
    )
    assert a.id == b.id
    assert (b.metadata or {}).get("idempotency_key") == "k1"


async def test_event_log_facade_no_key_passthrough(
    sqlite_store: SQLiteStore,
) -> None:
    """Without a key the facade preserves the historical behaviour."""
    log_facade = EventLog(sqlite_store.events)
    sid = "01HSESSION0000000000000ELP"
    a = await log_facade.append(sid, "user.message", {"t": "x"})
    b = await log_facade.append(sid, "user.message", {"t": "x"})
    assert a.id != b.id


# ---------------------------------------------------------------------------
# Concurrency — the asyncio.Lock per session guards the dedupe pre-check
# ---------------------------------------------------------------------------


async def test_concurrent_appends_with_same_key_dedupe(
    sqlite_store: SQLiteStore,
) -> None:
    """Two concurrent appends with the same key must end up with one row.

    The SQLite store serialises ``append`` via a per-session asyncio
    lock, so the second coroutine sees the row inserted by the first.
    """
    import asyncio

    sid = "01HSESSION0000000000000CCR"

    async def _append() -> str:
        ev = await sqlite_store.events.append(
            sid, "user.message", {"t": "x"}, idempotency_key="race"
        )
        return ev.id

    results = await asyncio.gather(_append(), _append(), _append())
    assert len(set(results)) == 1
    rows = await sqlite_store.events.get(sid)
    assert len(rows) == 1
