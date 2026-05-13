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

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import structlog
from fastapi import FastAPI

from wake import __version__
from wake.api.dependencies import AppState
from wake.api.routes import agents as agents_routes
from wake.api.routes import environments as environments_routes
from wake.api.routes import events as events_routes
from wake.api.routes import sessions as sessions_routes
from wake.api.sse import router as sse_router

if TYPE_CHECKING:
    from wake.adapters.registry import AdapterRegistry
    from wake.core.event_log import EventLog
    from wake.core.session import SessionStateMachine
    from wake.runtime.dispatcher import SessionDispatcher
    from wake.sandbox.base import SandboxAdapter
    from wake.store.base import AgentStore, EnvironmentStore, SessionStore
    from wake.tools.registry import ToolRegistry

logger = structlog.get_logger(__name__)


def create_app(
    *,
    agent_store: AgentStore | None = None,
    environment_store: EnvironmentStore | None = None,
    session_store: SessionStore | None = None,
    event_log: EventLog | None = None,
    session_machine: SessionStateMachine | None = None,
    tool_registry: ToolRegistry | None = None,
    sandbox: SandboxAdapter | None = None,
    adapter_registry: AdapterRegistry | None = None,
    dispatcher: SessionDispatcher | None = None,
) -> FastAPI:
    """Build a FastAPI app wired with the provided wake components.

    All components are optional: routes will return 501 if a required component
    is missing. This lets the runtime slice ship while foundation is still WIP.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("wake_api_starting", version=__version__)
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

    app.state.wake = AppState(
        agent_store=agent_store,
        environment_store=environment_store,
        session_store=session_store,
        event_log=event_log,
        session_machine=session_machine,
        tool_registry=tool_registry,
        sandbox=sandbox,
        adapter_registry=adapter_registry,
        dispatcher=dispatcher,
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

    app.include_router(agents_routes.router)
    app.include_router(environments_routes.router)
    app.include_router(sessions_routes.router)
    app.include_router(events_routes.router)
    app.include_router(sse_router)

    return app


# Module-level app for ``uvicorn wake.api.app:app``. Components are wired
# by the CLI / launcher before requests hit the API.
app = create_app()
