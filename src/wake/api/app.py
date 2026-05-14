# ruff: noqa: TC003
"""FastAPI application factory.

``create_app()`` wires routes + dependencies and returns a FastAPI instance.
``app`` is a module-level instance for ``uvicorn wake.api.app:app``.

The foundation slice provides the storage layer; this factory only depends on
ABC interfaces. Phase 2 swapped the hardcoded ``AnthropicHarness`` for an
``AdapterRegistry`` + ``SessionDispatcher`` pair — the API is otherwise
unchanged.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import structlog
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from wake import __version__
from wake.api.dependencies import (
    WAKE_API_KEY_ENV,
    AppState,
    _auth_required_flag,
    is_under_pytest,
    verify_api_key,
)
from wake.api.metrics_prom import install_prometheus
from wake.api.middleware.backpressure import BackpressureMiddleware
from wake.api.ratelimit import (
    RateLimitExceededError,
    build_limiter,
    rate_limit_dep,
    rate_limit_exceeded_handler,
)
from wake.api.routes import agents as agents_routes
from wake.api.routes import environments as environments_routes
from wake.api.routes import events as events_routes
from wake.api.routes import metrics as metrics_routes
from wake.api.routes import sessions as sessions_routes
from wake.api.routes import state as state_routes
from wake.api.routes import users as users_routes
from wake.api.routes import vault as vault_routes
from wake.api.sse import router as sse_router

#: Env var consulted for CORS origin allowlist (comma-separated).
WAKE_CORS_ENV = "WAKE_API_CORS_ORIGINS"
#: Routes that do not require an API key (health/discovery).
_AUTH_EXEMPT_PATHS = ("/health", "/docs", "/redoc", "/openapi.json")

if TYPE_CHECKING:
    from wake.adapters.registry import AdapterRegistry
    from wake.core.event_log import EventLog
    from wake.core.session import SessionStateMachine
    from wake.runtime.dispatcher import SessionDispatcher
    from wake.sandbox.base import SandboxAdapter
    from wake.store.base import AgentStore, EnvironmentStore, SessionStore, UserStore
    from wake.tools.registry import ToolRegistry

logger = structlog.get_logger(__name__)


def create_app(
    *,
    agent_store: AgentStore | None = None,
    environment_store: EnvironmentStore | None = None,
    session_store: SessionStore | None = None,
    user_store: UserStore | None = None,
    event_log: EventLog | None = None,
    session_machine: SessionStateMachine | None = None,
    tool_registry: ToolRegistry | None = None,
    sandbox: SandboxAdapter | None = None,
    adapter_registry: AdapterRegistry | None = None,
    dispatcher: SessionDispatcher | None = None,
    vault: object | None = None,
    oauth_clients: dict[str, dict[str, str]] | None = None,
) -> FastAPI:
    """Build a FastAPI app wired with the provided wake components.

    All components are optional: routes will return 501 if a required component
    is missing. This lets the runtime slice ship while foundation is still WIP.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("wake_api_starting", version=__version__)
        # Warn if the API is going to accept everything because no key is
        # configured AND fail-closed mode is off. Production deploys MUST
        # set ``WAKE_AUTH_REQUIRED=true`` so an unset ``WAKE_API_KEY``
        # surfaces as 503 instead of a silent fail-open.
        key_set = bool(os.environ.get(WAKE_API_KEY_ENV, "").strip())
        required = _auth_required_flag()
        if not key_set and not required and not is_under_pytest():
            logger.warning(
                "wake_auth_disabled",
                detail=(
                    "WAKE_API_KEY is unset and WAKE_AUTH_REQUIRED is not "
                    "enabled — the API will accept unauthenticated "
                    "requests. Set WAKE_AUTH_REQUIRED=true to fail closed "
                    "or set WAKE_API_KEY to enforce auth."
                ),
            )
        elif not key_set and required:
            logger.warning(
                "wake_auth_required_no_key",
                detail=(
                    "WAKE_AUTH_REQUIRED=true but WAKE_API_KEY is unset — "
                    "all authenticated routes will return 503."
                ),
            )
        yield
        logger.info("wake_api_shutting_down")
        state: AppState = app.state.wake
        if state.sandbox is not None:
            for handle in list(state.sandbox_handles.values()):
                try:
                    await state.sandbox.destroy(handle)  # type: ignore[arg-type]
                except Exception:  # noqa: BLE001
                    logger.warning("sandbox_destroy_on_shutdown_failed")
            state.sandbox_handles.clear()

    app = FastAPI(
        title="Wake",
        version=__version__,
        description="Durable runtime substrate for AI agents.",
        lifespan=lifespan,
    )

    # Phase 7 ops-throughput: rate-limit storage backend + exception
    # handler. The limiter is stashed on ``app.state.limiter`` so the
    # ``Depends(rate_limit_dep(...))`` calls below can resolve it.
    app.state.limiter = build_limiter()
    app.add_exception_handler(RateLimitExceededError, rate_limit_exceeded_handler)  # type: ignore[arg-type]

    # Phase 7 ops-throughput: backpressure middleware injects the
    # ``X-Wake-Worker-Saturation`` header on every response and
    # returns 503 + ``Retry-After: 30`` when the dispatcher is
    # saturated. Mount BEFORE CORS so the saturation header is part
    # of the response that CORS preflight observes.
    app.add_middleware(BackpressureMiddleware)

    # CORS — the Wake Dashboard runs on :3000 in dev and at a configurable
    # origin in production. ``WAKE_API_CORS_ORIGINS`` accepts a comma-separated
    # list; the default permits the dashboard's dev server only.
    cors_env = os.environ.get(WAKE_CORS_ENV, "").strip()
    allow_origins = (
        [o.strip() for o in cors_env.split(",") if o.strip()]
        if cors_env
        else ["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
        expose_headers=["X-Wake-API-Key", "X-Wake-Worker-Saturation"],
    )

    app.state.wake = AppState(
        agent_store=agent_store,
        environment_store=environment_store,
        session_store=session_store,
        user_store=user_store,
        event_log=event_log,
        session_machine=session_machine,
        tool_registry=tool_registry,
        sandbox=sandbox,
        adapter_registry=adapter_registry,
        dispatcher=dispatcher,
        vault=vault,
        oauth_clients=oauth_clients or {},
    )

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, Any]:
        state: AppState = app.state.wake
        return {
            "status": "ok",
            "version": __version__,
            "components": {
                "agent_store": state.agent_store is not None,
                "environment_store": state.environment_store is not None,
                "session_store": state.session_store is not None,
                "event_log": state.event_log is not None,
                "session_machine": state.session_machine is not None,
                "tool_registry": state.tool_registry is not None,
                "sandbox": state.sandbox is not None,
                "adapter_registry": state.adapter_registry is not None,
                "dispatcher": state.dispatcher is not None,
                "adapters": (
                    state.adapter_registry.names()
                    if state.adapter_registry is not None
                    else []
                ),
            },
        }

    # Auth dependency is wired here so the legacy /health, /docs, /redoc and
    # /openapi.json surfaces remain unauthenticated. Per-router opt-in lets
    # all slices (sessions, replay, metrics, vault) inherit auth uniformly.
    #
    # Phase 7 ops-throughput: per-router rate-limit dependency. The
    # method-aware dependency picks write vs read budget based on
    # the HTTP verb (resolved at request time), so a single dep call
    # covers POST/GET/PATCH/DELETE per router without per-route
    # decoration.
    auth_dep = [Depends(verify_api_key), Depends(rate_limit_dep())]
    app.include_router(agents_routes.router, dependencies=auth_dep)
    app.include_router(environments_routes.router, dependencies=auth_dep)
    app.include_router(sessions_routes.router, dependencies=auth_dep)
    app.include_router(events_routes.router, dependencies=auth_dep)
    app.include_router(state_routes.router, dependencies=auth_dep)
    app.include_router(metrics_routes.router, dependencies=auth_dep)
    app.include_router(users_routes.router, dependencies=auth_dep)
    app.include_router(vault_routes.router, dependencies=auth_dep)
    app.include_router(sse_router, dependencies=auth_dep)

    # Prometheus exposition — ``GET /metrics`` in text format. NOT auth
    # gated (Prom convention; scrapers don't carry app API keys — protect
    # via NetworkPolicy / firewall). Lives alongside the JSON
    # ``GET /v1/metrics/summary`` endpoint owned by ``metrics_routes``.
    # Phase 7 / Tier 1 gap #8.
    install_prometheus(app)

    return app


# Module-level app — **dev shortcut only**. This instance has no stores,
# no dispatcher, no sandbox: every business route will return 501 until
# the components are attached. Production deployments must use
# ``wake.api.bootstrap:create_production_app`` (mounted by ``wake server``
# via ``uvicorn --factory``). Tests should build their own ``create_app``
# call with in-memory fakes (see ``tests/conftest.py``).
app = create_app()
