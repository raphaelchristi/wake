"""Generic entry-point registries for runtime-pluggable Wake components.

The existing ``wake.adapters.AdapterRegistry`` introduced the
entry-point discovery pattern for ``HarnessAdapter`` implementations.
Phase 4 brings four new pluggable layers — Store, Sandbox, Vault, and
LLMProvider — that follow the same shape, so this module provides a
small generic ``EntryPointRegistry[T]`` plus four pre-configured
specialisations.

Entry-point groups
------------------

* ``wake.stores``         — factories returning a ``PostgresStore``-like
                            bundle from a DSN.
* ``wake.sandboxes``      — factories returning a ``SandboxAdapter``.
* ``wake.vaults``         — factories returning a ``VaultAdapter``.
* ``wake.llm_providers``  — factories returning an ``LLMProvider``.

Each entry-point should resolve to a *callable* (a function or class).
The registry treats the loaded object as opaque — discovery only records
the factory; instantiation is the caller's responsibility (a Postgres
store needs a DSN, a vault needs credentials, etc.).

Why a separate file from ``wake.adapters.registry``?
----------------------------------------------------

``AdapterRegistry`` registers fully-instantiated adapters because
``HarnessAdapter`` instances are stateless beyond their ``name`` field.
Stores, vaults, providers and (some) sandboxes need configuration to
construct, so the registry holds **factory callables** rather than
instances. Keeping the two patterns separate avoids type-system pretzels.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from importlib import metadata
from typing import Generic, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


class EntryPointRegistryError(Exception):
    """Raised when the registry cannot satisfy a lookup."""


class EntryPointRegistry(Generic[T]):
    """Maps ``name`` → factory callable discovered via entry points.

    ``T`` is the return type of the registered factories (informational
    only — the registry doesn't enforce it).
    """

    def __init__(self, group: str) -> None:
        self._group = group
        self._factories: dict[str, Callable[..., T]] = {}

    @property
    def group(self) -> str:
        """The Python entry-point group this registry pulls from."""
        return self._group

    def register(self, name: str, factory: Callable[..., T]) -> None:
        """Register a factory under ``name``.

        Re-registering the same name overwrites — useful in tests and
        when an embedding application wants to override a plugin.
        """
        if not name:
            raise EntryPointRegistryError(
                "registry name must be a non-empty string"
            )
        self._factories[name] = factory

    def get(self, name: str) -> Callable[..., T]:
        """Return the factory registered under ``name`` or raise."""
        try:
            return self._factories[name]
        except KeyError as e:
            raise EntryPointRegistryError(
                f"no {self._group!r} entry registered under {name!r}; "
                f"discovered: {sorted(self._factories)}"
            ) from e

    def names(self) -> list[str]:
        """Return all registered names in deterministic order."""
        return sorted(self._factories)

    def discover(self) -> None:
        """Populate the registry from the configured entry-point group.

        Errors loading individual entry points are caught and logged;
        one broken plugin doesn't prevent the rest from registering.
        """
        eps = metadata.entry_points()
        selected = (
            eps.select(group=self._group)
            if hasattr(eps, "select")
            else eps.get(self._group, [])  # type: ignore[union-attr]
        )
        for ep in selected:
            try:
                target = ep.load()
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "registry.entry_point.load_failed",
                    extra={"group": self._group, "name": ep.name, "error": str(e)},
                )
                continue
            try:
                self.register(ep.name, target)
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "registry.entry_point.register_failed",
                    extra={"group": self._group, "name": ep.name, "error": str(e)},
                )


# ---------------------------------------------------------------------------
# Pre-configured registries — one per Phase-4 pluggable layer
# ---------------------------------------------------------------------------


def store_registry() -> EntryPointRegistry[object]:
    """Return a fresh registry over the ``wake.stores`` entry-point group."""
    r: EntryPointRegistry[object] = EntryPointRegistry("wake.stores")
    r.discover()
    return r


def sandbox_registry() -> EntryPointRegistry[object]:
    """Return a fresh registry over the ``wake.sandboxes`` entry-point group."""
    r: EntryPointRegistry[object] = EntryPointRegistry("wake.sandboxes")
    r.discover()
    return r


def vault_registry() -> EntryPointRegistry[object]:
    """Return a fresh registry over the ``wake.vaults`` entry-point group."""
    r: EntryPointRegistry[object] = EntryPointRegistry("wake.vaults")
    r.discover()
    return r


def llm_provider_registry() -> EntryPointRegistry[object]:
    """Return a fresh registry over ``wake.llm_providers``."""
    r: EntryPointRegistry[object] = EntryPointRegistry("wake.llm_providers")
    r.discover()
    return r


__all__ = [
    "EntryPointRegistry",
    "EntryPointRegistryError",
    "store_registry",
    "sandbox_registry",
    "vault_registry",
    "llm_provider_registry",
]
