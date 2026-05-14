"""Unit tests for ``wake.runtime.replay_engine``.

Covers:

* Deterministic replay without overrides reproduces the source log.
* ``system_prompt`` override records on the new session metadata and
  emits a ``status`` event.
* ``tools`` override is recorded + flags tool_use events that reference
  removed tools.
* ``max_steps`` override truncates the replay + emits a status event.
* Replaying twice with the same overrides yields the same event sequence.
* Missing source session / archived agent raise ``ReplayError``.
* The dashboard projection helper ``project_overrides_into_messages``
  inserts the system prompt at the head of the messages list.
"""

from __future__ import annotations

import pytest

from tests.unit.fakes import (
    InMemoryAgentStore,
    InMemoryEventStore,
    InMemorySessionStore,
)
from wake.core.event_log import EventLog
from wake.runtime.replay_engine import (
    DEFAULT_MAX_STEPS,
    ReplayEngine,
    ReplayError,
    project_overrides_into_messages,
)
from wake.types import ModelConfig, ReplayRequest, ToolConfig


pytestmark = pytest.mark.asyncio


async def _build_stack() -> tuple[
    InMemoryAgentStore,
    InMemorySessionStore,
    InMemoryEventStore,
    EventLog,
]:
    return (
        InMemoryAgentStore(),
        InMemorySessionStore(),
        InMemoryEventStore(),
        EventLog(InMemoryEventStore()),  # placeholder; overwritten below
    )


async def _seed_session(
    n_assistant_turns: int = 2,
    tools: list[ToolConfig] | None = None,
    session_seed: str | None = None,
) -> tuple[
    ReplayEngine,
    InMemoryAgentStore,
    InMemorySessionStore,
    InMemoryEventStore,
    EventLog,
    str,
    str,
]:
    agent_store = InMemoryAgentStore()
    session_store = InMemorySessionStore()
    event_store = InMemoryEventStore()
    event_log = EventLog(event_store)

    agent = await agent_store.create(
        name="alpha",
        model=ModelConfig(id="claude-opus-4-7"),
        system="You are alpha.",
        tools=list(tools or []),
        metadata={},
    )
    session_meta = {"seed": session_seed} if session_seed else {}
    session = await session_store.create(
        agent_id=agent.id,
        agent_version=agent.version,
        metadata=session_meta,
    )
    # Seed a realistic source log.
    await event_log.user_message(session.id, "hello")
    for i in range(n_assistant_turns):
        await event_log.assistant_message(session.id, f"reply {i}")
        await event_log.append(
            session.id,
            "tool_use",
            {"tool_use_id": f"tu_{i}", "name": "bash", "input": {"cmd": "ls"}},
        )
        await event_log.append(
            session.id,
            "tool_result",
            {"tool_use_id": f"tu_{i}", "content": [], "is_error": False},
        )
    # Status events from the source session — should NOT carry into replay.
    await event_log.status(session.id, from_="running", to="idle", reason="end")

    engine = ReplayEngine(session_store, agent_store, event_log)
    return engine, agent_store, session_store, event_store, event_log, agent.id, session.id


async def test_replay_without_overrides_is_deterministic() -> None:
    """Two replays of the same source produce the same copyable event types."""
    engine, _agent_store, session_store, _event_store, event_log, _aid, sid = (
        await _seed_session(n_assistant_turns=2)
    )

    result_a = await engine.replay(sid, ReplayRequest())
    result_b = await engine.replay(sid, ReplayRequest())

    assert result_a.deterministic is True
    assert result_b.deterministic is True
    assert result_a.new_session_id != result_b.new_session_id
    # Same source → same seed (derived from hash of source id).
    assert result_a.seed == result_b.seed

    events_a = await event_log.get(result_a.new_session_id)
    events_b = await event_log.get(result_b.new_session_id)

    # Same sequence of event types — status events from the source are
    # filtered out, the rest carries through verbatim.
    types_a = [e.type for e in events_a]
    types_b = [e.type for e in events_b]
    assert types_a == types_b
    assert "status" not in types_a  # source status not copied
    assert types_a.count("assistant.message") == 2
    assert types_a.count("user.message") == 1


async def test_replay_carries_payloads_verbatim() -> None:
    engine, *_rest, event_log, _aid, sid = await _seed_session(n_assistant_turns=1)
    src_events = await event_log.get(sid)

    result = await engine.replay(sid, ReplayRequest())
    new_events = await event_log.get(result.new_session_id)

    src_user = next(e for e in src_events if e.type == "user.message")
    new_user = next(e for e in new_events if e.type == "user.message")
    assert new_user.payload == src_user.payload


