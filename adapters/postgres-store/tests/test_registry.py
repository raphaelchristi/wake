"""Tests for the generic entry-point registry introduced by this slice.

These run without Docker — they exercise the pattern that will be
re-used by the sandbox-runtime / vault-llm-deploy slices.
"""

from __future__ import annotations

import pytest
from wake.runtime.registry import EntryPointRegistry, EntryPointRegistryError


def test_register_and_get() -> None:
    r: EntryPointRegistry[str] = EntryPointRegistry("wake.test_group")

    def factory() -> str:
        return "hello"

    r.register("greeter", factory)
    assert r.get("greeter") is factory
    assert factory() == "hello"


def test_get_missing_raises() -> None:
    r: EntryPointRegistry[str] = EntryPointRegistry("wake.test_group")
    with pytest.raises(EntryPointRegistryError):
        r.get("nope")


def test_register_empty_name_raises() -> None:
    r: EntryPointRegistry[str] = EntryPointRegistry("wake.test_group")
    with pytest.raises(EntryPointRegistryError):
        r.register("", lambda: "x")


def test_names_is_sorted() -> None:
    r: EntryPointRegistry[str] = EntryPointRegistry("wake.test_group")
    r.register("zeta", lambda: "z")
    r.register("alpha", lambda: "a")
    assert r.names() == ["alpha", "zeta"]


def test_discover_picks_up_wake_stores_postgres() -> None:
    """The package's own entry point should be discoverable."""
    from wake.runtime.registry import store_registry

    r = store_registry()
    assert "postgres" in r.names()
    factory = r.get("postgres")
    # ``create_from_dsn`` is the registered factory.
    assert callable(factory)
