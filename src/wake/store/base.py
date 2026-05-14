"""Abstract storage interfaces for Wake.

These ABCs define the contract every storage backend must implement.
The default backend is SQLite (`wake.store.sqlite`); future backends
(Postgres, Kafka, S3+index) plug in by implementing the same interfaces.

Design notes
------------
- All I/O is async. Implementations must be safe to use concurrently.
- The four stores (Event/Agent/Environment/Session) are separate ABCs so
  backends can mix-and-match (e.g. events in Kafka, metadata in Postgres).
- `EventStore.append` assigns the `seq` atomically — callers never set it.
- `EventStore.subscribe` is a long-lived async iterator. Polling-based
  implementations are acceptable for the Phase-1 SQLite backend.
"""

# `id` shadows a builtin but the PHASE-1-CONTRACT mandates this parameter
# name on every store method. The types in `wake.types` use the same
# field name on AgentConfig/EnvironmentConfig/Session.
# ruff: noqa: A002, TC001, TC003

from __future__ import annotations

import builtins
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from wake.rbac import Role, User
from wake.tenancy import DEFAULT_ORGANIZATION_ID, DEFAULT_WORKSPACE_ID
from wake.types import (
    AgentConfig,
    EnvironmentConfig,
    Event,
    EventType,
    ModelConfig,
    Session,
    SessionStatus,
)


class StoreError(Exception):
    """Base class for storage-layer errors."""


# ---------------------------------------------------------------------------
# EventStore
# ---------------------------------------------------------------------------


