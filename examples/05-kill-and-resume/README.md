# 05 — Kill and resume

Demonstrates Phase 4's headline reliability guarantee: a session that
loses its worker mid-step recovers within ≤ 60s on a different worker
with a complete event log.

## What it does

1. Starts a session against a stub agent.
2. Spawns worker #1, which begins consuming events for the session.
3. After worker #1 has produced a few events, kills it with `SIGKILL`.
4. Spawns worker #2; verifies it acquires the session's advisory lock
   and finishes the run.
5. Asserts that:
   - the event log is contiguous (no gaps in `seq`)
   - the final event is `assistant.message`
   - end-to-end recovery time < 60 s

By default the script uses **in-memory fakes** so it runs without
Postgres. With `WAKE_DATABASE_URL` pointing at a real Postgres, the
script exercises the production code path (advisory locks +
`LISTEN/NOTIFY`).

## Prerequisites

- Python 3.11 + `pip install -e ".[dev]"` from the repo root.
- (optional) Postgres 16 + `wake-store-postgres` from the postgres-store slice.

## Run

```bash
cd examples/05-kill-and-resume
python run.py
```

Expected output (abridged):

```
[05] starting session sess_…
[05] worker-1 PID=12345 — emitted seq 0..4
[05] killing worker-1 (SIGKILL)
[05] worker-2 starting — acquired lock for session sess_…
[05] worker-2 finished — final seq=9, type=assistant.message
[05] recovery time = 1.84s  (target <60s)
[05] OK
```

## With real Postgres

```bash
docker run --rm -d --name pg-kill -p 5432:5432 \
  -e POSTGRES_PASSWORD=wake -e POSTGRES_USER=wake -e POSTGRES_DB=wake \
  postgres:16

WAKE_DATABASE_URL=postgresql+asyncpg://wake:wake@localhost:5432/wake \
  python run.py
```

## Tunables (env vars)

| Var | Default | Meaning |
|-----|---------|---------|
| `WAKE_KILL_AFTER_EVENTS` | `3` | Kill worker-1 after this many events |
| `WAKE_TOTAL_EVENTS` | `10` | Total events the session should produce |
| `WAKE_RECOVERY_BUDGET_S` | `60` | Hard failure threshold |
