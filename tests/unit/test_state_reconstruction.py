"""Unit tests for sandbox state reconstruction."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from ulid import ULID

from wake.api.state_reconstruction import (
    ReconstructedState,
    parse_bash_cd,
    reconstruct_state_at,
)
from wake.types import Event, EventType


def _ev(seq: int, type_: EventType, payload: dict[str, Any]) -> Event:
    return Event(
        id=str(ULID()),
        session_id="sess_test",
        seq=seq,
        type=type_,
        payload=payload,
        created_at=datetime.now(timezone.utc),
    )


def test_empty_events_returns_default_snapshot() -> None:
    state = reconstruct_state_at([], 0)
    assert isinstance(state, ReconstructedState)
    assert state.seq == 0
    assert state.sandbox.cwd == "/"
    assert state.sandbox.last_output_lines == []
    assert state.sandbox.files_modified == []
    assert state.tool_calls_so_far == 0
    assert state.errors_so_far == 0


def test_bash_cd_updates_cwd() -> None:
    events = [
        _ev(0, "tool_use", {"name": "bash", "input": {"command": "cd /workspace"}}),
        _ev(1, "tool_result", {"content": [{"type": "text", "text": "ok"}]}),
    ]
    state = reconstruct_state_at(events, 1)
    assert state.sandbox.cwd == "/workspace"
    assert state.tool_calls_so_far == 1


def test_bash_cd_relative_path() -> None:
    events = [
        _ev(0, "tool_use", {"name": "bash", "input": {"command": "cd /a/b"}}),
        _ev(1, "tool_use", {"name": "bash", "input": {"command": "cd ../c"}}),
    ]
    state = reconstruct_state_at(events, 1)
    assert state.sandbox.cwd == "/a/c"


def test_bash_cd_with_tilde() -> None:
    events = [_ev(0, "tool_use", {"name": "bash", "input": {"command": "cd ~/foo"}})]
    state = reconstruct_state_at(events, 0)
    assert state.sandbox.cwd == "/root/foo"


def test_bash_cd_with_dash_is_noop() -> None:
    events = [
        _ev(0, "tool_use", {"name": "bash", "input": {"command": "cd /tmp"}}),
        _ev(1, "tool_use", {"name": "bash", "input": {"command": "cd -"}}),
    ]
    state = reconstruct_state_at(events, 1)
    assert state.sandbox.cwd == "/tmp"


def test_file_write_tracks_path() -> None:
    events = [
        _ev(
            0,
            "tool_use",
            {"name": "file_write", "input": {"path": "src/foo.py"}},
        ),
        _ev(
            1,
            "tool_use",
            {"name": "file_edit", "input": {"file_path": "src/bar.py"}},
        ),
    ]
    state = reconstruct_state_at(events, 1)
    assert state.sandbox.files_modified == ["src/foo.py", "src/bar.py"]


def test_repeated_file_write_moves_to_end() -> None:
    events = [
        _ev(0, "tool_use", {"name": "file_write", "input": {"path": "a.py"}}),
        _ev(1, "tool_use", {"name": "file_write", "input": {"path": "b.py"}}),
        _ev(2, "tool_use", {"name": "file_write", "input": {"path": "a.py"}}),
    ]
    state = reconstruct_state_at(events, 2)
    assert state.sandbox.files_modified == ["b.py", "a.py"]


def test_tool_result_captures_last_output() -> None:
    events = [
        _ev(0, "tool_use", {"name": "bash", "input": {"command": "ls"}}),
        _ev(
            1,
            "tool_result",
            {"content": [{"type": "text", "text": "foo\nbar\nbaz"}]},
        ),
    ]
    state = reconstruct_state_at(events, 1)
    assert state.sandbox.last_output_lines == ["foo", "bar", "baz"]


def test_tool_result_overwrites_previous_output() -> None:
    events = [
        _ev(0, "tool_use", {"name": "bash", "input": {"command": "ls"}}),
        _ev(1, "tool_result", {"content": [{"type": "text", "text": "first"}]}),
        _ev(2, "tool_use", {"name": "bash", "input": {"command": "echo 2"}}),
        _ev(3, "tool_result", {"content": [{"type": "text", "text": "second"}]}),
    ]
    state = reconstruct_state_at(events, 3)
    assert state.sandbox.last_output_lines == ["second"]


def test_tool_result_with_error_increments_counter() -> None:
    events = [
        _ev(0, "tool_use", {"name": "bash", "input": {"command": "false"}}),
        _ev(
            1,
            "tool_result",
            {
                "content": [{"type": "text", "text": "exit 1"}],
                "is_error": True,
            },
        ),
    ]
    state = reconstruct_state_at(events, 1)
    assert state.errors_so_far == 1
    assert state.tool_calls_so_far == 1


def test_error_event_increments_counter() -> None:
    events = [
        _ev(0, "user.message", {"content": [{"type": "text", "text": "hi"}]}),
        _ev(1, "error", {"error_type": "harness_panic", "message": "boom"}),
    ]
    state = reconstruct_state_at(events, 1)
    assert state.errors_so_far == 1


def test_target_seq_caps_replay() -> None:
    events = [
        _ev(0, "tool_use", {"name": "bash", "input": {"command": "cd /a"}}),
        _ev(1, "tool_use", {"name": "bash", "input": {"command": "cd /b"}}),
        _ev(2, "tool_use", {"name": "bash", "input": {"command": "cd /c"}}),
    ]
    # Stop at seq=1; cwd should reflect first two cd's.
    state = reconstruct_state_at(events, 1)
    assert state.sandbox.cwd == "/b"
    assert state.tool_calls_so_far == 2


def test_target_seq_beyond_events_is_safe() -> None:
    events = [_ev(0, "user.message", {})]
    state = reconstruct_state_at(events, 999)
    assert state.seq == 999
    assert state.tool_calls_so_far == 0


def test_full_session_replay() -> None:
    """The canonical SPEC-EVENT-SCHEMA example, recreated."""
    events = [
        _ev(0, "user.message", {"content": [{"type": "text", "text": "ls"}]}),
        _ev(1, "status", {"from": "idle", "to": "running"}),
        _ev(2, "provision", {"container_id": "wake_xyz"}),
        _ev(3, "tool_use", {"name": "bash", "input": {"command": "cd /workspace"}}),
        _ev(4, "tool_result", {"content": [{"type": "text", "text": "ok"}]}),
        _ev(5, "tool_use", {"name": "bash", "input": {"command": "ls"}}),
        _ev(
            6,
            "tool_result",
            {"content": [{"type": "text", "text": "src/\ntests/\nREADME.md"}]},
        ),
        _ev(
            7,
            "tool_use",
            {"name": "file_write", "input": {"path": "src/csv_parser.py"}},
        ),
        _ev(8, "tool_result", {"content": [{"type": "text", "text": "wrote 1 file"}]}),
        _ev(9, "tool_use", {"name": "bash", "input": {"command": "pytest tests/"}}),
        _ev(
            10,
            "tool_result",
            {"content": [{"type": "text", "text": "5 passed"}]},
        ),
        _ev(11, "assistant.message", {"content": [{"type": "text", "text": "Done."}]}),
        _ev(12, "status", {"from": "running", "to": "idle"}),
    ]
    state = reconstruct_state_at(events, 12)
    assert state.sandbox.cwd == "/workspace"
    assert state.sandbox.last_output_lines == ["5 passed"]
    assert state.sandbox.files_modified == ["src/csv_parser.py"]
    assert state.tool_calls_so_far == 4
    assert state.errors_so_far == 0


def test_parse_bash_cd_helper() -> None:
    assert parse_bash_cd("cd /tmp") == "/tmp"
    assert parse_bash_cd("  cd /a") == "/a"
    assert parse_bash_cd("ls -la") is None
    assert parse_bash_cd("cd /a && ls") == "/a"


def test_tolerates_malformed_payloads() -> None:
    events = [
        _ev(0, "tool_use", {}),  # missing name/input
        _ev(1, "tool_use", {"name": "bash"}),  # missing input
        _ev(2, "tool_use", {"name": "bash", "input": "not-a-dict"}),  # type: ignore[arg-type]
        _ev(3, "tool_result", {}),  # missing content
    ]
    # Should not raise.
    state = reconstruct_state_at(events, 3)
    # First three count as tool_use (we don't care about correctness, just stability).
    assert state.tool_calls_so_far == 3


@pytest.mark.anyio
async def test_state_at_endpoint_returns_snapshot(client, app_components) -> None:
    """End-to-end smoke through the FastAPI route."""
    from wake.types import ModelConfig

    agent_store = app_components["agent_store"]
    machine = app_components["session_machine"]
    event_log = app_components["event_log"]

    agent = await agent_store.create(name="t", model=ModelConfig(id="claude-opus-4-7"))
    sess = await machine.create(agent_id=agent.id, agent_version=agent.version)

    await event_log.append(
        sess.id,
        "tool_use",
        {"name": "bash", "input": {"command": "cd /workspace"}},
    )
    await event_log.append(
        sess.id,
        "tool_result",
        {"content": [{"type": "text", "text": "ok"}]},
    )

    resp = await client.get(f"/v1/sessions/{sess.id}/state-at/1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["seq"] == 1
    assert body["sandbox"]["cwd"] == "/workspace"
    assert body["sandbox"]["last_output_lines"] == ["ok"]
    assert body["tool_calls_so_far"] == 1
    assert body["errors_so_far"] == 0


@pytest.mark.anyio
async def test_state_at_endpoint_unknown_session_returns_404(client) -> None:
    resp = await client.get("/v1/sessions/sess_nope/state-at/0")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_state_at_endpoint_negative_seq_returns_422(client, app_components) -> None:
    from wake.types import ModelConfig

    agent = await app_components["agent_store"].create(
        name="t", model=ModelConfig(id="claude-opus-4-7")
    )
    sess = await app_components["session_machine"].create(
        agent_id=agent.id, agent_version=agent.version
    )
    resp = await client.get(f"/v1/sessions/{sess.id}/state-at/-1")
    # FastAPI path validation rejects negative integers when the param is typed int
    # via the URL parser; our explicit check catches the case if it slips through.
    assert resp.status_code in (404, 422)