class EventStore(ABC):
    """Append-only event log.

    Events are immutable. The store assigns a monotonic ``seq`` per session
    on append and a globally unique ULID id.
    """

    @abstractmethod
    async def append(
        self,
        session_id: str,
        event_type: EventType,
        payload: dict[str, Any],
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> Event:
        """Append an event to ``session_id``'s log.

        Returns the persisted event (with assigned ``id``, ``seq``,
        ``created_at``). Must be atomic with respect to ``seq`` allocation
        on the same session.
        """

    @abstractmethod
    async def get(
        self,
        session_id: str,
        since: int = 0,
        *,
        workspace_id: str | None = None,
    ) -> list[Event]:
        """Return events for ``session_id`` with ``seq >= since``, ordered."""

    @abstractmethod
    async def get_one(self, event_id: str, *, workspace_id: str | None = None) -> Event | None:
        """Return a single event by ULID, or ``None`` if not found."""

    @abstractmethod
    async def subscribe(
        self,
        session_id: str,
        since: int = 0,
        *,
        workspace_id: str | None = None,
    ) -> AsyncIterator[Event]:
        """Yield events for ``session_id`` as they are appended.

        Yields any backlog with ``seq >= since`` first, then live events.
        Implementations may use polling; consumers must call ``aclose()``
        to release resources.
        """
        # Note: declared as a coroutine that returns an iterator in
        # implementations; ABC just specifies the signature.

    @abstractmethod
    async def count(self, session_id: str, *, workspace_id: str | None = None) -> int:
        """Return total number of events on the session."""


# ---------------------------------------------------------------------------
# AgentStore
# ---------------------------------------------------------------------------


class AgentStore(ABC):
    """Catalog of agents with versioning.

    Versioning rules (matching Managed Agents):
    - ``create`` assigns ``version = 1`` and a new ULID-based id.
    - ``update`` compares incoming fields against the current version's
      content hash. If unchanged, returns the current version unchanged
      (no-op). Otherwise persists a new version row.
    - ``archive`` sets ``archived_at`` on the agent (all versions).
    """

    @abstractmethod
    async def create(
        self,
        name: str,
        model: ModelConfig,
        *,
        system: str | None = None,
        tools: list[Any] | None = None,
        mcp_servers: list[Any] | None = None,
        skills: list[dict[str, Any]] | None = None,
        description: str | None = None,
        metadata: dict[str, str] | None = None,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> AgentConfig:
        """Create a new agent (version 1) and return it."""

    @abstractmethod
    async def get(
        self,
        id: str,
        version: int | None = None,
        *,
        workspace_id: str | None = None,
    ) -> AgentConfig | None:
        """Return an agent by id. Latest version when ``version`` is None."""

    @abstractmethod
    async def update(
        self, id: str, *, workspace_id: str | None = None, **changes: Any
    ) -> AgentConfig:
        """Update an agent. Returns existing or newly-versioned config.

        If the change set is a no-op (content hash unchanged), the current
        version is returned and no new row is written.
        """

    @abstractmethod
    async def list(  # noqa: A003 — public API name fixed by contract
        self, *, include_archived: bool = False, workspace_id: str | None = None
    ) -> builtins.list[AgentConfig]:
        """List agents (latest versions only)."""

    @abstractmethod
    async def list_versions(
        self, id: str, *, workspace_id: str | None = None
    ) -> builtins.list[AgentConfig]:
        """List every version of a given agent, oldest first."""

    @abstractmethod
    async def archive(self, id: str, *, workspace_id: str | None = None) -> AgentConfig:
        """Set ``archived_at`` on the agent and return the latest version."""


# ---------------------------------------------------------------------------
# EnvironmentStore
# ---------------------------------------------------------------------------


class EnvironmentStore(ABC):
    """Catalog of environments. No versioning (deliberate, matching
    Managed Agents)."""

    @abstractmethod
    async def create(
        self,
        name: str,
        config: dict[str, Any],
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> EnvironmentConfig: ...

    @abstractmethod
    async def get(
        self, id: str, *, workspace_id: str | None = None
    ) -> EnvironmentConfig | None: ...

    @abstractmethod
    async def list(
        self, *, include_archived: bool = False, workspace_id: str | None = None
    ) -> builtins.list[EnvironmentConfig]: ...

    @abstractmethod
    async def archive(self, id: str, *, workspace_id: str | None = None) -> EnvironmentConfig: ...

    @abstractmethod
    async def delete(self, id: str, *, workspace_id: str | None = None) -> None: ...


# ---------------------------------------------------------------------------
# SessionStore
# ---------------------------------------------------------------------------


class SessionStore(ABC):
    """Catalog of sessions (lifecycle metadata, not events)."""

    @abstractmethod
    async def create(
        self,
        agent_id: str,
        agent_version: int,
        environment_id: str | None = None,
        metadata: dict[str, str] | None = None,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> Session: ...

    @abstractmethod
    async def get(self, id: str, *, workspace_id: str | None = None) -> Session | None: ...

    @abstractmethod
    async def list(
        self,
        *,
        status: SessionStatus | None = None,
        workspace_id: str | None = None,
    ) -> builtins.list[Session]: ...

    @abstractmethod
    async def update_status(
        self, id: str, status: SessionStatus, *, workspace_id: str | None = None
    ) -> Session: ...

    @abstractmethod
    async def set_container(
        self,
        id: str,
        container_id: str | None,
        workspace_path: str | None = None,
        workspace_id: str | None = None,
    ) -> Session: ...

    @abstractmethod
    async def delete(self, id: str, *, workspace_id: str | None = None) -> None: ...


# ---------------------------------------------------------------------------
# UserStore
# ---------------------------------------------------------------------------


class UserStore(ABC):
    """Catalog of users + workspace-scoped role assignments.

    Users live at the organisation/workspace level: a ``User`` row is
    created once per ``(workspace_id, user_id)`` pair. Roles are
    stored separately in a many-to-many table so a single user can
    hold multiple roles and roles can be assigned/revoked without
    touching the user row.

    Identity semantics:

    * ``id`` is the user identifier the gateway injects via
      ``X-Wake-User-Id``. It is opaque to Wake — typically a stable
      identifier from the upstream IdP (Auth0 ``sub``, GitHub login,
      Cognito sub, etc.).
    * ``workspace_id`` is the tenancy boundary. The same ``user_id``
      can exist in two workspaces and is treated as two independent
      principals.

    All methods are async and workspace-scoped. ``workspace_id`` is
    required on writes; on reads it is optional only for the cross-
    workspace ``get_global`` helper (used by audit tooling).
    """

    @abstractmethod
    async def create(
        self,
        user_id: str,
        *,
        display_name: str | None = None,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> User:
        """Persist a user in the given workspace and return it.

        Duplicates raise :class:`StoreError`. The reserved id
        ``"system"`` is rejected (it is the sentinel for
        RBAC-disabled mode).
        """

    @abstractmethod
    async def get(
        self,
        user_id: str,
        *,
        workspace_id: str,
    ) -> User | None:
        """Return the user (with roles loaded) or ``None``."""

    @abstractmethod
    async def list(  # noqa: A003 — public API name fixed by contract
        self,
        *,
        workspace_id: str,
    ) -> builtins.list[User]:
        """List users in the workspace, oldest first."""

    @abstractmethod
    async def update(
        self,
        user_id: str,
        *,
        workspace_id: str,
        display_name: str | None = None,
    ) -> User:
        """Update mutable user fields.

        Only ``display_name`` is currently mutable; identity-bearing
        fields like ``id`` are immutable by contract.
        """

    @abstractmethod
    async def delete(
        self,
        user_id: str,
        *,
        workspace_id: str,
    ) -> None:
        """Remove the user and cascade-delete its role assignments."""

    @abstractmethod
    async def assign_role(
        self,
        user_id: str,
        role: Role,
        *,
        workspace_id: str,
    ) -> None:
        """Bind ``role`` to ``user_id`` in the workspace.

        Idempotent: assigning the same role twice is a no-op.
        Raises :class:`StoreError` if the user does not exist in the
        workspace (no orphan role rows).
        """

    @abstractmethod
    async def revoke_role(
        self,
        user_id: str,
        role: Role,
        *,
        workspace_id: str,
    ) -> None:
        """Remove ``role`` from ``user_id`` in the workspace.

        Idempotent: revoking a role the user does not hold is a
        no-op. Removing the last admin in a workspace is allowed —
        the API layer is responsible for guarding against
        operator-shoot-foot scenarios.
        """

    @abstractmethod
    async def roles_for(
        self,
        user_id: str,
        *,
        workspace_id: str,
    ) -> builtins.list[Role]:
        """Return roles bound to the user in the workspace, sorted
        in :class:`Role` declaration order."""
