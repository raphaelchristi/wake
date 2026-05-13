"""InfisicalVault — concrete ``VaultAdapter`` backed by Infisical Agent Vault.

Infisical Agent Vault runs as a local sidecar (typically Docker
container). It exposes a small REST API for credential CRUD plus an
HTTPS MITM proxy that performs placeholder substitution on outbound
agent traffic.

This adapter is a thin HTTP client. It deliberately does **not** keep
secret values in process memory after ``add()`` returns — once the
secret is in the vault, the adapter holds only metadata.
"""

from __future__ import annotations

import builtins
import os
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import structlog

from wake_vault_infisical.base import (
    CredentialMetadata,
    ProviderName,
    VaultAdapter,
    VaultError,
    VaultNotFoundError,
)

logger = structlog.get_logger(__name__)


DEFAULT_VAULT_URL = "http://localhost:8200"
"""Where the Infisical Agent Vault sidecar listens by default."""


class _InMemoryBackend:
    """Fallback backend used when Infisical SDK is unavailable.

    Stores secrets in process memory keyed by vault_id. This is **only**
    intended for testing and the dev-grade docker-compose path documented
    in ``docs/DEPLOY-DOCKER-COMPOSE.md``. Production deployments must
    use the real Infisical Agent Vault.

    The fallback exists so that ``examples/08-vault-credentials/run.py``
    is runnable on a clean checkout without bringing up Infisical first.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        self._proxy_tokens: dict[str, str] = {}  # proxy_token -> vault_id

    def put(self, vault_id: str, name: str, provider: str, value: str,
            scopes: list[str], metadata: dict[str, Any]) -> None:
        self._store[vault_id] = {
            "name": name,
            "provider": provider,
            "value": value,
            "scopes": scopes,
            "metadata": metadata,
            "created_at": datetime.now(UTC),
        }

    def get_value(self, vault_id: str) -> str:
        if vault_id not in self._store:
            raise VaultNotFoundError(f"vault entry {vault_id!r} not found")
        return str(self._store[vault_id]["value"])

    def get_meta(self, vault_id: str) -> dict[str, Any]:
        if vault_id not in self._store:
            raise VaultNotFoundError(f"vault entry {vault_id!r} not found")
        return self._store[vault_id]

    def list_all(self) -> list[tuple[str, dict[str, Any]]]:
        return [(vid, dict(meta)) for vid, meta in self._store.items()]

    def revoke(self, vault_id: str) -> None:
        # Idempotent: silently drop unknown ids.
        self._store.pop(vault_id, None)
        # Also revoke any outstanding proxy tokens for this vault_id.
        self._proxy_tokens = {
            tok: vid for tok, vid in self._proxy_tokens.items() if vid != vault_id
        }

    def issue_proxy_token(self, vault_id: str) -> str:
        if vault_id not in self._store:
            raise VaultNotFoundError(f"vault entry {vault_id!r} not found")
        token = f"wkv_{uuid4().hex}"
        self._proxy_tokens[token] = vault_id
        return token

    def resolve_proxy_token(self, proxy_token: str) -> str:
        """Used by the proxy implementation to swap token → real value."""
        vault_id = self._proxy_tokens.get(proxy_token)
        if vault_id is None or vault_id not in self._store:
            raise VaultNotFoundError("proxy token unknown or revoked")
        return str(self._store[vault_id]["value"])


class InfisicalVault(VaultAdapter):
    """VaultAdapter that talks to an Infisical Agent Vault sidecar.

    Construction modes:

    * ``InfisicalVault(infisical_url=..., token=...)`` — talk to a
      running Infisical instance via HTTP.
    * ``InfisicalVault(in_memory=True)`` — dev/test fallback that keeps
      secrets in process memory (NEVER use in production).

    The API surface matches ``VaultAdapter`` exactly.
    """

    def __init__(
        self,
        infisical_url: str | None = None,
        token: str | None = None,
        *,
        in_memory: bool = False,
        http_client: httpx.AsyncClient | None = None,
        project_id: str | None = None,
        environment: str = "prod",
    ) -> None:
        self._url = (infisical_url or os.getenv("INFISICAL_URL") or DEFAULT_VAULT_URL).rstrip("/")
        self._token = token or os.getenv("INFISICAL_TOKEN")
        self._project_id = project_id or os.getenv("INFISICAL_PROJECT_ID", "wake")
        self._environment = environment

        # Decide backend mode. We prefer the real Infisical client if a
        # token is configured AND the SDK imports cleanly; otherwise we
        # fall back to in-memory storage.
        self._mode: str
        self._memory: _InMemoryBackend | None = None
        self._http: httpx.AsyncClient | None = None

        if in_memory or not self._token:
            self._mode = "memory"
            self._memory = _InMemoryBackend()
            logger.info(
                "infisical_vault_init",
                mode="memory",
                reason="in_memory=True" if in_memory else "no token configured",
            )
        else:
            self._mode = "http"
            self._http = http_client or httpx.AsyncClient(
                base_url=self._url,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=10.0,
            )
            logger.info("infisical_vault_init", mode="http", url=self._url)

    # ------------------------------------------------------------------ ABC

    async def add(
        self,
        name: str,
        provider: ProviderName | str,
        value: str,
        *,
        scopes: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CredentialMetadata:
        vault_id = f"vault_{uuid4().hex[:16]}"
        scopes = scopes or []
        metadata = metadata or {}

        # IMPORTANT: never log ``value`` — only its presence.
        logger.info(
            "vault_add",
            vault_id=vault_id,
            name=name,
            provider=provider,
            has_value=bool(value),
            scopes=scopes,
        )

        if self._mode == "memory":
            assert self._memory is not None
            self._memory.put(vault_id, name, str(provider), value, scopes, metadata)
        else:
            assert self._http is not None
            try:
                resp = await self._http.post(
                    f"/api/v3/secrets/{self._project_id}/{name}",
                    json={
                        "environment": self._environment,
                        "secretValue": value,
                        "secretMetadata": {
                            "vault_id": vault_id,
                            "provider": str(provider),
                            "scopes": scopes,
                            **metadata,
                        },
                    },
                )
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise VaultError(f"infisical add failed: {exc}") from exc

        return CredentialMetadata(
            vault_id=vault_id,
            name=name,
            provider=provider,
            scopes=scopes,
            created_at=datetime.now(UTC),
            metadata=metadata,
        )

    async def get_proxy_token(self, vault_id: str, session_id: str) -> str:
        # Proxy tokens are opaque — agent code that "leaks" one in a
        # tool_result event leaks nothing useful. The HTTPS proxy swaps
        # the token for the real credential at egress time.
        logger.info("vault_proxy_token_issued", vault_id=vault_id, session_id=session_id)

        if self._mode == "memory":
            assert self._memory is not None
            return self._memory.issue_proxy_token(vault_id)

        assert self._http is not None
        try:
            resp = await self._http.post(
                "/api/v3/proxy-tokens",
                json={"vault_id": vault_id, "session_id": session_id},
            )
            resp.raise_for_status()
            data = resp.json()
            token: str = data.get("proxy_token", "")
            if not token:
                raise VaultError("infisical returned an empty proxy_token")
            return token
        except httpx.HTTPError as exc:
            raise VaultError(f"infisical proxy_token failed: {exc}") from exc

    async def list(self) -> list[CredentialMetadata]:  # noqa: A003
        if self._mode == "memory":
            assert self._memory is not None
            out: list[CredentialMetadata] = []
            for vault_id, meta in self._memory.list_all():
                out.append(
                    CredentialMetadata(
                        vault_id=vault_id,
                        name=str(meta.get("name", "")),
                        provider=str(meta.get("provider", "custom")),
                        scopes=list(meta.get("scopes", [])),
                        created_at=meta.get("created_at", datetime.now(UTC)),
                        metadata=dict(meta.get("metadata", {})),
                    )
                )
            return out

        assert self._http is not None
        try:
            resp = await self._http.get(
                f"/api/v3/secrets/{self._project_id}",
                params={"environment": self._environment},
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            raise VaultError(f"infisical list failed: {exc}") from exc

        out2: list[CredentialMetadata] = []
        for entry in data.get("secrets", []):
            md = entry.get("secretMetadata", {}) or {}
            out2.append(
                CredentialMetadata(
                    vault_id=str(md.get("vault_id", entry.get("id", ""))),
                    name=str(entry.get("secretKey", "")),
                    provider=str(md.get("provider", "custom")),
                    scopes=list(md.get("scopes", [])),
                    created_at=datetime.now(UTC),  # API does not echo created_at on list
                    metadata={
                        k: v
                        for k, v in md.items()
                        if k not in {"vault_id", "provider", "scopes"}
                    },
                )
            )
        return out2

    async def get_metadata(self, vault_id: str) -> CredentialMetadata:
        if self._mode == "memory":
            assert self._memory is not None
            meta = self._memory.get_meta(vault_id)
            return CredentialMetadata(
                vault_id=vault_id,
                name=str(meta.get("name", "")),
                provider=str(meta.get("provider", "custom")),
                scopes=list(meta.get("scopes", [])),
                created_at=meta.get("created_at", datetime.now(UTC)),
                metadata=dict(meta.get("metadata", {})),
            )
        # HTTP path: re-use list and filter; Infisical lacks a direct vault_id endpoint.
        items = await self.list()
        for item in items:
            if item.vault_id == vault_id:
                return item
        raise VaultNotFoundError(f"vault entry {vault_id!r} not found")

    async def revoke(self, vault_id: str) -> None:
        logger.info("vault_revoke", vault_id=vault_id)

        if self._mode == "memory":
            assert self._memory is not None
            self._memory.revoke(vault_id)
            return

        assert self._http is not None
        try:
            # List → find name → delete by name. Idempotent: 404 is fine.
            try:
                meta = await self.get_metadata(vault_id)
            except VaultNotFoundError:
                return
            resp = await self._http.delete(
                f"/api/v3/secrets/{self._project_id}/{meta.name}",
                params={"environment": self._environment},
            )
            if resp.status_code not in (200, 204, 404):
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise VaultError(f"infisical revoke failed: {exc}") from exc

    async def replace(
        self,
        vault_id: str,
        value: str,
        *,
        name: str | None = None,
        provider: ProviderName | str | None = None,
        scopes: builtins.list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CredentialMetadata:
        """Replace ``vault_id``'s secret with ``value`` (rotate).

        Semantics:

        * The returned ``CredentialMetadata`` represents the **new** credential.
        * The old ``vault_id`` is revoked (best-effort, idempotent) so any
          previously issued proxy tokens stop resolving.
        * If the old entry's name/provider/scopes are omitted, they are
          carried over from the existing metadata.

        Infisical's REST API does not expose an atomic "rotate by vault_id"
        primitive, so the implementation is *add-new → revoke-old*. The
        window of inconsistency (both credentials live) is short — bounded
        by the second HTTP round-trip — and is acceptable because the new
        credential is what gets handed back to the caller for immediate use.

        Idempotency: if the old ``vault_id`` no longer exists, ``replace``
        still adds the new credential and returns its metadata. The caller
        can interpret this as a recovery from a half-completed rotate.
        """
        # Carry over fields from the existing record when caller omits them.
        # We tolerate "not found" here so a rotate after a partial failure
        # still completes; the new credential is what matters.
        old_meta: CredentialMetadata | None = None
        try:
            old_meta = await self.get_metadata(vault_id)
        except VaultNotFoundError:
            logger.warning(
                "vault_replace_old_missing",
                vault_id=vault_id,
                note="proceeding with rotate; old entry not found",
            )

        effective_name = name or (old_meta.name if old_meta else f"credential_{uuid4().hex[:8]}")
        effective_provider: ProviderName | str = (
            provider
            if provider is not None
            else (old_meta.provider if old_meta else "custom")
        )
        effective_scopes = (
            scopes if scopes is not None else (list(old_meta.scopes) if old_meta else [])
        )
        # Merge metadata: old.metadata + caller overrides. Caller wins.
        effective_metadata: dict[str, Any] = dict(old_meta.metadata) if old_meta else {}
        if metadata:
            effective_metadata.update(metadata)
        effective_metadata.setdefault("rotated_from", vault_id)

        logger.info(
            "vault_replace",
            old_vault_id=vault_id,
            name=effective_name,
            provider=str(effective_provider),
        )

        new_meta = await self.add(
            name=effective_name,
            provider=effective_provider,
            value=value,
            scopes=effective_scopes,
            metadata=effective_metadata,
        )

        # Revoke the old entry. Best-effort: if it's already gone, fine.
        try:
            await self.revoke(vault_id)
        except VaultError as exc:
            logger.warning(
                "vault_replace_revoke_failed",
                old_vault_id=vault_id,
                new_vault_id=new_meta.vault_id,
                error=str(exc),
            )

        return new_meta

    # ------------------------------------------------------------------ helpers

    async def aclose(self) -> None:
        """Close the underlying HTTP client (if any)."""
        if self._http is not None:
            await self._http.aclose()

    @property
    def memory_backend(self) -> _InMemoryBackend | None:
        """Expose the in-memory backend (only set in ``mode=memory``).

        Used by ``VaultProxy`` to resolve proxy tokens locally without
        round-tripping to an external service.
        """
        return self._memory


def create() -> InfisicalVault:
    """Entry-point factory used by the ``wake.vaults`` discovery loader.

    Pulls configuration from the standard ``INFISICAL_*`` environment
    variables, with a sensible in-memory fallback when nothing is
    configured (so importing the package never blows up).
    """
    if not os.getenv("INFISICAL_TOKEN"):
        return InfisicalVault(in_memory=True)
    return InfisicalVault()


__all__ = ["InfisicalVault", "create", "DEFAULT_VAULT_URL"]
