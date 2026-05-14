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
when launched through ``wake server``. ``create_production_app`` is a
**synchronous** callable that returns a FastAPI app immediately — async
initialisation (store ``initialize()``, adapter discovery, etc.) runs in
the app's lifespan startup, which is what Uvicorn awaits before
accepting traffic. Keeping the factory sync is mandatory: Uvicorn calls
``app_factory()`` from a sync context and treats anything returned as
the ASGI app; an ``async def`` would hand back a coroutine and crash on
the first request.

Tests that need a fully-wired app *outside* a real Uvicorn loop should
call :func:`build_components` + :func:`create_app` directly, or import
:func:`create_production_app_async` and ``await`` it.

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
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

import structlog
from fastapi import FastAPI

from wake.adapters.registry import AdapterRegistry
from wake.api.app import create_app
from wake.api.dependencies import AppState
from wake.core.event_log import EventLog
from wake.core.session import SessionStateMachine
from wake.runtime.dispatcher import SessionDispatcher
from wake.tools.registry import ToolRegistry

if TYPE_CHECKING:
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
    # Registry holds untyped factories; we trust the entry-point group
    # contract and cast back to the SandboxAdapter shape.
    sb_obj = cast("SandboxAdapter", factory())
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
            v: object = create_infisical()
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
    # Phase 7 — cost-budget enforcer. Wires post-step interrupt when
    # the per-session running cost exceeds ``agent.metadata.max_cost_usd``.
    from wake.runtime.cost_budget import CostBudgetEnforcer

    cost_budget = CostBudgetEnforcer(event_log, session_machine)
    dispatcher = SessionDispatcher(
        adapter_registry, event_log, tool_registry, cost_budget=cost_budget
    )

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


def create_production_app() -> FastAPI:
    """Build a production FastAPI app — **synchronous Uvicorn factory**.

    Reads configuration from environment variables (see module docstring).
    Designed for use with ``uvicorn --factory``:

        uvicorn wake.api.bootstrap:create_production_app --factory

    Uvicorn invokes factories from a synchronous context and expects a
    raw ASGI app — not a coroutine. We therefore return a ``FastAPI``
    instance immediately, wiring an *empty* :class:`AppState` and
    deferring all async initialisation (store ``initialize()``, adapter
    discovery, sandbox/vault construction) to the lifespan startup
    handler, which Uvicorn awaits before accepting traffic.

    For a fully-initialised app *outside* a Uvicorn loop (tests,
    scripts, the worker entrypoint), use :func:`create_production_app_async`.
    """
    app = create_app()  # all components None → empty shell

    @asynccontextmanager
    async def _wired_lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # 1. Bootstrap everything async.
        components = await build_components()
        store = components["store"]
        # 2. Mutate the AppState in place — routes already hold a
        #    ``request.app.state.wake`` reference, so swapping
        #    individual fields is enough; we do *not* rebind the
        #    container itself.
        state: AppState = _app.state.wake
        state.agent_store = store.agents
        state.environment_store = store.environments
        state.session_store = store.sessions
        state.event_log = components["event_log"]
        state.session_machine = components["session_machine"]
        state.tool_registry = components["tool_registry"]
        state.sandbox = components["sandbox"]
        state.adapter_registry = components["adapter_registry"]
        state.dispatcher = components["dispatcher"]
        state.vault = components["vault"]
        # Stash the store for shutdown.
        _app.state.wake_store = store
        logger.info(
            "bootstrap.app.ready",
            adapters=components["adapter_registry"].names(),
        )
        try:
            yield
        finally:
            # Cleanup sandbox handles + close the store.
            if state.sandbox is not None:
                for handle in list(state.sandbox_handles.values()):
                    try:
                        await state.sandbox.destroy(handle)  # type: ignore[arg-type]
                    except Exception:  # noqa: BLE001
                        logger.warning("bootstrap.sandbox.destroy_failed")
                state.sandbox_handles.clear()
            close = getattr(store, "close", None)
            if close is not None:
                try:
                    await close()
                except Exception:  # noqa: BLE001
                    logger.warning("bootstrap.store.close_failed")

    # Replace the empty-shell lifespan on the FastAPI instance.
    # Starlette caches the lifespan on the router; assigning it here is
    # the simplest stable hook across Starlette versions.
    app.router.lifespan_context = _wired_lifespan
    return app


async def create_production_app_async() -> FastAPI:
    """Async sibling of :func:`create_production_app` for direct awaiting.

    Use from tests/scripts where there is no Uvicorn loop to drive the
    lifespan. Returns an app whose ``AppState`` is already populated
    (no lifespan dependency required).
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
    "create_production_app_async",
]
