# ruff: noqa: A002
"""File operations: read, write, edit.

Like bash, these always require a sandbox in Phase 1 — they operate on the
session's workspace path inside the container.
"""

from __future__ import annotations

from typing import Any

from wake.tools.base import Tool
from wake.types import SandboxHandle, TextBlock, ToolDescriptor, ToolResult


def _unavailable(reason: str) -> ToolResult:
    return ToolResult(
        content=[TextBlock(text=reason)], is_error=True, error_code="unavailable"
    )


class FileReadTool(Tool):
    """`file_read`: read a file from the sandbox workspace."""

    @property
    def descriptor(self) -> ToolDescriptor:
        return ToolDescriptor(
            name="file_read",
            description="Read a file from the session workspace.",
            schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative path to read.",
                    },
                    "start_line": {"type": "integer", "minimum": 1},
                    "end_line": {"type": "integer", "minimum": 1},
                },
                "required": ["path"],
            },
            requires_sandbox=True,
        )

    async def execute(
        self,
        input: dict[str, Any],
        sandbox: SandboxHandle | None,
    ) -> ToolResult:
        if sandbox is None:
            return _unavailable("file_read requires a sandbox; none was provisioned.")
        return _unavailable("file_read sandbox adapter is not configured.")


class FileWriteTool(Tool):
    """`file_write`: write a file to the sandbox workspace, overwriting if present."""

    @property
    def descriptor(self) -> ToolDescriptor:
        return ToolDescriptor(
            name="file_write",
            description="Write (create or overwrite) a file in the session workspace.",
            schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative path to write.",
                    },
                    "content": {
                        "type": "string",
                        "description": "File contents.",
                    },
                },
                "required": ["path", "content"],
            },
            requires_sandbox=True,
        )

    async def execute(
        self,
        input: dict[str, Any],
        sandbox: SandboxHandle | None,
    ) -> ToolResult:
        if sandbox is None:
            return _unavailable("file_write requires a sandbox; none was provisioned.")
        return _unavailable("file_write sandbox adapter is not configured.")


class FileEditTool(Tool):
    """`file_edit`: replace an exact string in a file inside the sandbox workspace."""

    @property
    def descriptor(self) -> ToolDescriptor:
        return ToolDescriptor(
            name="file_edit",
            description="Replace an exact string occurrence in a workspace file.",
            schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative path to edit.",
                    },
                    "old_string": {
                        "type": "string",
                        "description": "Exact string to find (must appear once).",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "Replacement string.",
                    },
                    "replace_all": {
                        "type": "boolean",
                        "default": False,
                        "description": "If true, replace all occurrences.",
                    },
                },
                "required": ["path", "old_string", "new_string"],
            },
            requires_sandbox=True,
        )

    async def execute(
        self,
        input: dict[str, Any],
        sandbox: SandboxHandle | None,
    ) -> ToolResult:
        if sandbox is None:
            return _unavailable("file_edit requires a sandbox; none was provisioned.")
        return _unavailable("file_edit sandbox adapter is not configured.")
