# ruff: noqa: A002, TC001
"""Sandbox adapter ABC.

A SandboxAdapter provisions an isolated execution environment, exposes a
unified `execute(tool, input)` interface, and destroys it when the session ends.

Phase 1 ships a Docker backend. Phase 4 adds sandbox-runtime, gVisor,
Firecracker.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from wake.types import EnvironmentConfig, SandboxHandle, ToolResult


class SandboxProvisionError(Exception):
    """Raised when sandbox provisioning fails."""


class SandboxAdapter(ABC):
    """Common interface every sandbox backend implements."""

    @abstractmethod
    async def provision(self, env: EnvironmentConfig) -> SandboxHandle:
        """Provision a fresh sandbox from the given Environment config."""

    @abstractmethod
    async def execute(
        self,
        handle: SandboxHandle,
        tool_name: str,
        input: dict[str, Any],
    ) -> ToolResult:
        """Execute a tool inside the sandbox."""

    @abstractmethod
    async def destroy(self, handle: SandboxHandle) -> None:
        """Tear down the sandbox (best-effort)."""
