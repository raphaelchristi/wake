"""ToolRegistry interface as seen by HarnessAdapter implementations.

Adapters call ``tools.execute(name, input, tool_use_id=...)`` to invoke
tools. They never call tool implementations directly — this enforces
permission policy, sandbox routing, vault credential injection, and
audit logging from a single chokepoint.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from wake.types import ToolDescriptor, ToolResult


class ToolRegistry(ABC):
    """Adapter-facing view of the tool registry.

    The runtime supplies an implementation (filtered by permission
    policy) per step() call.
    """

    @abstractmethod
    def list(self) -> list[ToolDescriptor]:
        """Return the tool descriptors available to this session."""
        ...

    @abstractmethod
    def get(self, name: str) -> ToolDescriptor:
        """Return the descriptor for a specific tool, or raise KeyError."""
        ...

    @abstractmethod
    async def execute(
        self,
        name: str,
        input: dict[str, Any],
        *,
        tool_use_id: str,
    ) -> ToolResult:
        """Execute a tool by name.

        ``tool_use_id`` is required: it ties the call to the originating
        tool_use event and enables idempotent retries.
        """
        ...
