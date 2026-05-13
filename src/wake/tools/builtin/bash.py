# ruff: noqa: A002
"""Bash tool: execute a shell command.

Always sandbox-routed in Phase 1 (no host-side fallback). The SandboxAdapter
is responsible for running the command inside the configured container.
"""

from __future__ import annotations

from typing import Any

from wake.tools.base import Tool
from wake.types import SandboxHandle, TextBlock, ToolDescriptor, ToolResult


class BashTool(Tool):
    """`bash`: run a shell command inside the sandbox."""

    @property
    def descriptor(self) -> ToolDescriptor:
        return ToolDescriptor(
            name="bash",
            description="Execute a bash command inside the session sandbox.",
            schema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to run.",
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 600,
                        "default": 60,
                        "description": "Max seconds to wait for command.",
                    },
                },
                "required": ["command"],
            },
            requires_sandbox=True,
        )

    async def execute(
        self,
        input: dict[str, Any],
        sandbox: SandboxHandle | None,
    ) -> ToolResult:
        # If we end up here, the registry routed bash to host mode (no sandbox).
        # Phase 1 disallows running bash on the host for safety.
        if sandbox is None:
            return ToolResult(
                content=[
                    TextBlock(text="bash requires a sandbox; none was provisioned.")
                ],
                is_error=True,
                error_code="unavailable",
            )
        # Sandbox path is handled inside ToolRegistry.execute via SandboxAdapter.
        # Reaching here means the registry has no sandbox adapter wired up.
        return ToolResult(
            content=[TextBlock(text="bash sandbox adapter is not configured.")],
            is_error=True,
            error_code="unavailable",
        )
