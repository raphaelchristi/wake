# ruff: noqa: A002, TC001
"""Tool registry: register tools and dispatch executions.

The registry is the harness's view of "what tools can I call?". Each Wake
session uses one registry (typically populated from the agent's tool config).
"""

from __future__ import annotations

import builtins
from typing import Any

import structlog

from wake.sandbox.base import SandboxAdapter
from wake.tools.base import Tool, ToolExecutionError
from wake.types import SandboxHandle, TextBlock, ToolDescriptor, ToolResult

logger = structlog.get_logger(__name__)


class ToolRegistry:
    """Holds registered tools and dispatches execute calls."""

    def __init__(self, sandbox: SandboxAdapter | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        self._sandbox = sandbox

    def register(self, tool: Tool) -> None:
        name = tool.descriptor.name
        if name in self._tools:
            raise ValueError(f"tool {name!r} already registered")
        self._tools[name] = tool
        logger.debug("tool_registered", name=name)

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list(self) -> builtins.list[Tool]:
        return list(self._tools.values())

    def descriptors(self) -> builtins.list[ToolDescriptor]:
        return [t.descriptor for t in self._tools.values()]

    def anthropic_tools(self) -> builtins.list[dict[str, Any]]:
        """Render the registry as the `tools` argument to the Anthropic Messages API."""
        out: builtins.list[dict[str, Any]] = []
        for t in self._tools.values():
            d = t.descriptor
            out.append(
                {
                    "name": d.name,
                    "description": d.description,
                    "input_schema": d.schema,
                }
            )
        return out

    async def execute(
        self,
        name: str,
        input: dict[str, Any],
        sandbox_handle: SandboxHandle | None = None,
    ) -> ToolResult:
        """Execute a tool by name.

        If the tool requires a sandbox and `sandbox_handle` is given, the tool
        runs inside the sandbox via the registry's SandboxAdapter. Otherwise the
        tool's own `execute` is invoked (host-side).
        """
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                content=[TextBlock(text=f"unknown tool: {name}")],
                is_error=True,
                error_code="not_found",
            )

        try:
            if tool.descriptor.requires_sandbox and sandbox_handle is not None and self._sandbox is not None:
                logger.debug("tool_execute_sandbox", name=name)
                return await self._sandbox.execute(sandbox_handle, name, input)
            logger.debug("tool_execute_host", name=name)
            return await tool.execute(input, sandbox_handle)
        except ToolExecutionError as e:
            logger.warning("tool_execution_error", name=name, error=str(e))
            return ToolResult(
                content=[TextBlock(text=str(e))],
                is_error=True,
                error_code=e.error_code,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("tool_unexpected_error", name=name)
            return ToolResult(
                content=[TextBlock(text=f"unexpected error: {e}")],
                is_error=True,
                error_code="unknown",
            )
