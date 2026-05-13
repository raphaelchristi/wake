# wake-store-postgres

PostgreSQL 16+ storage backend for Wake — drop-in replacement for the
in-tree SQLite reference store (`wake.store.sqlite.SQLiteStore`).

The adapter implements the four ABCs declared in `wake.store.base`:

- `EventStore` (with LISTEN/NOTIFY-driven `subscribe` + polling fallback)
- `AgentStore` (versioned, content-hash deduplication identical to SQLite)
- `EnvironmentStore`
- `SessionStore`

Plus two production-grade primitives required by Phase 4:

- **Advisory locks** for cooperative session ownership across workers
  (`pg_try_advisory_lock(hashtext(session_id))`).
- **Worker heartbeat protocol** — a renewable lease that lets a healthy
  worker keep a session while a watchdog reclaims dead workers' sessions
  in under 30 s.

---

## Install

```bash
pip install -e adapters/postgres-store
# or, from PyPI once published:
pip install wake-store-postgres
```

Requires Python 3.11+, PostgreSQL 16+ on the server side, and
`asyncpg>=0.29`.

---

## Quickstart

```python
import asyncio
from wake_store_postgres import PostgresStore
from wake.types import ModelConfig


async def main() -> None:
    store = PostgresStore("postgresql+asyncpg://wake:wake@localhost:5432/wake")
    await store.initialize()  # runs Alembic to head
    try:
        agent = await store.agents.create(
            name="hello", model=ModelConfig(id="claude-opus-4-7")
        )
        session = await store.sessions.create(agent.id, agent.version)
        await store.events.append(session.id, "user.message", {"text": "hi"})
        print(await store.events.count(session.id))
    finally:
        await store.close()


asyncio.run(main())
```

A runnable version lives in `examples/quickstart.py`.

---

## DSN format

```
postgresql+asyncpg://<user>:<password>@<host>:<port>/<database>
```

`PostgresStore` accepts either the `postgresql+asyncpg://...` URL or the
bare `postgresql://...` form (which is auto-rewritten to use the asyncpg
driver). DSNs are never logged.

---

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `WAKE_PG_EVENT_PARTITIONS` | `16` | Number of `HASH(session_id)` partitions for the `events` table. Must be a positive integer. Only honoured at initial-schema migration time. |
| `WAKE_PG_HEARTBEAT_INTERVAL_S` | `10` | How often a `WorkerHeartbeat` renews its lock. |
| `WAKE_PG_HEARTBEAT_TIMEOUT_S` | `30` | Stale-worker threshold for the watchdog. |

---

## Schema highlights

- `events` is **partitioned by HASH(session_id)** with 16 partitions by
  default (configurable). Each partition is a separate table that
  PostgreSQL routes inserts/selects to automatically. This keeps single
  partitions bounded as the cluster scales horizontally per session.
- A **BRIN index on `events.created_at`** gives cheap range scans over
  the time dimension while remaining tiny compared to a btree.
- A `pg_notify('events_<id_short>', ...)` trigger fires after every
  `INSERT` into `events` so `subscribe()` can wake without polling.
  Channel names are truncated to keep PostgreSQL's 63-byte
  `NAMEDATALEN` budget.

### Partitioning trade-offs

`HASH(session_id)` partitioning is intentional:

- **Pro**: even distribution, no hot partition, scales horizontally if
  you add a foreign data wrapper / Citus shard layer later.
- **Pro**: per-session queries hit exactly one partition.
- **Con**: time-range scans across all sessions touch every partition.
  Mitigated by the BRIN index on `created_at` which is cheap to scan in
  parallel.
- **Con**: changing partition count requires a migration and rebalance.
  Pick once; raise `WAKE_PG_EVENT_PARTITIONS` only at greenfield deploys.

---

## Advisory locks

```python
from wake_store_postgres.locks import acquire_session_lock, release_session_lock

acquired = await acquire_session_lock(store.engine, session_id="01H...")
if acquired:
    try:
        ...  # exclusive ownership
    finally:
        await release_session_lock(store.engine, session_id="01H...")
```

Locks are mapped to `pg_try_advisory_lock(bigint)` via
`hashtext(session_id)`. They are session-scoped (released when the
connection closes), so even a crashed worker frees its locks.

---

## Heartbeat

```python
from wake_store_postgres.heartbeat import WorkerHeartbeat

hb = WorkerHeartbeat(
    engine=store.engine,
    session_id="01H...",
    worker_id="worker-1",
    interval_s=10,
)
await hb.start()
try:
    ...  # do work
finally:
    await hb.stop()
```

`WorkerHeartbeat` opens a dedicated connection, takes the advisory lock,
and renews `sessions.meta['_heartbeat']` every `interval_s` seconds.
A peer worker may call `WorkerHeartbeat.detect_stale(...)` to find
sessions whose last heartbeat is older than `timeout_s` and reschedule
them.

---

## LISTEN / NOTIFY (with polling fallback)

`PostgresEventStore.subscribe(session_id)` opens a long-lived asyncpg
connection, executes `LISTEN events_<id_short>`, and yields events from
the trigger's NOTIFY payload as they arrive. If the underlying
connection fails or the channel times out, the subscriber falls back to
the same polling strategy used by the SQLite reference store — so the
behaviour is **always at-least-as-good** as the SQLite store.

---

## Running tests

```bash
# Requires Docker (testcontainers spins up Postgres 16)
pytest adapters/postgres-store/tests/ -q

# Skip Docker-dependent tests gracefully:
pytest adapters/postgres-store/tests/ -q -k "not testcontainer"

# Opt-in load test (1000 concurrent sessions):
pytest adapters/postgres-store/tests/load/ --run-load
```

---

## Status

v0.1.0 — implements Phase 4 contract. Behavioural parity with
`SQLiteStore` is verified by re-running a shared test suite against both.
