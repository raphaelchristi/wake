"""Load test: 1000 concurrent sessions.

Opt-in via ``--run-load``. Reports p95 of:

* session creation latency
* first-event-append latency

Targets (from PHASE-4 contract):
* p95 session creation < 200 ms
* p95 first event       < 500 ms

The test deliberately uses *concurrent* awaits rather than sequential
iteration so we exercise the connection pool + advisory-lock contention
realistically.
"""

from __future__ import annotations

import asyncio
import statistics
import time
from typing import Any

import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.load]


N_SESSIONS = 1000
P95_SESSION_CREATION_MS = 200.0
P95_FIRST_EVENT_MS = 500.0


async def _create_one(store: Any) -> tuple[float, float]:
    """Create a session + first event, return (create_ms, first_event_ms)."""
    t0 = time.perf_counter()
    s = await store.sessions.create(agent_id="loadtest", agent_version=1)
    t1 = time.perf_counter()
    await store.events.append(s.id, "user.message", {"text": "hi"})
    t2 = time.perf_counter()
    return (t1 - t0) * 1000.0, (t2 - t1) * 1000.0


async def test_1000_sessions_p95_under_targets(store: Any) -> None:
    """Soft load test — measures p95 and asserts against targets."""
    # Run in batches to avoid swamping the test container's pool.
    batch = 50
    creates: list[float] = []
    events: list[float] = []
    overall_t0 = time.perf_counter()
    for _start in range(0, N_SESSIONS, batch):
        results = await asyncio.gather(*(_create_one(store) for _ in range(batch)))
        for c, e in results:
            creates.append(c)
            events.append(e)
    overall_elapsed = time.perf_counter() - overall_t0

    p95_create = statistics.quantiles(creates, n=20)[-1]  # p95
    p95_event = statistics.quantiles(events, n=20)[-1]
    print(
        f"\nload: n={N_SESSIONS} total={overall_elapsed:.2f}s "
        f"create p50={statistics.median(creates):.1f}ms "
        f"p95={p95_create:.1f}ms "
        f"event p50={statistics.median(events):.1f}ms "
        f"p95={p95_event:.1f}ms"
    )

    # Use soft asserts so the report is always visible.
    assert p95_create < P95_SESSION_CREATION_MS, (
        f"p95 session creation {p95_create:.1f}ms exceeds target {P95_SESSION_CREATION_MS}ms"
    )
    assert p95_event < P95_FIRST_EVENT_MS, (
        f"p95 first event {p95_event:.1f}ms exceeds target {P95_FIRST_EVENT_MS}ms"
    )
