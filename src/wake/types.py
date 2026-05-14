"""Canonical types for Wake.

This module is the source of truth for shared types across the codebase.
All other modules import from here. Don't duplicate types elsewhere.

Schema matches `docs/SPEC-EVENT-SCHEMA.md` v0.1.0.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — runtime needed by pydantic validation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from wake.rbac import Role, User
from wake.tenancy import DEFAULT_ORGANIZATION_ID, DEFAULT_WORKSPACE_ID

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
    organization_id: str = DEFAULT_ORGANIZATION_ID
    workspace_id: str = DEFAULT_WORKSPACE_ID
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
    organization_id: str = DEFAULT_ORGANIZATION_ID
    workspace_id: str = DEFAULT_WORKSPACE_ID
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
    organization_id: str = DEFAULT_ORGANIZATION_ID
    workspace_id: str = DEFAULT_WORKSPACE_ID
    name: str
    config: dict[str, Any]  # type, packages, networking, sandbox backend, etc.
    created_at: datetime
    archived_at: datetime | None = None


class Session(BaseModel):
    id: str
    organization_id: str = DEFAULT_ORGANIZATION_ID
    workspace_id: str = DEFAULT_WORKSPACE_ID
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


# ============================================================================
# RBAC (re-exports — canonical definitions live in ``wake.rbac``)
# ============================================================================
#
# We surface ``User`` and ``Role`` from ``wake.types`` so callers can
# import the entire surface from one module. The real implementation
# is in :mod:`wake.rbac` so it can be reused without dragging pydantic
# into low-level code paths.


class UserRoleBinding(BaseModel):
    """Wire-shape for a ``(user_id, workspace_id, role)`` triple.

    Stored in the ``user_roles`` table. Pydantic shape used by the
    API surface so OpenAPI can describe the role-assignment payloads.
    """

    user_id: str
    organization_id: str = DEFAULT_ORGANIZATION_ID
    workspace_id: str = DEFAULT_WORKSPACE_ID
    role: Role
    created_at: datetime


# ============================================================================
# Edit-and-replay (Phase 8 — Tier 2 gap #10)
# ============================================================================
#
# A replay materialises a NEW session from an EXISTING session's event
# log, optionally substituting ``system_prompt`` / ``tools`` / ``max_steps``
# overrides. The replay is *deterministic* with respect to the source
# session: same input log + same overrides → same output log, modulo the
# semantic effect of the overrides themselves.
#
# The shape is intentionally narrow — the replay endpoint is NOT a
# generic "run agent" API. It is the engineering loop primitive:
# "I changed this prompt; show me what the agent would have done."


class ReplayRequest(BaseModel):
    """Optional overrides for ``POST /v1/sessions/{id}/replay``.

    All fields default to ``None`` meaning "inherit from source". When
    ``system_prompt`` is provided it REPLACES the agent's ``system``
    string for the replay. When ``tools`` is provided it REPLACES the
    visible tool list — items NOT in the override are not callable in
    the replay. ``max_steps`` caps the replay loop to bound runaway
    edits (None = inherit dispatcher default).
    """

    system_prompt: str | None = None
    tools: list[ToolConfig] | None = None
    max_steps: int | None = Field(
        default=None,
        ge=1,
        le=1000,
        description=(
            "Override max replay steps. Caps runaway edits "
            "(canonical default: agent.metadata.max_steps then 32)."
        ),
    )
    # Sticky-seed knob: when set, the engine uses this seed for every
    # non-deterministic adapter call (random tool ordering, sampling).
    # Defaults to the source session's seed when None — that's how we
    # achieve "same input → same output" with overrides off.
    seed: int | None = Field(
        default=None,
        ge=0,
        le=2**63 - 1,
        description="PRNG seed. None inherits from source session metadata.",
    )


class ReplayResult(BaseModel):
    """Response envelope for ``POST /v1/sessions/{id}/replay``.

    Returns the brand-new session id so the dashboard can ``GET
    /v1/sessions/{new_id}/events`` and render the diff. Carries a
    ``deterministic`` flag for the canary path — False when overrides
    forced a non-identity replay (caller should not expect bit-for-bit
    equality with the source).
    """

    source_session_id: str
    new_session_id: str
    seed: int
    deterministic: bool
    overrides_applied: list[str]
    # Event counts so the dashboard can show "replayed N events" without
    # an extra round-trip. Filled by the engine.
    source_event_count: int = 0
    replayed_event_count: int = 0


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
    "Role",
    "User",
    "UserRoleBinding",
    "ReplayRequest",
    "ReplayResult",
]
