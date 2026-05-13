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
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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
    """

    model_config = ConfigDict(frozen=True)

    vault_id: str
    name: str
    provider: ProviderName | str
    scopes: list[str] = Field(default_factory=list)
    created_at: datetime
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    ) -> CredentialMetadata:
        """Store a secret and return its public metadata.

        ``value`` is the bearer token / API key. After this call the
        secret lives **only** in the vault — the caller should drop its
        in-memory copy.
        """

    @abstractmethod
    async def get_proxy_token(self, vault_id: str, session_id: str) -> str:
        """Return a short-lived opaque token bound to ``session_id``.

        The token is what an agent sees if it inspects placeholder
        substitution output. The vault's HTTPS MITM proxy will swap it
        for the real credential when it observes an outbound request
        whose ``Authorization`` header contains this token.
        """

    @abstractmethod
    async def list(self) -> list[CredentialMetadata]:  # noqa: A003 — matches CLI semantics
        """Return metadata for every credential the vault knows."""

    @abstractmethod
    async def get_metadata(self, vault_id: str) -> CredentialMetadata:
        """Return metadata for a single vault entry."""

    @abstractmethod
    async def revoke(self, vault_id: str) -> None:
        """Permanently delete a credential.

        Implementations should be idempotent: revoking a vault_id that
        was already revoked must not raise.
        """


__all__ = [
    "VaultAdapter",
    "VaultError",
    "VaultNotFoundError",
    "CredentialMetadata",
    "ProviderName",
]
