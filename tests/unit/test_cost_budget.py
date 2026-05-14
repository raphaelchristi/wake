"""Cost-budget enforcement tests (Phase 7 — gap #7).

The enforcer reads ``agent.metadata.max_cost_usd`` and interrupts the
session when the running sum of ``event.metadata.cost_usd`` (or
``event.payload.cost_usd``) exceeds the budget. Critical contract bits
exercised here:

* No budget configured → never interrupts.
* Budget configured but spend under cap → no-op.
* Budget exceeded → interrupt event emitted with
  ``reason="cost_budget_exceeded"`` + session transitions to
  terminated.
* Bad budget data → silent no-op (warn-and-continue).
"""

from __future__ import annotations

import os
import tempfile
from decimal import Decimal

import pytest

from wake.core.event_log import EventLog
from wake.core.session import SessionService
from wake.runtime.cost_budget import (
    COST_BUDGET_REASON,
    CostBudgetEnforcer,
    event_cost,
    parse_budget,
)
from wake.store import SQLiteStore
from wake.types import AgentConfig, Event, ModelConfig


@pytest.fixture
async def env():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="wake-cb-test-")
    os.close(fd)
    s = SQLiteStore(f"sqlite+aiosqlite:///{path}")
    await s.initialize()
    log = EventLog(s.events)
    svc = SessionService(s.sessions, log)
    enforcer = CostBudgetEnforcer(log, svc)
    try:
        yield s, log, svc, enforcer
    finally:
        await s.close()
        os.unlink(path)


def _make_agent(metadata: dict[str, str] | None = None) -> AgentConfig:
    return AgentConfig(
        id="ag-test-budget",
        name="cost-budget-agent",
        model=ModelConfig(id="claude-opus-4-7"),
        system=None,
        tools=[],
        mcp_servers=[],
        skills=[],
        description=None,
        metadata=metadata or {},
        version=1,
        created_at="2026-05-14T00:00:00+00:00",  # type: ignore[arg-type]
        updated_at="2026-05-14T00:00:00+00:00",  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# parse_budget unit tests (pure function)
# ---------------------------------------------------------------------------


def test_parse_budget_missing_returns_none() -> None:
    assert parse_budget(None) is None
    assert parse_budget({}) is None
    assert parse_budget({"other": "value"}) is None


def test_parse_budget_zero_or_negative_returns_none() -> None:
    # Soft attribute: bad data → no enforcement (never crash).
    assert parse_budget({"max_cost_usd": "0"}) is None
    assert parse_budget({"max_cost_usd": "-5.0"}) is None


def test_parse_budget_accepts_string_and_number() -> None:
    assert parse_budget({"max_cost_usd": "10.5"}) == Decimal("10.5")
    assert parse_budget({"max_cost_usd": 10.5}) == Decimal("10.5")


def test_parse_budget_bad_data_returns_none() -> None:
    assert parse_budget({"max_cost_usd": "not-a-number"}) is None


def test_event_cost_sums_payload_and_metadata() -> None:
    ev = Event(
        id="01H00000000000000000000000",
        session_id="se1",
        seq=0,
        type="assistant.message",
        payload={"cost_usd": "0.25", "content": []},
        metadata={"cost_usd": "0.10"},
        created_at="2026-05-14T00:00:00+00:00",  # type: ignore[arg-type]
    )
    assert event_cost(ev) == Decimal("0.35")


def test_event_cost_handles_missing_and_bad_data() -> None:
    ev_missing = Event(
        id="01H00000000000000000000001",
        session_id="se1",
        seq=0,
        type="assistant.message",
        payload={"content": []},
        metadata=None,
        created_at="2026-05-14T00:00:00+00:00",  # type: ignore[arg-type]
    )
    assert event_cost(ev_missing) == Decimal("0")

    ev_bad = Event(
        id="01H00000000000000000000002",
        session_id="se1",
        seq=0,
        type="assistant.message",
        payload={"cost_usd": "not-a-number"},
        metadata=None,
        created_at="2026-05-14T00:00:00+00:00",  # type: ignore[arg-type]
    )
    assert event_cost(ev_bad) == Decimal("0")


# ---------------------------------------------------------------------------
# Enforcer integration tests
# ---------------------------------------------------------------------------


async def test_no_budget_means_no_enforcement(env) -> None:
    store, log, svc, enforcer = env
    sess = await svc.create(agent_id="ag", agent_version=1)
    # Pile up costs; no budget configured.
    for i in range(5):
        await log.append(
            sess.id,
            "assistant.message",
            {"content": [], "stop_reason": "end_turn"},
            metadata={"cost_usd": "100.00"},
        )
    agent_no_budget = _make_agent({})
    interrupted = await enforcer.check(sess.id, agent_no_budget)
    assert interrupted is False
    refreshed = await svc.get(sess.id)
    assert refreshed.status == "idle"


async def test_under_budget_no_interrupt(env) -> None:
    store, log, svc, enforcer = env
    sess = await svc.create(agent_id="ag", agent_version=1)
    await log.append(
        sess.id,
        "assistant.message",
        {"content": []},
        metadata={"cost_usd": "0.50"},
    )
    agent = _make_agent({"max_cost_usd": "1.00"})
    interrupted = await enforcer.check(sess.id, agent)
    assert interrupted is False
    refreshed = await svc.get(sess.id)
    assert refreshed.status == "idle"
    # No interrupt event written.
    events = await log.get(sess.id)
    assert not any(e.type == "interrupt" for e in events)


async def test_budget_exceeded_triggers_interrupt_event(env) -> None:
    store, log, svc, enforcer = env
    sess = await svc.create(agent_id="ag", agent_version=1)
    # Accumulate enough cost to bust a $1 budget.
    await log.append(
        sess.id,
        "assistant.message",
        {"content": []},
        metadata={"cost_usd": "0.60"},
    )
    await log.append(
        sess.id,
        "assistant.message",
        {"content": []},
        metadata={"cost_usd": "0.50"},
    )
    agent = _make_agent({"max_cost_usd": "1.00"})

    interrupted = await enforcer.check(sess.id, agent)
    assert interrupted is True

    # Interrupt event present with the right reason.
    events = await log.get(sess.id)
    interrupts = [e for e in events if e.type == "interrupt"]
    assert len(interrupts) == 1
    assert interrupts[0].payload["reason"] == COST_BUDGET_REASON
    assert interrupts[0].payload["metadata"]["budget_usd"] == "1.00"
    # Session terminated.
    refreshed = await svc.get(sess.id)
    assert refreshed.status == "terminated"


async def test_enforcer_idempotent_after_termination(env) -> None:
    """Calling check() again on a terminated session adds a second
    interrupt event but does NOT re-emit a status transition (which
    would fail because terminated is terminal). Validates the
    idempotent terminate() path inside SessionService.interrupt."""
    store, log, svc, enforcer = env
    sess = await svc.create(agent_id="ag", agent_version=1)
    await log.append(
        sess.id,
        "assistant.message",
        {"content": []},
        metadata={"cost_usd": "5.00"},
    )
    agent = _make_agent({"max_cost_usd": "1.00"})

    first = await enforcer.check(sess.id, agent)
    second = await enforcer.check(sess.id, agent)
    assert first is True and second is True  # both report "exceeded"
    # Both calls write an interrupt event (for audit completeness).
    events = await log.get(sess.id)
    interrupts = [e for e in events if e.type == "interrupt"]
    assert len(interrupts) == 2
    # Session is still terminated (no double-transition crashes).
    refreshed = await svc.get(sess.id)
    assert refreshed.status == "terminated"
