"""Phase 7 — worker backpressure coverage.

Acceptance criteria (ops-throughput contract):

* saturation < threshold → response carries header only.
* saturation >= 1.0 → 503 + ``Retry-After: 30``.
* Header value rounded to 3 decimal places.
* Health/discovery endpoints stay reachable when saturated.
* ``WAKE_BACKPRESSURE_DISABLED=true`` opts out entirely.
* Dispatcher's ``in_flight`` counter increments+decrements correctly
  around an adapter step.
"""

# Some imports inside test functions are needed at runtime (async
# generator definitions, class instantiation) — TC checks would push
# them into a TYPE_CHECKING block which breaks the code.
# ruff: noqa: TC001, TC003

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from wake.api.dependencies import AppState
from wake.api.middleware.backpressure import (
    SATURATION_HEADER,
    WAKE_BACKPRESSURE_DISABLED_ENV,
    WAKE_BACKPRESSURE_RETRY_AFTER_ENV,
    WAKE_BACKPRESSURE_THRESHOLD_ENV,
    BackpressureMiddleware,
    format_saturation,
)

pytestmark = pytest.mark.asyncio


class _FakeDispatcher:
    """Minimal dispatcher stub exposing ``saturation()``."""

    def __init__(self, value: float, in_flight: int = 0, ceiling: int = 1) -> None:
        self._value = value
        self.in_flight = in_flight
        self.max_in_flight = ceiling

    def saturation(self) -> float:
        return self._value


def _make_app(dispatcher: object | None) -> FastAPI:
    app = FastAPI()
    app.state.wake = AppState(dispatcher=dispatcher)  # type: ignore[arg-type]
    app.add_middleware(BackpressureMiddleware)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/some-route")
    async def some_route() -> dict[str, str]:
        return {"ok": "yes"}

    return app


async def test_below_threshold_emits_only_saturation_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(WAKE_BACKPRESSURE_DISABLED_ENV, raising=False)
    monkeypatch.delenv(WAKE_BACKPRESSURE_THRESHOLD_ENV, raising=False)
    app = _make_app(_FakeDispatcher(0.5))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/some-route")
    assert r.status_code == 200
    assert SATURATION_HEADER in r.headers
    assert r.headers[SATURATION_HEADER] == "0.500"


async def test_at_or_above_threshold_returns_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(WAKE_BACKPRESSURE_DISABLED_ENV, raising=False)
    monkeypatch.delenv(WAKE_BACKPRESSURE_THRESHOLD_ENV, raising=False)
    app = _make_app(_FakeDispatcher(1.0))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/some-route")
    assert r.status_code == 503
    assert r.headers.get("Retry-After") == "30"
    assert r.headers[SATURATION_HEADER] == "1.000"
    body = r.json()
    assert body["retry_after"] == 30
    assert body["saturation"] == "1.000"


async def test_health_endpoint_bypasses_backpressure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Probes must keep working even when saturated."""
    monkeypatch.delenv(WAKE_BACKPRESSURE_DISABLED_ENV, raising=False)
    monkeypatch.delenv(WAKE_BACKPRESSURE_THRESHOLD_ENV, raising=False)
    app = _make_app(_FakeDispatcher(5.0))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/health")
    assert r.status_code == 200


async def test_header_value_rounded_to_3_decimals() -> None:
    assert format_saturation(0.1234567) == "0.123"
    assert format_saturation(0.5) == "0.500"
    assert format_saturation(1.0) == "1.000"
    assert format_saturation(-0.5) == "0.000"
    assert format_saturation(2.345) == "2.345"


async def test_disabled_env_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """``WAKE_BACKPRESSURE_DISABLED=true`` short-circuits the middleware."""
    monkeypatch.setenv(WAKE_BACKPRESSURE_DISABLED_ENV, "true")
    app = _make_app(_FakeDispatcher(2.0))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/some-route")
    # Saturation header absent (middleware is a no-op) and request OK.
    assert r.status_code == 200
    assert SATURATION_HEADER not in r.headers


async def test_threshold_override_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Custom threshold below 1.0 triggers 503 earlier."""
    monkeypatch.delenv(WAKE_BACKPRESSURE_DISABLED_ENV, raising=False)
    monkeypatch.setenv(WAKE_BACKPRESSURE_THRESHOLD_ENV, "0.7")
    monkeypatch.setenv(WAKE_BACKPRESSURE_RETRY_AFTER_ENV, "15")
    app = _make_app(_FakeDispatcher(0.8))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/some-route")
    assert r.status_code == 503
    assert r.headers["Retry-After"] == "15"


