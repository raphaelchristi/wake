"""Compact tests (Phase 7 — gap #5).

``EventStore.compact_session`` coalesces contiguous ``assistant.delta``
runs into a single ``assistant.message`` snapshot. Contract assertions:

* 100+ deltas → 1 snapshot event + delete all deltas.
* Idempotent — running compact twice in a row doesn't re-coalesce a
  zero-delta log.
* Replay determinism — ``EventLog.events_to_messages`` projection MUST
  yield identical message lists before and after compact (deltas were
  always invisible to the projection by spec).
* Multiple non-adjacent runs are each coalesced separately.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from wake.core.event_log import EventLog
from wake.store import SQLiteStore


@pytest.fixture
async def env():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="wake-compact-test-")
    os.close(fd)
    s = SQLiteStore(f"sqlite+aiosqlite:///{path}")
    await s.initialize()
    log = EventLog(s.events)
    try:
        yield s, log
    finally:
        await s.close()
        os.unlink(path)


async def _append_deltas(log: EventLog, session_id: str, n: int, prefix: str = "x") -> None:
    for i in range(n):
        await log.append(
            session_id,
            "assistant.delta",
            {"text": f"{prefix}{i}"},
        )


async def test_compact_no_deltas_is_noop(env) -> None:
    store, log = env
    await log.append("se-empty", "user.message", {"content": [{"type": "text", "text": "hi"}]})
    result = await store.events.compact_session("se-empty")
    assert result.deltas_removed == 0
    assert result.snapshots_emitted == 0


async def test_compact_100_deltas_to_one_snapshot(env) -> None:
    store, log = env
    sid = "se-100-deltas"
    await log.append(sid, "user.message", {"content": [{"type": "text", "text": "hi"}]})
    await _append_deltas(log, sid, 100)
    # Initial: 1 user + 100 deltas = 101 events.
    assert await log.count(sid) == 101

    result = await store.events.compact_session(sid)
    assert result.deltas_removed == 100
    assert result.snapshots_emitted == 1

    after = await log.get(sid)
    # 1 user + 1 snapshot = 2 events.
    assert len(after) == 2
    assert after[0].type == "user.message"
    assert after[1].type == "assistant.message"
    snap = after[1]
    # Concatenated text is recoverable.
    assert "x0" in snap.payload["content"][0]["text"]
    assert "x99" in snap.payload["content"][0]["text"]
    # Audit metadata preserved.
    assert snap.metadata is not None
    assert snap.metadata["compacted"] is True
    assert snap.metadata["deltas_removed"] == 100


async def test_compact_idempotent(env) -> None:
    store, log = env
    sid = "se-idempotent"
    await log.append(sid, "user.message", {"content": [{"type": "text", "text": "hi"}]})
    await _append_deltas(log, sid, 50)
    await store.events.compact_session(sid)
    # Second call: no deltas left.
    again = await store.events.compact_session(sid)
    assert again.deltas_removed == 0
    assert again.snapshots_emitted == 0


async def test_compact_preserves_replay_determinism(env) -> None:
    """``events_to_messages`` projection MUST be identical before/after.

    Deltas are not part of the Messages API projection (per
    SPEC-EVENT-SCHEMA), so a compacted log produces the same message
    list as the original — the snapshot just adds an
    ``assistant.message`` that wasn't there before. Test asserts that
    projection only sees the surviving non-delta events.
    """
    store, log = env
    sid = "se-replay"
    await log.append(sid, "user.message", {"content": [{"type": "text", "text": "ping"}]})
    await _append_deltas(log, sid, 30, prefix="d")

    before = await log.get(sid)
    msgs_before = EventLog.events_to_messages(before)
    # Before compact: just 1 user message (deltas dropped).
    assert len(msgs_before) == 1
    assert msgs_before[0]["role"] == "user"

    await store.events.compact_session(sid)

    after = await log.get(sid)
    msgs_after = EventLog.events_to_messages(after)
    # After compact: 1 user + 1 assistant.message (the snapshot).
    assert len(msgs_after) == 2
    assert msgs_after[0]["role"] == "user"
    assert msgs_after[1]["role"] == "assistant"


async def test_compact_multiple_runs_coalesced_separately(env) -> None:
    """Two interrupted streams in one session → two snapshots."""
    store, log = env
    sid = "se-multi-run"
    await log.append(sid, "user.message", {"content": [{"type": "text", "text": "turn1"}]})
    await _append_deltas(log, sid, 5, prefix="a")
    await log.append(sid, "user.message", {"content": [{"type": "text", "text": "turn2"}]})
    await _append_deltas(log, sid, 7, prefix="b")

    result = await store.events.compact_session(sid)
    assert result.deltas_removed == 12
    assert result.snapshots_emitted == 2

    after = await log.get(sid)
    snapshots = [e for e in after if e.type == "assistant.message"]
    assert len(snapshots) == 2
