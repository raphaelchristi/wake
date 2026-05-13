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
    """Build an in-memory wake stack for tests."""
    from tests.unit.fakes import (
        InMemoryAgentStore,
        InMemoryEnvironmentStore,
        InMemoryEventStore,
        InMemorySessionStore,
    )
    from wake.core.event_log import EventLog
    from wake.core.session import SessionStateMachine
    from wake.tools.registry import ToolRegistry

    event_store = InMemoryEventStore()
    session_store = InMemorySessionStore()
    agent_store = InMemoryAgentStore()
    environment_store = InMemoryEnvironmentStore()
    event_log = EventLog(event_store)
    session_machine = SessionStateMachine(session_store, event_log)
    tool_registry = ToolRegistry()

    return {
        "agent_store": agent_store,
        "environment_store": environment_store,
        "session_store": session_store,
        "event_store": event_store,
        "event_log": event_log,
        "session_machine": session_machine,
        "tool_registry": tool_registry,
    }


@pytest_asyncio.fixture
async def app(app_components: dict[str, Any]) -> FastAPI:
    from wake.api.app import create_app

    return create_app(
        agent_store=app_components["agent_store"],
        environment_store=app_components["environment_store"],
        session_store=app_components["session_store"],
        event_log=app_components["event_log"],
        session_machine=app_components["session_machine"],
        tool_registry=app_components["tool_registry"],
    )


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
