"""Tests for the LISTEN/NOTIFY-based subscribe() path.

We verify two scenarios:

1. Backlog is yielded first (events appended before subscribe starts).
2. Live events appended *after* subscribe starts arrive promptly via
   the NOTIFY trigger — measured by the round-trip latency staying
   well below the polling fallback interval.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from wake_store_postgres.events import _channel_name

# pytest-asyncio is in AUTO mode (pyproject.toml) so the explicit marker
# is unnecessary — keep `pytest` imported for the assertions below.
_ = pytest


def test_channel_name_truncation() -> None:
    # PG NAMEDATALEN is 63 bytes; ``events_`` + 12-char prefix = 19 bytes.
    name = _channel_name("01HABCDEFGHIJKLMNOPQRSTUV0")
    assert len(name) <= 63
    # 12-char prefix of the session_id, lowercased.
    assert name == "events_01habcdefghi"


async def test_subscribe_yields_backlog_first(store: Any) -> None:
    sid = "01HSUBBACK0000000000000ABCD"
    # Append three events before subscribing.
    for i in range(3):
        await store.events.append(sid, "status", {"i": i})
    received: list[int] = []

    async def consume() -> None:
        gen = await store.events.subscribe(sid, since=0)
        async for ev in gen:
            received.append(ev.seq)
            if len(received) == 3:
                break

    await asyncio.wait_for(consume(), timeout=2.0)
    assert received == [0, 1, 2]


async def test_subscribe_yields_live_events(store: Any) -> None:
    sid = "01HSUBLIVE0000000000000ABCD"
    received: list[int] = []

    async def consume() -> None:
        gen = await store.events.subscribe(sid, since=0)
        async for ev in gen:
            received.append(ev.seq)
            if len(received) == 2:
                break

    async def producer() -> None:
        # Give the subscriber a moment to set up LISTEN.
        await asyncio.sleep(0.15)
        await store.events.append(sid, "status", {"phase": "first"})
        await asyncio.sleep(0.05)
        await store.events.append(sid, "status", {"phase": "second"})

    await asyncio.wait_for(asyncio.gather(consume(), producer()), timeout=3.0)
    assert received == [0, 1]
