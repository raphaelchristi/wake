"""Smoke tests for canonical types.

We do not modify ``wake.types`` from this slice — these tests only
verify that the module is importable and the types behave as documented.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from wake.types import (
    AgentConfig,
    ContentBlock,
    EnvironmentConfig,
    Event,
    ImageBlock,
    McpServerConfig,
    ModelConfig,
    SandboxHandle,
    Session,
    TextBlock,
    ToolConfig,
    ToolDescriptor,
    ToolResult,
    ToolResultBlock,
    ToolUseBlock,
)


def test_event_is_frozen() -> None:
    now = datetime.now(UTC)
    ev = Event(
        id="01" + "A" * 24,
        session_id="sess_1",
        seq=0,
        type="user.message",
        payload={"content": [{"type": "text", "text": "hi"}]},
        created_at=now,
    )
    with pytest.raises(Exception):  # noqa: B017 — pydantic raises ValidationError
        ev.seq = 1  # type: ignore[misc]


def test_event_round_trip_dict() -> None:
    now = datetime.now(UTC)
    payload = {"content": [{"type": "text", "text": "hi"}]}
    ev = Event(
        id="01" + "A" * 24,
        session_id="sess_x",
        seq=3,
        type="user.message",
        payload=payload,
        created_at=now,
    )
    d = ev.model_dump()
    assert d["id"] == ev.id
    assert d["seq"] == 3
    assert d["type"] == "user.message"


def test_content_blocks_match_spec() -> None:
    t = TextBlock(text="hello")
    assert t.type == "text"
    img = ImageBlock(source={"type": "base64", "media_type": "image/png", "data": "x"})
    assert img.type == "image"
    tu = ToolUseBlock(id="toolu_1", name="bash", input={"command": "ls"})
    assert tu.type == "tool_use"
    tr = ToolResultBlock(tool_use_id="toolu_1", content=[TextBlock(text="ok")])
    assert tr.type == "tool_result" and tr.is_error is False


def test_content_block_union() -> None:
    # ContentBlock is a union; runtime check is just by isinstance.
    blocks: list[ContentBlock] = [
        TextBlock(text="x"),
        ToolUseBlock(id="t1", name="n", input={}),
    ]
    assert isinstance(blocks[0], TextBlock)
    assert isinstance(blocks[1], ToolUseBlock)


def test_model_and_tool_configs() -> None:
    m = ModelConfig(id="claude-opus-4-7")
    assert m.provider == "anthropic" and m.speed == "standard"
    tc = ToolConfig(type="bash")
    assert tc.config == {}
    mc = McpServerConfig(name="fs", transport="stdio")
    assert mc.transport == "stdio"


def test_agent_environment_session_minimal() -> None:
    now = datetime.now(UTC)
    a = AgentConfig(
        id="ag1",
        name="bot",
        model=ModelConfig(id="claude"),
        created_at=now,
        updated_at=now,
    )
    assert a.version == 1 and a.archived_at is None
    e = EnvironmentConfig(id="env1", name="default", config={}, created_at=now)
    assert e.archived_at is None
    s = Session(
        id="sess1",
        agent_id=a.id,
        agent_version=1,
        created_at=now,
        updated_at=now,
    )
    assert s.status == "idle"


def test_sandbox_and_tool_result() -> None:
    now = datetime.now(UTC)
    h = SandboxHandle(
        backend="docker",
        container_id="c1",
        workspace_path="/work",
        created_at=now,
    )
    assert h.backend == "docker"
    td = ToolDescriptor(name="bash", description="run shell", schema={})
    assert td.requires_sandbox is False
    tr = ToolResult(content=[TextBlock(text="done")])
    assert tr.is_error is False and tr.error_code is None