async def test_system_prompt_override_recorded() -> None:
    engine, _agent_store, session_store, _event_store, event_log, _aid, sid = (
        await _seed_session()
    )
    result = await engine.replay(
        sid,
        ReplayRequest(system_prompt="You are beta now."),
    )
    assert result.deterministic is False
    assert "system_prompt" in result.overrides_applied

    new_sess = await session_store.get(result.new_session_id)
    assert new_sess is not None
    assert new_sess.metadata["replay_system_prompt"] == "You are beta now."
    assert new_sess.metadata["replay_of"] == sid

    events = await event_log.get(result.new_session_id)
    # First event must be the override status marker.
    assert events[0].type == "status"
    assert events[0].payload.get("override") == "system_prompt"


async def test_tools_override_flags_removed_tools() -> None:
    tools = [ToolConfig(type="bash"), ToolConfig(type="file_read")]
    engine, *_rest, event_log, _aid, sid = await _seed_session(tools=tools)

    # Replay with only "file_read" allowed → bash calls must be flagged.
    result = await engine.replay(
        sid,
        ReplayRequest(tools=[ToolConfig(type="file_read")]),
    )
    assert "tools" in result.overrides_applied

    events = await event_log.get(result.new_session_id)
    tool_uses = [e for e in events if e.type == "tool_use"]
    assert tool_uses, "source seeded with tool_use events"
    for ev in tool_uses:
        meta = ev.metadata or {}
        assert meta.get("replay_warning") == "tool_removed"


async def test_max_steps_truncates_replay() -> None:
    engine, *_rest, event_log, _aid, sid = await _seed_session(n_assistant_turns=5)

    result = await engine.replay(sid, ReplayRequest(max_steps=2))
    assert "max_steps" in result.overrides_applied
    events = await event_log.get(result.new_session_id)
    assistant_turns = [e for e in events if e.type == "assistant.message"]
    # Cap is enforced — replay stops at 2 assistant turns.
    assert len(assistant_turns) == 2
    truncation_marker = [
        e for e in events if e.type == "status" and e.payload.get("truncated")
    ]
    assert truncation_marker, "engine emits a truncation status event"


async def test_default_max_steps_constant_is_reasonable() -> None:
    # Sanity: cap is high enough that normal sessions never get clipped.
    assert DEFAULT_MAX_STEPS >= 16


async def test_replay_missing_source_raises() -> None:
    agent_store = InMemoryAgentStore()
    session_store = InMemorySessionStore()
    event_log = EventLog(InMemoryEventStore())
    engine = ReplayEngine(session_store, agent_store, event_log)

    with pytest.raises(ReplayError):
        await engine.replay("sess_does_not_exist", ReplayRequest())


async def test_replay_missing_agent_version_raises() -> None:
    """When the agent's pinned version was archived we surface a clean error."""
    agent_store = InMemoryAgentStore()
    session_store = InMemorySessionStore()
    event_log = EventLog(InMemoryEventStore())

    sess = await session_store.create(
        agent_id="agent_ghost", agent_version=99
    )
    engine = ReplayEngine(session_store, agent_store, event_log)

    with pytest.raises(ReplayError):
        await engine.replay(sess.id, ReplayRequest())


async def test_seed_inherits_when_unset() -> None:
    engine, *_rest, _event_log, _aid, sid = await _seed_session(session_seed="42")
    # Source seeded metadata["seed"]="42" → replay should inherit.
    result = await engine.replay(sid, ReplayRequest())
    assert result.seed == 42


async def test_seed_derives_from_source_when_no_seed_metadata() -> None:
    """No seed anywhere → engine derives a stable seed from the source
    session id so the same source always gets the same default seed."""
    engine, *_rest, _event_log, _aid, sid = await _seed_session()
    result_a = await engine.replay(sid, ReplayRequest())
    result_b = await engine.replay(sid, ReplayRequest())
    # Same source → same fallback seed (hash-based, stable).
    assert result_a.seed == result_b.seed


async def test_seed_override_takes_precedence() -> None:
    engine, *_rest, _event_log, _aid, sid = await _seed_session()
    result = await engine.replay(sid, ReplayRequest(seed=999))
    assert result.seed == 999


async def test_project_overrides_into_messages_inserts_system_prompt() -> None:
    """Pure helper: the dashboard uses this to render the diff.

    Declared ``async`` only to silence the asyncio_mode=auto marker
    that applies module-wide via ``pytestmark``. The body itself is
    pure synchronous logic.
    """
    from datetime import UTC, datetime

    from wake.types import Event

    events = [
        Event(
            id="01" + "0" * 24,
            session_id="s1",
            seq=0,
            type="user.message",
            payload={"content": [{"type": "text", "text": "hi"}]},
            created_at=datetime.now(UTC),
        )
    ]
    msgs_no_override = project_overrides_into_messages(events, {})
    assert len(msgs_no_override) == 1
    assert msgs_no_override[0]["role"] == "user"

    msgs = project_overrides_into_messages(
        events,
        {"system_prompt": "new system"},
    )
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"][0]["text"] == "new system"
    assert msgs[1]["role"] == "user"
