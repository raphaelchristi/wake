"""Pydantic models mirroring the Wake server wire shapes.

The shapes here are intentionally a strict subset of ``wake.types`` re-derived
from the OpenAPI surface so the client package does not import the server.
Adding a field on the server is forward-compatible because all models opt into
``extra='allow'``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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

SessionStatus = Literal["idle", "running", "rescheduling", "terminated"]


class _Base(BaseModel):
    """Shared base — accepts extra fields so server additions don't break clients."""

    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# Content blocks (Anthropic-style)
# ---------------------------------------------------------------------------


class TextBlock(_Base):
    type: Literal["text"] = "text"
    text: str


class ImageBlock(_Base):
    type: Literal["image"] = "image"
    source: dict[str, Any]


class ToolUseBlock(_Base):
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any]


class ToolResultBlock(_Base):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: list[TextBlock]
    is_error: bool = False


ContentBlock = TextBlock | ImageBlock | ToolUseBlock | ToolResultBlock


# ---------------------------------------------------------------------------
# Model / Tool / MCP configs
# ---------------------------------------------------------------------------


class ModelConfig(_Base):
    id: str
    speed: Literal["standard", "fast"] = "standard"
    provider: str = "anthropic"


class ToolConfig(_Base):
    type: str
    config: dict[str, Any] = Field(default_factory=dict)


class McpServerConfig(_Base):
    name: str
    transport: Literal["stdio", "http", "sse"]
    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    vault_ref: str | None = None


# ---------------------------------------------------------------------------
# Core resources
# ---------------------------------------------------------------------------


class AgentConfig(_Base):
    id: str
    organization_id: str = "default"
    workspace_id: str = "default"
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


class Session(_Base):
    id: str
    organization_id: str = "default"
    workspace_id: str = "default"
    agent_id: str
    agent_version: int
    environment_id: str | None = None
    status: SessionStatus = "idle"
    container_id: str | None = None
    workspace_path: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class Event(_Base):
    id: str
    organization_id: str = "default"
    workspace_id: str = "default"
    session_id: str
    seq: int
    type: EventType
    payload: dict[str, Any]
    parent_id: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# List envelopes (match server responses)
# ---------------------------------------------------------------------------


class AgentList(_Base):
    data: list[AgentConfig]


class SessionList(_Base):
    data: list[Session]


class EventList(_Base):
    data: list[Event]


__all__ = [
    "EventType",
    "SessionStatus",
    "TextBlock",
    "ImageBlock",
    "ToolUseBlock",
    "ToolResultBlock",
    "ContentBlock",
    "ModelConfig",
    "ToolConfig",
    "McpServerConfig",
    "AgentConfig",
    "Session",
    "Event",
    "AgentList",
    "SessionList",
    "EventList",
]
