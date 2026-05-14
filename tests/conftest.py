"""Shared pytest configuration."""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest_asyncio.fixture
async def app_components() -> dict[str, Any]:
    """Build an in-memory wake stack for tests.

    Includes an empty ``AdapterRegistry`` and a ``SessionDispatcher`` so
    API routes that exercise the dispatch path can run without booting
    the real Claude SDK adapter.
    """
    from tests.unit.fakes import (
        InMemoryAgentStore,
        InMemoryEnvironmentStore,
        InMemoryEventStore,
        InMemorySessionStore,
        InMemoryUserStore,
    )
    from wake.adapters.registry import AdapterRegistry
    from wake.core.event_log import EventLog
    from wake.core.session import SessionStateMachine
    from wake.runtime.dispatcher import SessionDispatcher
    from wake.tools.registry import ToolRegistry

    event_store = InMemoryEventStore()
    session_store = InMemorySessionStore()
    agent_store = InMemoryAgentStore()
    environment_store = InMemoryEnvironmentStore()
    user_store = InMemoryUserStore()
    event_log = EventLog(event_store)
    session_machine = SessionStateMachine(session_store, event_log)
    tool_registry = ToolRegistry()
    adapter_registry = AdapterRegistry()
    dispatcher = SessionDispatcher(adapter_registry, event_log, tool_registry)

    return {
        "agent_store": agent_store,
        "environment_store": environment_store,
        "session_store": session_store,
        "user_store": user_store,
        "event_store": event_store,
        "event_log": event_log,
        "session_machine": session_machine,
        "tool_registry": tool_registry,
        "adapter_registry": adapter_registry,
        "dispatcher": dispatcher,
    }


@pytest_asyncio.fixture
async def app(app_components: dict[str, Any]) -> FastAPI:
    from wake.api.app import create_app

    return create_app(
        agent_store=app_components["agent_store"],
        environment_store=app_components["environment_store"],
        session_store=app_components["session_store"],
        user_store=app_components["user_store"],
        event_log=app_components["event_log"],
        session_machine=app_components["session_machine"],
        tool_registry=app_components["tool_registry"],
        adapter_registry=app_components["adapter_registry"],
        dispatcher=app_components["dispatcher"],
    )


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
