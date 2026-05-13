"""Tests for ``WakeToolRegistry`` — adapter view over wake.tools.registry."""

from __future__ import annotations

from typing import Any

import pytest

from wake.runtime.tool_registry import WakeToolRegistry
from wake.tools.base import Tool
from wake.tools.registry import ToolRegistry as WakeToolsRegistry
from wake.types import (
    SandboxHandle,
    TextBlock,
    ToolDescriptor,
    ToolResult,
)


class _Echo(Tool):
    @property
    def descriptor(self) -> ToolDescriptor:
        return ToolDescriptor(
            name="echo",
            description="echo back",
            schema={"type": "object", "properties": {"text": {"type": "string"}}},
        )

    async def execute(
        self, input: dict[str, Any], sandbox: SandboxHandle | None  # noqa: A002, ARG002
    ) -> ToolResult:
        return ToolResult(content=[TextBlock(text=str(input.get("text", "")))])


@pytest.fixture
def wrapped() -> WakeToolRegistry:
    inner = WakeToolsRegistry()
    inner.register(_Echo())
    return WakeToolRegistry(inner)


@pytest.mark.asyncio
async def test_list_returns_descriptors(wrapped: WakeToolRegistry) -> None:
    descs = wrapped.list()
    assert len(descs) == 1
    assert descs[0].name == "echo"


@pytest.mark.asyncio
async def test_get_known_tool(wrapped: WakeToolRegistry) -> None:
    d = wrapped.get("echo")
    assert d.name == "echo"


@pytest.mark.asyncio
async def test_get_unknown_raises_key_error(wrapped: WakeToolRegistry) -> None:
    with pytest.raises(KeyError):
        wrapped.get("missing")


@pytest.mark.asyncio
async def test_execute_known_tool(wrapped: WakeToolRegistry) -> None:
    result = await wrapped.execute("echo", {"text": "hi"}, tool_use_id="tu_1")
    assert result.is_error is False
    assert result.content[0].text == "hi"


@pytest.mark.asyncio
async def test_execute_unknown_tool_returns_not_found(
    wrapped: WakeToolRegistry,
) -> None:
    result = await wrapped.execute("nope", {}, tool_use_id="tu_2")
    assert result.is_error is True
    assert result.error_code == "not_found"
    assert "unknown tool" in result.content[0].text


@pytest.mark.asyncio
async def test_execute_passes_sandbox_handle(monkeypatch: pytest.MonkeyPatch) -> None:
    """The wrapper forwards its bound sandbox_handle through to the registry."""
    inner = WakeToolsRegistry()
    inner.register(_Echo())

    captured: dict[str, Any] = {}
    original = inner.execute

    async def _spy(
        name: str,
        input: dict[str, Any],  # noqa: A002
        sandbox_handle: SandboxHandle | None = None,
    ) -> ToolResult:
        captured["handle"] = sandbox_handle
        return await original(name, input, sandbox_handle=sandbox_handle)

    monkeypatch.setattr(inner, "execute", _spy)

    handle = SandboxHandle(
        backend="docker",
        container_id="c1",
        workspace_path="/w",
        created_at=__import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ),
    )
    adapter_view = WakeToolRegistry(inner, sandbox_handle=handle)
    await adapter_view.execute("echo", {"text": "x"}, tool_use_id="tu")
    assert captured["handle"] is handle
