"""Tests for ``WakeEventStream`` — the EventLog-backed EventStream view."""

from __future__ import annotations

import pytest

from tests.unit.fakes import InMemoryEventStore
from wake.core.event_log import EventLog
from wake.runtime.event_stream import WakeEventStream


@pytest.fixture
def event_log() -> EventLog:
    return EventLog(InMemoryEventStore())


@pytest.mark.asyncio
async def test_all_returns_events_in_seq_order(event_log: EventLog) -> None:
    await event_log.append("s1", "user.message", {"content": []})
    await event_log.append("s1", "assistant.message", {"content": []})
    stream = WakeEventStream(event_log, "s1")
    events = await stream.all()
    assert [e.type for e in events] == ["user.message", "assistant.message"]
    assert [e.seq for e in events] == [0, 1]


@pytest.mark.asyncio
async def test_all_is_scoped_to_session(event_log: EventLog) -> None:
    await event_log.append("s1", "user.message", {"content": []})
    await event_log.append("s2", "user.message", {"content": []})
    stream = WakeEventStream(event_log, "s1")
    events = await stream.all()
    assert len(events) == 1
    assert events[0].session_id == "s1"


@pytest.mark.asyncio
async def test_since_returns_only_newer_events(event_log: EventLog) -> None:
    await event_log.append("s1", "user.message", {"content": []})
    await event_log.append("s1", "assistant.delta", {"index": 0, "delta": {}})
    await event_log.append("s1", "assistant.message", {"content": []})
    stream = WakeEventStream(event_log, "s1")
    events = await stream.since(1)
    assert [e.type for e in events] == ["assistant.delta", "assistant.message"]


@pytest.mark.asyncio
async def test_latest_no_type_filter(event_log: EventLog) -> None:
    await event_log.append("s1", "user.message", {"content": []})
    await event_log.append("s1", "assistant.message", {"content": []})
    stream = WakeEventStream(event_log, "s1")
    ev = await stream.latest()
    assert ev is not None and ev.type == "assistant.message"


@pytest.mark.asyncio
async def test_latest_with_type_filter(event_log: EventLog) -> None:
    await event_log.append("s1", "user.message", {"content": []})
    await event_log.append("s1", "assistant.message", {"content": []})
    await event_log.append("s1", "tool_use", {"tool_use_id": "tu", "name": "x", "input": {}})
    stream = WakeEventStream(event_log, "s1")
    ev = await stream.latest("user.message")
    assert ev is not None and ev.type == "user.message"


@pytest.mark.asyncio
async def test_latest_returns_none_when_missing(event_log: EventLog) -> None:
    stream = WakeEventStream(event_log, "empty")
    assert (await stream.latest()) is None
    assert (await stream.latest("user.message")) is None


@pytest.mark.asyncio
async def test_count(event_log: EventLog) -> None:
    stream = WakeEventStream(event_log, "s1")
    assert await stream.count() == 0
    await event_log.append("s1", "user.message", {"content": []})
    await event_log.append("s1", "assistant.message", {"content": []})
    assert await stream.count() == 2
