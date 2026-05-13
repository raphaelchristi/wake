"""Concrete ``ToolRegistry`` that wraps Wake's internal tool registry.

The adapter-facing registry (``wake.adapters.ToolRegistry``) is a small,
permission-scoped view over the actual ``wake.tools.registry.ToolRegistry``.
This class bridges them: it forwards ``list()``/``get()``/``execute()``
through to the wrapped registry, attaching the per-session sandbox
handle (if any) and translating unknown-tool requests into a ``not_found``
``ToolResult`` (rather than ``None``).
"""

# ruff: noqa: A002, TC001, TC003

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from wake.adapters.tool_registry import ToolRegistry as AdapterToolRegistry
from wake.types import TextBlock, ToolResult

if TYPE_CHECKING:
    from wake.tools.registry import ToolRegistry as WakeToolsRegistry
    from wake.types import SandboxHandle, ToolDescriptor


class WakeToolRegistry(AdapterToolRegistry):
    """Adapter-facing ToolRegistry over a session's tool set."""

    def __init__(
        self,
        registry: WakeToolsRegistry,
        sandbox_handle: SandboxHandle | None = None,
    ) -> None:
        self._registry = registry
        self._sandbox_handle = sandbox_handle

    def list(self) -> list[ToolDescriptor]:
        return self._registry.descriptors()

    def get(self, name: str) -> ToolDescriptor:
        tool = self._registry.get(name)
        if tool is None:
            raise KeyError(name)
        return tool.descriptor

    async def execute(
        self,
        name: str,
        input: dict[str, Any],
        *,
        tool_use_id: str,  # noqa: ARG002 — kept for ABC contract; wake registry doesn't need it (yet)
    ) -> ToolResult:
        tool = self._registry.get(name)
        if tool is None:
            return ToolResult(
                content=[TextBlock(text=f"unknown tool: {name}")],
                is_error=True,
                error_code="not_found",
            )
        return await self._registry.execute(
            name, input, sandbox_handle=self._sandbox_handle
        )
