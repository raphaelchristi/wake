"""API tests for ``POST /v1/sessions/{id}/replay``.

Smokes the wiring:
  - 201 with a new session id and matching event count
  - 404 when the source session doesn't exist
  - Overrides flow through end-to-end (system_prompt + tools + max_steps)
  - The canary-aware session create surfaces ``agent_version`` metadata
"""

from __future__ import annotations

from typing import Any

import pytest

from wake.runtime.canary import CANARY_WEIGHT_KEY
from wake.types import ModelConfig

pytestmark = pytest.mark.asyncio


async def _seed_agent_and_session(client: Any, components: Any) -> tuple[str, str]:
    agent = await components["agent_store"].create(
        name="replayable",
        model=ModelConfig(id="claude-opus-4-7"),
        system="You are alpha.",
    )
    session = await components["session_store"].create(
        agent_id=agent.id, agent_version=agent.version
    )
    event_log = components["event_log"]
    await event_log.user_message(session.id, "hello")
    await event_log.assistant_message(session.id, "world")
    return agent.id, session.id


async def test_replay_returns_201_and_new_session(client, app_components) -> None:
    _, sid = await _seed_agent_and_session(client, app_components)
    resp = await client.post(
        f"/v1/sessions/{sid}/replay",
        json={},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["source_session_id"] == sid
    assert data["new_session_id"] != sid
    assert data["deterministic"] is True
    assert data["overrides_applied"] == []
    assert data["replayed_event_count"] >= 2


async def test_replay_404_when_source_missing(client) -> None:
    resp = await client.post(
        "/v1/sessions/sess_missing/replay",
        json={},
    )
    assert resp.status_code == 404


async def test_replay_with_system_prompt_override(client, app_components) -> None:
    _, sid = await _seed_agent_and_session(client, app_components)
    resp = await client.post(
        f"/v1/sessions/{sid}/replay",
        json={"system_prompt": "You are beta."},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["deterministic"] is False
    assert data["overrides_applied"] == ["system_prompt"]

    # Verify the override is durable on the new session metadata.
    new_id = data["new_session_id"]
    new_sess = await app_components["session_store"].get(new_id)
    assert new_sess is not None
    assert new_sess.metadata["replay_system_prompt"] == "You are beta."


async def test_replay_with_max_steps(client, app_components) -> None:
    aid = (
        await app_components["agent_store"].create(
            name="long",
            model=ModelConfig(id="claude-opus-4-7"),
        )
    ).id
    sess = await app_components["session_store"].create(
        agent_id=aid, agent_version=1
    )
    event_log = app_components["event_log"]
    for i in range(5):
        await event_log.user_message(sess.id, f"q{i}")
        await event_log.assistant_message(sess.id, f"a{i}")

    resp = await client.post(
        f"/v1/sessions/{sess.id}/replay",
        json={"max_steps": 2},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "max_steps" in data["overrides_applied"]


async def test_session_create_records_agent_version(client, app_components) -> None:
    """The Phase 8 canary integration stamps the chosen version on the
    new session's metadata so the dashboard can show it without a
    round-trip to the agent versions endpoint."""
    agent = await app_components["agent_store"].create(
        name="versioned",
        model=ModelConfig(id="claude-opus-4-7"),
    )
    resp = await client.post(
        "/v1/sessions",
        json={"agent_id": agent.id, "metadata": {}},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["metadata"]["agent_version"] == "1"
    assert "canary" not in body["metadata"]


async def test_session_create_marks_canary(client, app_components) -> None:
    agent = await app_components["agent_store"].create(
        name="canaried",
        model=ModelConfig(id="claude-opus-4-7"),
    )
    # Promote to canary at 100% so the selection is deterministic.
    await app_components["agent_store"].update(
        agent.id,
        metadata={CANARY_WEIGHT_KEY: "100"},
    )
    resp = await client.post(
        "/v1/sessions",
        json={"agent_id": agent.id, "metadata": {}},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["metadata"]["agent_version"] == "2"
    assert body["metadata"]["canary"] == "true"


async def test_replay_with_tools_override(client, app_components) -> None:
    aid = (
        await app_components["agent_store"].create(
            name="with-tools",
            model=ModelConfig(id="claude-opus-4-7"),
        )
    ).id
    sess = await app_components["session_store"].create(
        agent_id=aid, agent_version=1
    )
    event_log = app_components["event_log"]
    await event_log.user_message(sess.id, "go")
    await event_log.append(
        sess.id,
        "tool_use",
        {"tool_use_id": "tu_0", "name": "bash", "input": {}},
    )

    resp = await client.post(
        f"/v1/sessions/{sess.id}/replay",
        json={"tools": [{"type": "file_read", "config": {}}]},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "tools" in data["overrides_applied"]

    new_id = data["new_session_id"]
    events = await app_components["event_log"].get(new_id)
    tool_uses = [e for e in events if e.type == "tool_use"]
    assert tool_uses
    # The bash call (now removed) is flagged but still copied for audit.
    for ev in tool_uses:
        assert ev.metadata is not None
        assert ev.metadata.get("replay_warning") == "tool_removed"
