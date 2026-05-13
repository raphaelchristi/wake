"""Wake VaultAdapter backed by Infisical Agent Vault.

Provides:

* ``VaultAdapter`` — ABC every vault implementation conforms to (Phase 4
  extension of the credential interface).
* ``InfisicalVault`` — concrete adapter that talks to a running Infisical
  Agent Vault (typically a sidecar) and stores credentials there.
* ``OAuthFlow`` — generic OAuth2 helper plus shipped providers for
  GitHub, Slack and Notion.
* CLI app exposed as ``wake vault`` (via the ``wake.cli`` entry-point).

Credential values are never logged or surfaced in events; only opaque
placeholders such as ``{{vault:github_token}}`` flow through the
substrate, and the HTTPS proxy substitutes the real value at egress
time.
"""

from wake_vault_infisical.base import (
    CredentialMetadata,
    VaultAdapter,
    VaultError,
    VaultNotFoundError,
)
from wake_vault_infisical.oauth import (
    OAuthError,
    OAuthFlow,
    OAuthProvider,
    get_provider,
)
from wake_vault_infisical.proxy import ProxyConfig, VaultProxy
from wake_vault_infisical.vault import InfisicalVault, create

__all__ = [
    "VaultAdapter",
    "VaultError",
    "VaultNotFoundError",
    "CredentialMetadata",
    "InfisicalVault",
    "OAuthFlow",
    "OAuthError",
    "OAuthProvider",
    "get_provider",
    "VaultProxy",
    "ProxyConfig",
    "create",
]

__version__ = "0.1.0"
