"""VaultAdapter ABC — the Phase 4 credential storage interface.

A vault stores opaque secrets (API tokens, OAuth refresh tokens, …) and
hands out short-lived **proxy tokens** that an egress proxy can swap for
the real value at request time. Agent code only ever sees the proxy
token, never the secret itself, so prompt-injection attacks that try to
exfiltrate credentials via the agent's tool surface get a useless
placeholder.

Every method is async because real implementations talk to an out-of-
process vault (typically Infisical Agent Vault running as a sidecar)
over HTTP.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime  # noqa: TC003 — runtime needed by pydantic validation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

#: Default tenant scope. Matches ``wake.tenancy.DEFAULT_*`` so deployments
#: that have not opted into multi-tenancy keep working.
DEFAULT_ORGANIZATION_ID = "default"
DEFAULT_WORKSPACE_ID = "default"

ProviderName = Literal["github", "slack", "notion", "custom"]
"""Built-in OAuth providers shipped with this package.

``custom`` is the escape hatch: callers supply ``client_id``,
``client_secret`` and ``authorize_url`` / ``token_url`` directly.
"""


class VaultError(Exception):
    """Base error for vault operations."""


class VaultNotFoundError(VaultError):
    """Raised when a vault entry is requested that does not exist."""


class CredentialMetadata(BaseModel):
    """Public, non-sensitive metadata about a stored credential.

    Returned by ``list()``. Crucially this object **never** carries the
    secret value — callers receive a proxy token from
    ``get_proxy_token()`` instead.

    Carries ``organization_id`` / ``workspace_id`` so vault entries are
    workspace-scoped — Phase 6.1 fix for Codex finding #1 (cross-tenant
    credential inventory). Defaults to the ``default/default`` scope so
    single-tenant deployments work without changes.
    """

    model_config = ConfigDict(frozen=True)

    vault_id: str
    name: str
    provider: ProviderName | str
    scopes: list[str] = Field(default_factory=list)
    created_at: datetime
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    organization_id: str = DEFAULT_ORGANIZATION_ID
    workspace_id: str = DEFAULT_WORKSPACE_ID


class VaultAdapter(ABC):
    """Common interface every Phase 4 vault implementation provides.

    Lifecycle (typical):

    1. ``add(name, provider, value)`` — caller stores a credential
       (usually right after completing an OAuth flow).
    2. ``get_proxy_token(vault_id, session_id)`` — runtime asks for a
       per-session opaque token, which the egress proxy swaps for the
       real value when it sees ``Authorization: Bearer {proxy_token}``
       on an outbound request.
    3. ``list()`` — UI / CLI surfaces a directory of available creds.
    4. ``revoke(vault_id)`` — destroys a credential.
    """

    @abstractmethod
    async def add(
        self,
        name: str,
        provider: ProviderName | str,
        value: str,
        *,
        scopes: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> CredentialMetadata:
        """Store a secret scoped to a workspace and return its metadata.

        ``value`` is the bearer token / API key. After this call the
        secret lives **only** in the vault — the caller should drop its
        in-memory copy. ``organization_id`` + ``workspace_id`` define the
        tenant boundary: every read/rotate/revoke path must filter by
        the same scope (Phase 6.1 finding #1).
        """

    @abstractmethod
    async def get_proxy_token(
        self,
        vault_id: str,
        session_id: str,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> str:
        """Return a short-lived opaque token bound to ``session_id``.

        Adapters MUST raise :class:`VaultNotFoundError` when ``vault_id``
        does not belong to the requested ``organization_id``/
        ``workspace_id``. The token is what an agent sees if it inspects
        placeholder substitution output. The vault's HTTPS MITM proxy
        will swap it for the real credential when it observes an
        outbound request whose ``Authorization`` header contains this
        token.
        """

    @abstractmethod
    async def list(  # noqa: A003 — matches CLI semantics
        self,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> list[CredentialMetadata]:
        """Return metadata for every credential in the given tenant scope."""

    @abstractmethod
    async def get_metadata(
        self,
        vault_id: str,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> CredentialMetadata:
        """Return metadata for a single vault entry, scoped to tenant.

        Implementations MUST raise :class:`VaultNotFoundError` if the
        ``vault_id`` exists but belongs to a different workspace — the
        404 is mandatory to keep workspace existence opaque across
        tenants (PHASE-6-CONTRACT.md).
        """

    @abstractmethod
    async def revoke(
        self,
        vault_id: str,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> None:
        """Permanently delete a credential within a workspace.

        Implementations should be idempotent: revoking a vault_id that
        was already revoked must not raise. Revoking a vault_id that
        belongs to a different workspace MUST behave as a missing entry
        (silent no-op) to keep tenant existence opaque.
        """


__all__ = [
    "DEFAULT_ORGANIZATION_ID",
    "DEFAULT_WORKSPACE_ID",
    "VaultAdapter",
    "VaultError",
    "VaultNotFoundError",
    "CredentialMetadata",
    "ProviderName",
]
