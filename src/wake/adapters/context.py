"""SessionContext — opaque container of per-session data given to harnesses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wake.types import AgentConfig, SandboxHandle


@dataclass
class SessionContext:
    """Per-session context passed to ``HarnessAdapter.step``.

    Stable across step() calls within a session; harness should treat
    fields as read-only.
    """

    session_id: str
    agent_id: str
    agent_version: int
    agent_config: AgentConfig

    environment_id: str | None = None

    sandbox: SandboxHandle | None = None
    """Sandbox handle, if provisioned. None when no tool has requested it yet."""

    vault_id: str | None = None
    """Vault scope token, if the session was created with a vault."""

    metadata: dict[str, str] = field(default_factory=dict)
    """User-supplied session metadata."""
