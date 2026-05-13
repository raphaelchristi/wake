"""Canonical types for Wake.

This module is the source of truth for shared types across the codebase.
All other modules import from here. Don't duplicate types elsewhere.

Schema matches `docs/SPEC-EVENT-SCHEMA.md` v0.1.0.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — runtime needed by pydantic validation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ============================================================================
# Event types
# ============================================================================

EventType = Literal[
    "user.message",
    "assistant.message",
    "assistant.thinking",
    "assistant.delta",
    "tool_use",
    "tool_result",
    "pause_turn",
    "status",
    "error",
    "artifact",
    "interrupt",
    "provision",
    "vault.access",
]


class Event(BaseModel):
    """An immutable event in the session log.

    Append-only. Once emitted, never modified.
    """

    model_config = ConfigDict(frozen=True)

    id: str  # ULID, 26 chars
    session_id: str
    seq: int  # monotonic per session, starts at 0
    type: EventType
    payload: dict[str, Any]
    parent_id: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime


# ============================================================================
# Content blocks (matching Anthropic Messages API format)
# ============================================================================


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ImageBlock(BaseModel):
    type: Literal["image"] = "image"
    source: dict[str, Any]


class ToolUseBlock(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any]


class ToolResultBlock(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: list[TextBlock]
    is_error: bool = False


ContentBlock = TextBlock | ImageBlock | ToolUseBlock | ToolResultBlock


# ============================================================================
# Model / Tool / MCP configs
# ============================================================================


class ModelConfig(BaseModel):
    id: str  # e.g., "claude-opus-4-7"
    speed: Literal["standard", "fast"] = "standard"
    provider: str = "anthropic"


class ToolConfig(BaseModel):
    """User-facing tool config in an Agent."""

    type: str  # "bash" | "file_read" | "file_write" | "agent_toolset_20260401" | ...
    config: dict[str, Any] = Field(default_factory=dict)


class McpServerConfig(BaseModel):
    name: str
    transport: Literal["stdio", "http", "sse"]
    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    vault_ref: str | None = None


# ============================================================================
# Agent / Environment / Session
# ============================================================================

SessionStatus = Literal["idle", "running", "rescheduling", "terminated"]


class AgentConfig(BaseModel):
    id: str
    name: str
    model: ModelConfig
    system: str | None = None
    tools: list[ToolConfig] = Field(default_factory=list)
    mcp_servers: list[McpServerConfig] = Field(default_factory=list)
    skills: list[dict[str, Any]] = Field(default_factory=list)
    description: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    version: int = 1
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


class EnvironmentConfig(BaseModel):
    id: str
    name: str
    config: dict[str, Any]  # type, packages, networking, sandbox backend, etc.
    created_at: datetime
    archived_at: datetime | None = None


class Session(BaseModel):
    id: str
    agent_id: str
    agent_version: int
    environment_id: str | None = None
    status: SessionStatus = "idle"
    container_id: str | None = None
    workspace_path: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


# ============================================================================
# Tool ABI (Phase 1 minimal; full HarnessAdapter ABI in Phase 2)
# ============================================================================


class ToolDescriptor(BaseModel):
    name: str
    description: str
    schema: dict[str, Any]  # JSON Schema for input
    requires_sandbox: bool = False


class ToolResult(BaseModel):
    content: list[TextBlock]
    is_error: bool = False
    error_code: str | None = None


# ============================================================================
# Sandbox
# ============================================================================


class SandboxHandle(BaseModel):
    backend: str  # "docker" | "sandbox-runtime" | ...
    container_id: str
    workspace_path: str
    created_at: datetime


__all__ = [
    "EventType",
    "Event",
    "TextBlock",
    "ImageBlock",
    "ToolUseBlock",
    "ToolResultBlock",
    "ContentBlock",
    "ModelConfig",
    "ToolConfig",
    "McpServerConfig",
    "SessionStatus",
    "AgentConfig",
    "EnvironmentConfig",
    "Session",
    "ToolDescriptor",
    "ToolResult",
    "SandboxHandle",
]
