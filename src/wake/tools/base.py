# ruff: noqa: A002, TC001
# `input` matches the Anthropic Tool API parameter name; we accept the shadow.
"""Tool ABI.

A Tool is the unit the harness invokes. Each tool exposes:
- A `descriptor` (name, description, JSON Schema, sandbox requirement)
- An async `execute(input, sandbox)` that returns a `ToolResult`

If `descriptor.requires_sandbox` is True, the tool registry will route execution
through the configured `SandboxAdapter`. Otherwise it runs in-process.

Phase 1 keeps the ABI deliberately small; Phase 2 extends it for the full
HarnessAdapter contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from wake.types import SandboxHandle, ToolDescriptor, ToolResult


class ToolExecutionError(Exception):
    """Raised when a tool fails with an unrecoverable error.

    Recoverable errors (the tool ran but produced an error result) should be
    represented as `ToolResult(is_error=True)`, not as exceptions.
    """

    def __init__(self, message: str, *, error_code: str = "unknown") -> None:
        super().__init__(message)
        self.error_code = error_code


class Tool(ABC):
    """Abstract base for a Wake tool."""

    @property
    @abstractmethod
    def descriptor(self) -> ToolDescriptor:
        """Describe the tool (name, JSON schema, sandbox requirement)."""

    @abstractmethod
    async def execute(
        self,
        input: dict[str, Any],
        sandbox: SandboxHandle | None,
    ) -> ToolResult:
        """Execute the tool. Returns a ToolResult (success or recoverable error)."""
