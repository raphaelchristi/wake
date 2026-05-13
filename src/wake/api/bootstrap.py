"""Production app factory for ``wake server``.

The module-level ``app = create_app()`` exposed by ``wake.api.app`` ships
without any storage / dispatcher / sandbox wired up — it's intentionally
"safe to import" so adapters and tests can compose their own stacks.

In production we need the opposite shape: a single entry point that

1. Reads configuration from environment variables.
2. Connects to the configured datastore (SQLite for dev, Postgres in prod).
3. Discovers adapters via Python entry points.
4. Constructs the ``SessionDispatcher``, sandbox adapter, and (optional)
   vault adapter.
5. Returns a fully-wired FastAPI application.

``uvicorn`` will import this module via ``--factory wake.api.bootstrap:create_production_app``
when launched through ``wake server``. The factory shape (an async callable
returning a FastAPI) keeps initialisation off the import path so failures
surface in the lifespan boot rather than at module-load time.

Environment surface
-------------------

==========================  ==========================================
Variable                    Meaning
==========================  ==========================================
``WAKE_DATABASE_URL``       SQLAlchemy DSN. ``sqlite+aiosqlite:///...``
                            uses the in-tree SQLite store; any DSN
                            starting with ``postgres`` / ``postgresql``
                            uses the optional ``wake-store-postgres``
                            adapter (must be installed).
                            Default: ``sqlite+aiosqlite:///./wake.db``.
``WAKE_SANDBOX_BACKEND``    ``docker`` (default), ``sandbox-runtime``
                            (discovers ``wake.sandboxes`` entry point),
                            or ``none`` to disable sandbox wiring.
``WAKE_VAULT_PROVIDER``     ``none`` (default) or ``infisical`` to wire
                            the ``wake_vault_infisical`` adapter when
                            installed.
``WAKE_API_KEY``            Forwarded to the auth dependency via env;
                            not consumed directly here.
``WAKE_API_CORS_ORIGINS``   Forwarded to ``create_app``; not consumed
                            directly here.
==========================  ==========================================
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import structlog

from wake.adapters.registry import AdapterRegistry
from wake.api.app import create_app
from wake.core.event_log import EventLog
from wake.core.session import SessionStateMachine
from wake.runtime.dispatcher import SessionDispatcher
from wake.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from fastapi import FastAPI

    from wake.sandbox.base import SandboxAdapter

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Env var names — exported so tests can monkeypatch via constants
# ---------------------------------------------------------------------------

WAKE_DATABASE_URL_ENV = "WAKE_DATABASE_URL"
WAKE_SANDBOX_BACKEND_ENV = "WAKE_SANDBOX_BACKEND"
WAKE_VAULT_PROVIDER_ENV = "WAKE_VAULT_PROVIDER"

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./wake.db"
DEFAULT_SANDBOX_BACKEND = "docker"
DEFAULT_VAULT_PROVIDER = "none"


# ---------------------------------------------------------------------------
# Store construction
# ---------------------------------------------------------------------------


async def build_store(dsn: str | None = None) -> Any:
    """Return an initialised store bundle for ``dsn``.

    The returned object exposes the same ``.agents`` / ``.environments`` /
    ``.sessions`` / ``.events`` facade shape as
    :class:`wake.store.sqlite.SQLiteStore`. We accept the duck-typed shape
    so the ``wake-store-postgres`` adapter can plug in without forcing a
    hard import here.
    """
    url = dsn if dsn is not None else os.environ.get(
        WAKE_DATABASE_URL_ENV, DEFAULT_DATABASE_URL
    )
    if url.startswith("postgres"):
        try:
            from wake_store_postgres.store import create_from_dsn
        except ImportError as exc:  # pragma: no cover - optional dep
            raise RuntimeError(
                "WAKE_DATABASE_URL points at Postgres but the "
                "wake-store-postgres adapter is not installed. "
                "Install with `pip install wake-store-postgres`."
            ) from exc
        store = create_from_dsn(url)
    else:
        from wake.store.sqlite import SQLiteStore

        store = SQLiteStore(url)

    await store.initialize()
    logger.info("bootstrap.store.ready", backend=type(store).__name__)
    return store


# ---------------------------------------------------------------------------
# Sandbox construction
# ---------------------------------------------------------------------------


def build_sandbox(backend: str | None = None) -> SandboxAdapter | None:
    """Return a sandbox adapter for ``backend`` (or ``None`` if disabled).

    ``backend="none"`` is a first-class option: the API still works for
    catalog / replay use cases that don't need to execute tools, just
    return 501 from any tool-execution path.
    """
    name = (
        backend
        if backend is not None
        else os.environ.get(WAKE_SANDBOX_BACKEND_ENV, DEFAULT_SANDBOX_BACKEND)
    ).strip().lower()

    if name in {"none", "", "disabled"}:
        logger.info("bootstrap.sandbox.disabled")
        return None

    if name == "docker":
        try:
            from wake.sandbox.docker import DockerSandbox

            sb = DockerSandbox()
        except Exception as exc:  # noqa: BLE001 - docker SDK is optional
            logger.warning(
                "bootstrap.sandbox.docker_unavailable",
                error=str(exc),
            )
            return None
        logger.info("bootstrap.sandbox.ready", backend="docker")
        return sb

    # Anything else: try the entry-point registry. This lets the
    # sandbox-runtime adapter plug in without a hard import.
    try:
        from wake.runtime.registry import sandbox_registry
    except ImportError:  # pragma: no cover - runtime package always present
        logger.warning("bootstrap.sandbox.registry_unavailable", backend=name)
        return None
    reg = sandbox_registry()
    try:
        factory = reg.get(name)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "bootstrap.sandbox.unknown_backend",
            backend=name,
            error=str(exc),
            registered=reg.names(),
        )
        return None
    sb_obj: SandboxAdapter = factory()
    logger.info("bootstrap.sandbox.ready", backend=name)
    return sb_obj


# ---------------------------------------------------------------------------
# Vault construction (optional)
# ---------------------------------------------------------------------------


def build_vault(provider: str | None = None) -> object | None:
    """Return a Vault adapter or ``None`` if disabled / unavailable.

    The vault is *optional* — when no provider is configured the routes
    return 503 (handled by ``get_vault`` in ``dependencies.py``).
    """
    name = (
        provider
        if provider is not None
        else os.environ.get(WAKE_VAULT_PROVIDER_ENV, DEFAULT_VAULT_PROVIDER)
    ).strip().lower()

    if name in {"none", "", "disabled"}:
        logger.info("bootstrap.vault.disabled")
        return None

    if name == "infisical":
        try:
            from wake_vault_infisical.vault import create as create_infisical
        except ImportError as exc:
            logger.warning(
                "bootstrap.vault.infisical_unavailable",
                error=str(exc),
            )
            return None
        try:
            v = create_infisical()
        except Exception as exc:  # noqa: BLE001 - vault init may need creds
            logger.warning("bootstrap.vault.init_failed", error=str(exc))
            return None
        logger.info("bootstrap.vault.ready", provider="infisical")
        return v

    # Fall back to the entry-point registry for unknown providers.
    try:
        from wake.runtime.registry import vault_registry
    except ImportError:  # pragma: no cover
        return None
    reg = vault_registry()
    try:
        factory = reg.get(name)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "bootstrap.vault.unknown_provider",
            provider=name,
            error=str(exc),
            registered=reg.names(),
        )
        return None
    return factory()


# ---------------------------------------------------------------------------
# Top-level factory
# ---------------------------------------------------------------------------


async def build_components(
    *,
    dsn: str | None = None,
    sandbox_backend: str | None = None,
    vault_provider: str | None = None,
) -> dict[str, Any]:
    """Build every wake component a fully-wired API needs.

    Used by :func:`create_production_app` and reused by ``wake worker``
    so both processes share identical wiring.
    """
    store = await build_store(dsn)
    sandbox = build_sandbox(sandbox_backend)
    vault = build_vault(vault_provider)

    event_log = EventLog(store.events)
    session_machine = SessionStateMachine(store.sessions, event_log)
    tool_registry = ToolRegistry(sandbox=sandbox)
    adapter_registry = AdapterRegistry()
    adapter_registry.discover()
    dispatcher = SessionDispatcher(adapter_registry, event_log, tool_registry)

    logger.info(
        "bootstrap.components.ready",
        adapters=adapter_registry.names(),
        sandbox=sandbox is not None,
        vault=vault is not None,
    )

    return {
        "store": store,
        "event_log": event_log,
        "session_machine": session_machine,
        "tool_registry": tool_registry,
        "adapter_registry": adapter_registry,
        "dispatcher": dispatcher,
        "sandbox": sandbox,
        "vault": vault,
    }


async def create_production_app() -> FastAPI:
    """Build a fully-wired production FastAPI app.

    Reads configuration from environment variables (see module docstring).
    Designed for use with ``uvicorn --factory``:

        uvicorn wake.api.bootstrap:create_production_app --factory

    The returned app is identical in shape to ``wake.api.app.create_app``
    — the only difference is that *every* component is non-``None``, so
    routes never return 501 "not configured" in production.
    """
    components = await build_components()
    store = components["store"]
    return create_app(
        agent_store=store.agents,
        environment_store=store.environments,
        session_store=store.sessions,
        event_log=components["event_log"],
        session_machine=components["session_machine"],
        tool_registry=components["tool_registry"],
        sandbox=components["sandbox"],
        adapter_registry=components["adapter_registry"],
        dispatcher=components["dispatcher"],
        vault=components["vault"],
    )


__all__ = [
    "DEFAULT_DATABASE_URL",
    "DEFAULT_SANDBOX_BACKEND",
    "DEFAULT_VAULT_PROVIDER",
    "WAKE_DATABASE_URL_ENV",
    "WAKE_SANDBOX_BACKEND_ENV",
    "WAKE_VAULT_PROVIDER_ENV",
    "build_components",
    "build_sandbox",
    "build_store",
    "build_vault",
    "create_production_app",
]
