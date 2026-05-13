"""Tests for the session domain + state machine."""

from __future__ import annotations

import os
import tempfile

import pytest

from wake.core.event_log import EventLog
from wake.core.session import (
    VALID_TRANSITIONS,
    InvalidTransitionError,
    SessionService,
)
from wake.store import SQLiteStore


@pytest.fixture
async def services():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="wake-test-")
    os.close(fd)
    s = SQLiteStore(f"sqlite+aiosqlite:///{path}")
    await s.initialize()
    log = EventLog(s.events)
    svc = SessionService(s.sessions, log)
    try:
        yield svc, log, s
    finally:
        await s.close()
        os.unlink(path)


async def test_valid_transitions_table_is_well_formed() -> None:
    # Every status appears as key; terminated is terminal (empty set).
    assert VALID_TRANSITIONS["terminated"] == set()
    assert "running" in VALID_TRANSITIONS["idle"]
    assert "rescheduling" in VALID_TRANSITIONS["running"]


async def test_create_starts_idle(services) -> None:
    svc, _, _ = services
    s = await svc.create(agent_id="ag", agent_version=1)
    assert s.status == "idle"


async def test_idle_to_running(services) -> None:
    svc, log, _ = services
    s = await svc.create(agent_id="ag", agent_version=1)
    started = await svc.start(s.id)
    assert started.status == "running"
    events = await log.get(s.id)
    assert any(e.type == "status" for e in events)
    last = [e for e in events if e.type == "status"][-1]
    assert last.payload["from"] == "idle"
    assert last.payload["to"] == "running"


async def test_running_to_idle_complete(services) -> None:
    svc, _, _ = services
    s = await svc.create(agent_id="ag", agent_version=1)
    await svc.start(s.id)
    done = await svc.complete(s.id)
    assert done.status == "idle"


async def test_running_to_rescheduling_and_resume(services) -> None:
    svc, _, _ = services
    s = await svc.create(agent_id="ag", agent_version=1)
    await svc.start(s.id)
    r = await svc.reschedule(s.id, reason="net flake")
    assert r.status == "rescheduling"
    back = await svc.resume(s.id)
    assert back.status == "running"


async def test_fail_transient_goes_rescheduling(services) -> None:
    svc, _, _ = services
    s = await svc.create(agent_id="ag", agent_version=1)
    await svc.start(s.id)
    failed = await svc.fail(s.id, reason="api error", transient=True)
    assert failed.status == "rescheduling"


async def test_fail_permanent_goes_terminated(services) -> None:
    svc, _, _ = services
    s = await svc.create(agent_id="ag", agent_version=1)
    await svc.start(s.id)
    failed = await svc.fail(s.id, reason="bad config", transient=False)
    assert failed.status == "terminated"


async def test_terminate_from_any_state(services) -> None:
    svc, _, _ = services
    for from_state in ("idle", "running", "rescheduling"):
        s = await svc.create(agent_id="ag", agent_version=1)
        if from_state in ("running", "rescheduling"):
            await svc.start(s.id)
        if from_state == "rescheduling":
            await svc.reschedule(s.id)
        terminated = await svc.terminate(s.id)
        assert terminated.status == "terminated"


async def test_invalid_transition_raises(services) -> None:
    svc, _, _ = services
    s = await svc.create(agent_id="ag", agent_version=1)
    # idle → rescheduling is not allowed
    with pytest.raises(InvalidTransitionError):
        await svc.reschedule(s.id)
    # idle → idle (via complete) is not allowed
    with pytest.raises(InvalidTransitionError):
        await svc.complete(s.id)


async def test_terminated_is_terminal(services) -> None:
    svc, _, _ = services
    s = await svc.create(agent_id="ag", agent_version=1)
    await svc.terminate(s.id)
    with pytest.raises(InvalidTransitionError):
        await svc.start(s.id)


async def test_idempotent_same_state(services) -> None:
    svc, log, _ = services
    s = await svc.create(agent_id="ag", agent_version=1)
    await svc.start(s.id)
    # Idempotent: calling start again returns running, doesn't emit a 2nd event.
    before = await log.count(s.id)
    await svc.start(s.id)
    after = await log.count(s.id)
    assert before == after


async def test_set_container_persists(services) -> None:
    svc, _, _ = services
    s = await svc.create(agent_id="ag", agent_version=1)
    updated = await svc.set_container(s.id, "ctn_42", "/work")
    assert updated.container_id == "ctn_42"
    assert updated.workspace_path == "/work"


async def test_get_missing_returns_none(services) -> None:
    svc, _, _ = services
    assert await svc.get("nope") is None


async def test_require_missing_raises(services) -> None:
    svc, _, _ = services
    with pytest.raises(InvalidTransitionError):
        await svc.require("nope")


async def test_list_filter(services) -> None:
    svc, _, _ = services
    a = await svc.create(agent_id="ag", agent_version=1)
    b = await svc.create(agent_id="ag", agent_version=1)
    await svc.start(b.id)
    idle = await svc.list(status="idle")
    running = await svc.list(status="running")
    assert {x.id for x in idle} == {a.id}
    assert {x.id for x in running} == {b.id}


async def test_delete(services) -> None:
    svc, _, _ = services
    s = await svc.create(agent_id="ag", agent_version=1)
    await svc.delete(s.id)
    assert await svc.get(s.id) is None
    with pytest.raises(InvalidTransitionError):
        await svc.require(s.id)
