"""Tests for the event log (store + facade)."""

from __future__ import annotations

import asyncio
import os
import tempfile

import pytest

from wake.core.event_log import EventLog
from wake.store import SQLiteStore
from wake.types import TextBlock, ToolResult


@pytest.fixture
async def setup() -> "tuple[SQLiteStore, EventLog]":
    fd, path = tempfile.mkstemp(suffix=".db", prefix="wake-test-")
    os.close(fd)
    s = SQLiteStore(f"sqlite+aiosqlite:///{path}")
    await s.initialize()
    log = EventLog(s.events)
    try:
        yield s, log
    finally:
        await s.close()
        os.unlink(path)


async def test_append_assigns_seq_zero_first(setup) -> None:
    _, log = setup
    ev = await log.user_message("sess1", "hi")
    assert ev.seq == 0
    assert ev.type == "user.message"
    assert ev.id and len(ev.id) == 26
    assert ev.created_at is not None


async def test_seq_monotonic(setup) -> None:
    _, log = setup
    e0 = await log.user_message("sess1", "a")
    e1 = await log.user_message("sess1", "b")
    e2 = await log.user_message("sess1", "c")
    assert [e0.seq, e1.seq, e2.seq] == [0, 1, 2]


async def test_seq_per_session_independent(setup) -> None:
    _, log = setup
    a = await log.user_message("sessA", "x")
    b = await log.user_message("sessB", "y")
    assert a.seq == 0 and b.seq == 0


async def test_get_with_since(setup) -> None:
    _, log = setup
    for i in range(5):
        await log.user_message("s", f"msg-{i}")
    all_ = await log.get("s")
    assert len(all_) == 5
    tail = await log.get("s", since=3)
    assert [e.seq for e in tail] == [3, 4]


async def test_get_one_by_id(setup) -> None:
    _, log = setup
    ev = await log.user_message("s", "x")
    fetched = await log.get_one(ev.id)
    assert fetched is not None and fetched.id == ev.id


async def test_count(setup) -> None:
    _, log = setup
    assert await log.count("s") == 0
    await log.user_message("s", "x")
    await log.user_message("s", "y")
    assert await log.count("s") == 2


async def test_assistant_message_helper(setup) -> None:
    _, log = setup
    ev = await log.assistant_message(
        "s",
        "done",
        usage={"input_tokens": 10, "output_tokens": 5},
    )
    assert ev.type == "assistant.message"
    assert ev.payload["stop_reason"] == "end_turn"
    assert ev.payload["usage"]["input_tokens"] == 10


async def test_tool_use_then_result_linked(setup) -> None:
    _, log = setup
    tu = await log.tool_use("s", "toolu_1", "bash", {"command": "ls"})
    result = ToolResult(content=[TextBlock(text="ok")])
    tr = await log.tool_result("s", "toolu_1", result, parent_id=tu.id)
    assert tr.parent_id == tu.id
    assert tr.payload["is_error"] is False
    assert tr.payload["tool_use_id"] == "toolu_1"


async def test_tool_result_error(setup) -> None:
    _, log = setup
    result = ToolResult(
        content=[TextBlock(text="oops")], is_error=True, error_code="permission_denied"
    )
    ev = await log.tool_result("s", "toolu_x", result)
    assert ev.payload["is_error"] is True
    assert ev.payload["error_code"] == "permission_denied"


async def test_status_event(setup) -> None:
    _, log = setup
    ev = await log.status("s", "idle", "running", reason="start")
    assert ev.payload == {"from": "idle", "to": "running", "reason": "start"}


async def test_error_event(setup) -> None:
    _, log = setup
    ev = await log.error("s", "harness_panic", "boom", trace="...")
    assert ev.type == "error"
    assert ev.payload["error_type"] == "harness_panic"
    assert ev.payload["trace"] == "..."


async def test_subscribe_yields_backlog_then_live(setup) -> None:
    store, log = setup
    # Backlog
    e0 = await log.user_message("s", "0")
    e1 = await log.user_message("s", "1")
    received: list[int] = []

    async def consume() -> None:
        it = await log.subscribe("s")
        async for ev in it:
            received.append(ev.seq)
            if len(received) == 4:
                break

    task = asyncio.create_task(consume())
    # let backlog drain
    await asyncio.sleep(0.05)
    await log.user_message("s", "2")
    await log.user_message("s", "3")
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except TimeoutError:
        pass
    assert received == [e0.seq, e1.seq, 2, 3]


async def test_events_to_messages_basic_turn(setup) -> None:
    _, log = setup
    await log.user_message("s", "hello")
    await log.tool_use("s", "tu1", "bash", {"command": "ls"})
    await log.tool_result("s", "tu1", ToolResult(content=[TextBlock(text="ok")]))
    await log.assistant_message("s", "done")
    events = await log.get("s")
    messages = EventLog.events_to_messages(events)
    # user → assistant(tool_use) → user(tool_result) → assistant
    roles = [m["role"] for m in messages]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert messages[1]["content"][0]["type"] == "tool_use"
    assert messages[2]["content"][0]["type"] == "tool_result"
