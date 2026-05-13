"""AdapterRegistry — discovers and exposes HarnessAdapter implementations.

Adapters register themselves via the ``wake.adapters`` Python entry-point
group. The runtime calls ``AdapterRegistry.discover()`` at startup to
populate the registry, then ``AdapterRegistry.get(name)`` to resolve
adapters by name.

Adapters can also be registered programmatically via ``register()``,
which is useful in tests and when an embedding application supplies its
own harness without going through Python entry points.
"""

from __future__ import annotations

from importlib import metadata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wake.adapters.base import HarnessAdapter


class AdapterRegistryError(Exception):
    """Raised when the registry cannot satisfy a request."""


class AdapterRegistry:
    """Maps adapter ``name`` → ``HarnessAdapter`` instance.

    Discovery uses the ``wake.adapters`` entry-point group. Each
    entry-point points at either:

    - a callable that returns a ``HarnessAdapter`` instance, or
    - a class with a no-arg constructor that produces one.

    Adapters that need configuration (model client, framework graph,
    etc.) should expose a factory that the caller invokes before
    registering — e.g. ``register(LangGraphAdapter(my_graph))``.
    """

    _ENTRY_POINT_GROUP = "wake.adapters"

    def __init__(self) -> None:
        self._adapters: dict[str, HarnessAdapter] = {}

    def register(self, adapter: HarnessAdapter) -> None:
        """Register an adapter instance under its declared ``name``."""
        name = getattr(adapter, "name", None)
        if not name:
            raise AdapterRegistryError(
                "adapter must declare a non-empty .name attribute"
            )
        self._adapters[name] = adapter

    def get(self, name: str) -> HarnessAdapter:
        """Return the adapter registered under ``name`` or raise."""
        try:
            return self._adapters[name]
        except KeyError as e:
            raise AdapterRegistryError(
                f"no adapter registered under name {name!r}; "
                f"discovered: {sorted(self._adapters)}"
            ) from e

    def list(self) -> list[HarnessAdapter]:
        """Return all registered adapters."""
        return list(self._adapters.values())

    def names(self) -> list[str]:
        """Return the names of all registered adapters."""
        return sorted(self._adapters)

    def discover(self) -> None:
        """Discover adapters via the ``wake.adapters`` entry-point group.

        Errors loading individual entry points are caught and logged; one
        broken adapter does not prevent the rest from registering. Re-raise
        only catastrophic failures (e.g. group lookup itself failing).
        """
        # importlib.metadata.entry_points API changed between Python versions;
        # the .select() form is the stable 3.10+ API.
        eps = metadata.entry_points()
        selected = (
            eps.select(group=self._ENTRY_POINT_GROUP)
            if hasattr(eps, "select")
            else eps.get(self._ENTRY_POINT_GROUP, [])
        )
        for ep in selected:
            try:
                target = ep.load()
            except Exception:  # noqa: BLE001 — log and continue
                # Adapters that fail to import shouldn't take down the runtime.
                continue
            try:
                adapter = target() if callable(target) else target
                self.register(adapter)
            except Exception:  # noqa: BLE001
                continue