async def test_no_dispatcher_treats_saturation_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a dispatcher the middleware reports 0.0 saturation."""
    monkeypatch.delenv(WAKE_BACKPRESSURE_DISABLED_ENV, raising=False)
    monkeypatch.delenv(WAKE_BACKPRESSURE_THRESHOLD_ENV, raising=False)
    app = _make_app(None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/some-route")
    assert r.status_code == 200
    assert r.headers[SATURATION_HEADER] == "0.000"


# ---------------------------------------------------------------------------
# Dispatcher gauge
# ---------------------------------------------------------------------------


async def test_dispatcher_in_flight_counter_increments_and_decrements() -> None:
    """The dispatcher's gauge must rise and fall around ``run_step``."""
    import asyncio
    from collections.abc import AsyncIterator
    from datetime import UTC, datetime

    from tests.unit.fakes import InMemoryEventStore
    from wake.adapters.context import SessionContext
    from wake.adapters.registry import AdapterRegistry
    from wake.core.event_log import EventLog
    from wake.runtime.dispatcher import SessionDispatcher
    from wake.tools.registry import ToolRegistry
    from wake.types import AgentConfig, Event, ModelConfig, Session

    event_log = EventLog(InMemoryEventStore())
    adapters = AdapterRegistry()

    saw_in_flight: list[int] = []
    in_step = asyncio.Event()
    release = asyncio.Event()

    class _SlowAdapter:
        name = "slow"

        async def on_lifecycle(
            self, ctx: SessionContext, lifecycle: str
        ) -> None: ...

        async def step(
            self,
            ctx: SessionContext,
            events: Any,
            tools: Any,
        ) -> AsyncIterator[Event]:
            in_step.set()
            await release.wait()
            return
            yield  # make this a generator

    adapters.register(_SlowAdapter())  # type: ignore[arg-type]

    dispatcher = SessionDispatcher(adapters, event_log, ToolRegistry(), max_in_flight=4)
    assert dispatcher.in_flight == 0
    assert dispatcher.saturation() == 0.0

    agent = AgentConfig(
        id="agent_1",
        name="x",
        model=ModelConfig(id="claude"),
        version=1,
        metadata={"harness": "slow"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session = Session(
        id="01HSESSION0000000000000IF1",
        agent_id=agent.id,
        agent_version=1,
        status="idle",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    task = asyncio.create_task(dispatcher.run_step(session, agent))
    await in_step.wait()
    saw_in_flight.append(dispatcher.in_flight)
    release.set()
    await task

    assert saw_in_flight == [1]
    assert dispatcher.in_flight == 0
    assert dispatcher.saturation() == 0.0


async def test_dispatcher_saturation_property() -> None:
    """Sanity: saturation = in_flight / max_in_flight."""
    from tests.unit.fakes import InMemoryEventStore
    from wake.adapters.registry import AdapterRegistry
    from wake.core.event_log import EventLog
    from wake.runtime.dispatcher import SessionDispatcher
    from wake.tools.registry import ToolRegistry

    dispatcher = SessionDispatcher(
        AdapterRegistry(),
        EventLog(InMemoryEventStore()),
        ToolRegistry(),
        max_in_flight=10,
    )
    dispatcher.in_flight = 7
    assert dispatcher.saturation() == 0.7
    assert dispatcher.queue_depth == 7
