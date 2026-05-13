"""Tests for tools, registry, and built-ins."""

from __future__ import annotations

from typing import Any

import pytest

from wake.sandbox.base import SandboxAdapter
from wake.tools.base import Tool, ToolExecutionError
from wake.tools.builtin import BashTool, FileEditTool, FileReadTool, FileWriteTool
from wake.tools.registry import ToolRegistry
from wake.types import (
    EnvironmentConfig,
    SandboxHandle,
    TextBlock,
    ToolDescriptor,
    ToolResult,
)


class _EchoTool(Tool):
    @property
    def descriptor(self) -> ToolDescriptor:
        return ToolDescriptor(
            name="echo",
            description="echo",
            schema={"type": "object", "properties": {"text": {"type": "string"}}},
            requires_sandbox=False,
        )

    async def execute(self, input: dict[str, Any], sandbox: SandboxHandle | None) -> ToolResult:
        return ToolResult(content=[TextBlock(text=input.get("text", ""))])


class _BoomTool(Tool):
    @property
    def descriptor(self) -> ToolDescriptor:
        return ToolDescriptor(
            name="boom",
            description="raises",
            schema={"type": "object"},
            requires_sandbox=False,
        )

    async def execute(self, input: dict[str, Any], sandbox: SandboxHandle | None) -> ToolResult:
        raise ToolExecutionError("kaboom", error_code="invalid_tool_input")


class _PanicTool(Tool):
    @property
    def descriptor(self) -> ToolDescriptor:
        return ToolDescriptor(
            name="panic",
            description="raises bare",
            schema={"type": "object"},
            requires_sandbox=False,
        )

    async def execute(self, input: dict[str, Any], sandbox: SandboxHandle | None) -> ToolResult:
        raise RuntimeError("unexpected")


class _FakeSandbox(SandboxAdapter):
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def provision(self, env: EnvironmentConfig) -> SandboxHandle:
        raise NotImplementedError

    async def execute(
        self, handle: SandboxHandle, tool_name: str, input: dict[str, Any]
    ) -> ToolResult:
        self.calls.append((tool_name, input))
        return ToolResult(content=[TextBlock(text=f"sandboxed {tool_name}")])

    async def destroy(self, handle: SandboxHandle) -> None:
        return None


def _fake_handle() -> SandboxHandle:
    from datetime import datetime, timezone

    return SandboxHandle(
        backend="fake",
        container_id="c1",
        workspace_path="/workspace",
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_register_and_list() -> None:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    assert reg.get("echo") is not None
    assert [t.descriptor.name for t in reg.list()] == ["echo"]


@pytest.mark.asyncio
async def test_register_duplicate_raises() -> None:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    with pytest.raises(ValueError):
        reg.register(_EchoTool())


@pytest.mark.asyncio
async def test_unregister() -> None:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    reg.unregister("echo")
    assert reg.get("echo") is None


@pytest.mark.asyncio
async def test_execute_host_tool() -> None:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    res = await reg.execute("echo", {"text": "hello"})
    assert not res.is_error
    assert res.content[0].text == "hello"


@pytest.mark.asyncio
async def test_execute_unknown_tool() -> None:
    reg = ToolRegistry()
    res = await reg.execute("nope", {})
    assert res.is_error
    assert res.error_code == "not_found"


@pytest.mark.asyncio
async def test_execute_tool_execution_error_caught() -> None:
    reg = ToolRegistry()
    reg.register(_BoomTool())
    res = await reg.execute("boom", {})
    assert res.is_error
    assert res.error_code == "invalid_tool_input"


@pytest.mark.asyncio
async def test_execute_unexpected_error_caught() -> None:
    reg = ToolRegistry()
    reg.register(_PanicTool())
    res = await reg.execute("panic", {})
    assert res.is_error
    assert res.error_code == "unknown"


@pytest.mark.asyncio
async def test_sandbox_routing() -> None:
    sandbox = _FakeSandbox()
    reg = ToolRegistry(sandbox=sandbox)
    reg.register(BashTool())
    handle = _fake_handle()
    res = await reg.execute("bash", {"command": "echo hi"}, sandbox_handle=handle)
    assert not res.is_error
    assert "sandboxed bash" in res.content[0].text
    assert sandbox.calls == [("bash", {"command": "echo hi"})]


@pytest.mark.asyncio
async def test_bash_without_sandbox_errors() -> None:
    reg = ToolRegistry()
    reg.register(BashTool())
    res = await reg.execute("bash", {"command": "echo hi"})
    assert res.is_error
    assert res.error_code == "unavailable"


@pytest.mark.asyncio
async def test_file_tools_without_sandbox() -> None:
    reg = ToolRegistry()
    for t in (FileReadTool(), FileWriteTool(), FileEditTool()):
        reg.register(t)
    for name in ("file_read", "file_write", "file_edit"):
        res = await reg.execute(name, {"path": "x", "content": "y", "old_string": "a", "new_string": "b"})
        assert res.is_error


def test_descriptors() -> None:
    reg = ToolRegistry()
    reg.register(BashTool())
    reg.register(FileReadTool())
    descs = reg.descriptors()
    names = [d.name for d in descs]
    assert "bash" in names
    assert "file_read" in names


def test_anthropic_tools_shape() -> None:
    reg = ToolRegistry()
    reg.register(BashTool())
    out = reg.anthropic_tools()
    assert len(out) == 1
    assert out[0]["name"] == "bash"
    assert "input_schema" in out[0]
    assert "description" in out[0]


def test_builtin_descriptors() -> None:
    # smoke: descriptors compile and look sensible
    for t in (BashTool(), FileReadTool(), FileWriteTool(), FileEditTool()):
        d = t.descriptor
        assert d.requires_sandbox
        assert d.schema["type"] == "object"
