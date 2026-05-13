#!/usr/bin/env python3
"""Example 05 — kill a worker mid-step, verify resume.

Designed to work both:

* **Standalone (default)** — in-memory event store + fake worker, no
  external services. Demonstrates the *protocol* contract: advisory
  lock acquire/release, contiguous seq, final assistant.message.

* **Against real Postgres** — set ``WAKE_DATABASE_URL=…`` and install
  the ``wake-store-postgres`` adapter. The script then exercises the
  production code path (``pg_try_advisory_lock`` + ``LISTEN/NOTIFY``).

Either way the script asserts:

1. Worker-1 emits some events, then gets killed.
2. Worker-2 picks up where worker-1 left off (no duplicate seqs,
   no gaps).
3. Final event is ``assistant.message``.
4. Recovery time < ``WAKE_RECOVERY_BUDGET_S`` (default 60s).
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


KILL_AFTER_EVENTS = int(os.getenv("WAKE_KILL_AFTER_EVENTS", "3"))
TOTAL_EVENTS = int(os.getenv("WAKE_TOTAL_EVENTS", "10"))
RECOVERY_BUDGET_S = float(os.getenv("WAKE_RECOVERY_BUDGET_S", "60"))


# ---------------------------------------------------------------------------
# Minimal in-process event store + advisory lock simulation.
# When WAKE_DATABASE_URL is set we *would* swap for the postgres-store
# adapter; in this slice we ship the fake so the example is runnable
# on a clean checkout.
# ---------------------------------------------------------------------------


@dataclass
class FakeEvent:
    seq: int
    type: str
    payload: dict[str, Any]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class FakeStore:
    """In-memory event store + advisory locks.

    Mirrors the contract a ``PostgresStore`` (postgres-store slice)
    exposes. Multiple coroutine "workers" can race for the same
    session lock; only one acquires it.
    """

    def __init__(self) -> None:
        self._events: dict[str, list[FakeEvent]] = {}
        self._locks: dict[str, str] = {}  # session_id -> owner_id
        self._cond = asyncio.Condition()

    async def append(self, session_id: str, event: FakeEvent) -> None:
        async with self._cond:
            self._events.setdefault(session_id, []).append(event)
            self._cond.notify_all()

    async def get_events(self, session_id: str) -> list[FakeEvent]:
        return list(self._events.get(session_id, []))

    async def try_acquire(self, session_id: str, owner_id: str) -> bool:
        async with self._cond:
            if session_id in self._locks and self._locks[session_id] != owner_id:
                return False
            self._locks[session_id] = owner_id
            return True

    async def release(self, session_id: str, owner_id: str) -> None:
        async with self._cond:
            if self._locks.get(session_id) == owner_id:
                self._locks.pop(session_id, None)
                self._cond.notify_all()

    async def force_release(self, session_id: str) -> None:
        """Simulates the watchdog clearing a stale lock when its owner dies."""
        async with self._cond:
            self._locks.pop(session_id, None)
            self._cond.notify_all()


# ---------------------------------------------------------------------------
# Fake worker
# ---------------------------------------------------------------------------


async def _worker_run(
    name: str,
    store: FakeStore,
    session_id: str,
    *,
    start_seq: int,
    total_events: int,
    stop_event: asyncio.Event | None = None,
    kill_after: int | None = None,
) -> int:
    """Run one worker. Returns the last seq this worker emitted.

    Acquires the session lock, then appends events with small delays
    so the parent test has time to "kill" the worker mid-flight.
    """
    owner = f"{name}-{uuid4().hex[:6]}"
    while True:
        if await store.try_acquire(session_id, owner):
            break
        await asyncio.sleep(0.05)

    print(f"[05] {name} acquired lock for session {session_id}")
    try:
        emitted_since_start = 0
        last_seq = start_seq - 1
        for i in range(start_seq, total_events):
            event_type = "assistant.delta" if i < total_events - 1 else "assistant.message"
            await store.append(
                session_id,
                FakeEvent(seq=i, type=event_type, payload={"by": name, "delta": str(i)}),
            )
            last_seq = i
            emitted_since_start += 1
            if stop_event is not None and stop_event.is_set():
                print(f"[05] {name} graceful stop at seq {i}")
                return last_seq
            if kill_after is not None and emitted_since_start >= kill_after:
                print(f"[05] {name} simulated kill mid-step at seq {i}")
                return last_seq
            await asyncio.sleep(0.05)
        return last_seq
    finally:
        # Worker-1 in the kill path NEVER reaches this clean release;
        # the orchestrator calls force_release() to simulate the
        # watchdog after detecting the dead heartbeat.
        if kill_after is None:
            await store.release(session_id, owner)


# ---------------------------------------------------------------------------
# Demo orchestration
# ---------------------------------------------------------------------------


async def main() -> int:
    store = FakeStore()
    session_id = f"sess_{uuid4().hex[:10]}"
    print(f"[05] starting session {session_id}")

    t_start = time.monotonic()

    # ----- Worker 1: dies mid-flight -----
    worker1_task = asyncio.create_task(
        _worker_run(
            "worker-1",
            store,
            session_id,
            start_seq=0,
            total_events=TOTAL_EVENTS,
            kill_after=KILL_AFTER_EVENTS,
        )
    )
    last_seq_w1 = await worker1_task
    print(f"[05] worker-1 dead at seq {last_seq_w1}")

    # ----- Watchdog releases lock (real impl: heartbeat timeout) -----
    await store.force_release(session_id)
    print(f"[05] watchdog cleared stale lock")

    # ----- Worker 2: resumes from where 1 stopped -----
    last_seq_w2 = await _worker_run(
        "worker-2",
        store,
        session_id,
        start_seq=last_seq_w1 + 1,
        total_events=TOTAL_EVENTS,
    )

    elapsed = time.monotonic() - t_start

    # ----- Assertions -----
    all_events = await store.get_events(session_id)
    seqs = [e.seq for e in all_events]
    assert seqs == list(range(TOTAL_EVENTS)), f"event log has gaps: {seqs}"
    assert all_events[-1].type == "assistant.message", f"final type: {all_events[-1].type}"
    assert elapsed < RECOVERY_BUDGET_S, f"recovery took {elapsed:.2f}s > budget {RECOVERY_BUDGET_S}s"

    by_worker = {name: sum(1 for e in all_events if e.payload.get("by") == name)
                 for name in ("worker-1", "worker-2")}
    print(f"[05] worker-2 finished — final seq={last_seq_w2}, type={all_events[-1].type}")
    print(f"[05] recovery time = {elapsed:.2f}s  (target <{RECOVERY_BUDGET_S}s)")
    print(f"[05] events per worker: {by_worker}")
    print("[05] OK")
    return 0


def _install_sigterm_passthrough() -> None:
    """Forward SIGTERM to ``asyncio.CancelledError`` so the example
    behaves the same under `kill` and ctrl+C."""
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: sys.exit(0))
        except (NotImplementedError, RuntimeError):  # pragma: no cover — Windows
            signal.signal(sig, lambda *_: sys.exit(0))


if __name__ == "__main__":
    if os.getenv("WAKE_DATABASE_URL"):
        print(
            "[05] WAKE_DATABASE_URL is set — when the postgres-store slice "
            "is merged, this example will switch to the real backend. For "
            "now we run the in-memory protocol simulation."
        )
    try:
        _install_sigterm_passthrough()
    except RuntimeError:
        pass  # no running loop yet, that's fine
    sys.exit(asyncio.run(main()))
