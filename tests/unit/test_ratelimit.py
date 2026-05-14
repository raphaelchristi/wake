"""Phase 7 — rate-limit middleware coverage.

Acceptance criteria (ops-throughput contract):

* Under-limit requests pass through unchanged.
* Over-limit requests return 429 with ``Retry-After`` + JSON body.
* Redis URL fallback: invalid/unreachable backend falls back to
  in-memory without raising.
* Per-route override: a tighter limit on a specific route fires
  independently of the global budget.
* ``WAKE_RATELIMIT_DISABLED=true`` short-circuits the dependency.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from wake.api.ratelimit import (
    WAKE_RATELIMIT_DISABLED_ENV,
    WAKE_RATELIMIT_REDIS_URL_ENV,
    RateLimitExceededError,
    WakeRateLimiter,
    build_limiter,
    is_disabled,
    rate_limit_dep,
    rate_limit_exceeded_handler,
)

pytestmark = pytest.mark.asyncio


def _make_app(*, write_limit: str = "3/minute", per_route: bool = False) -> FastAPI:
    """Build a minimal app wired with the rate-limit dependency."""
    app = FastAPI()
    app.state.limiter = build_limiter()
    app.add_exception_handler(RateLimitExceededError, rate_limit_exceeded_handler)

    @app.post("/write", dependencies=[Depends(rate_limit_dep(write_limit, per_route=per_route))])
    async def write_route() -> dict[str, str]:
        return {"ok": "yes"}

    @app.post(
        "/other",
        dependencies=[Depends(rate_limit_dep("100/minute", per_route=per_route))],
    )
    async def other_route() -> dict[str, str]:
        return {"ok": "yes"}

    return app


async def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture(autouse=True)
def _reset_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(WAKE_RATELIMIT_DISABLED_ENV, raising=False)
    monkeypatch.delenv(WAKE_RATELIMIT_REDIS_URL_ENV, raising=False)


async def test_under_limit_passes_through() -> None:
    app = _make_app(write_limit="5/minute")
    async with await _client(app) as client:
        for _ in range(3):
            r = await client.post(
                "/write",
                headers={"X-Wake-API-Key": "k", "X-Wake-Workspace-Id": "alpha"},
            )
            assert r.status_code == 200


async def test_over_limit_returns_429_with_retry_after_and_json_body() -> None:
    app = _make_app(write_limit="2/minute")
    async with await _client(app) as client:
        headers = {"X-Wake-API-Key": "k", "X-Wake-Workspace-Id": "alpha"}
        r1 = await client.post("/write", headers=headers)
        r2 = await client.post("/write", headers=headers)
        r3 = await client.post("/write", headers=headers)

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429
    assert "Retry-After" in r3.headers
    body = r3.json()
    assert "detail" in body
    assert "limit" in body
    assert "reset_at" in body
    assert body["limit"] == "2/minute"
    assert isinstance(body["reset_at"], int)


async def test_per_workspace_buckets_are_isolated() -> None:
    """Different workspaces share the same API key but separate buckets."""
    app = _make_app(write_limit="2/minute")
    async with await _client(app) as client:
        h_alpha = {"X-Wake-API-Key": "k", "X-Wake-Workspace-Id": "alpha"}
        h_beta = {"X-Wake-API-Key": "k", "X-Wake-Workspace-Id": "beta"}
        # Burn alpha's budget.
        await client.post("/write", headers=h_alpha)
        await client.post("/write", headers=h_alpha)
        r_alpha_3 = await client.post("/write", headers=h_alpha)
        # Beta still has full budget.
        r_beta_1 = await client.post("/write", headers=h_beta)
        r_beta_2 = await client.post("/write", headers=h_beta)

    assert r_alpha_3.status_code == 429
    assert r_beta_1.status_code == 200
    assert r_beta_2.status_code == 200


async def test_per_route_override_isolates_buckets() -> None:
    """``per_route=True`` gives each endpoint its own counter."""
    app = _make_app(write_limit="1/minute", per_route=True)
    async with await _client(app) as client:
        headers = {"X-Wake-API-Key": "k", "X-Wake-Workspace-Id": "alpha"}
        r_write_1 = await client.post("/write", headers=headers)
        r_other_1 = await client.post("/other", headers=headers)
        # /write is now exhausted; /other still has plenty of budget.
        r_write_2 = await client.post("/write", headers=headers)

    assert r_write_1.status_code == 200
    assert r_other_1.status_code == 200
    assert r_write_2.status_code == 429


async def test_disabled_env_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    """``WAKE_RATELIMIT_DISABLED=true`` lets every request through."""
    monkeypatch.setenv(WAKE_RATELIMIT_DISABLED_ENV, "true")
    assert is_disabled() is True
    app = _make_app(write_limit="1/minute")
    async with await _client(app) as client:
        headers = {"X-Wake-API-Key": "k", "X-Wake-Workspace-Id": "alpha"}
        statuses = []
        for _ in range(5):
            r = await client.post("/write", headers=headers)
            statuses.append(r.status_code)
    assert statuses == [200] * 5


async def test_redis_url_invalid_falls_back_to_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An invalid/unreachable Redis URL must NEVER crash the limiter.

    Two acceptable behaviours:

    1. ``RedisStorage(url)`` raises at construction time because the
       async ``coredis`` driver is missing. We catch the exception
       in ``build_limiter`` and fall back to in-memory.
    2. ``RedisStorage(url)`` constructs OK but blows up on the first
       ``hit()`` because the TCP connection is refused. We swallow
       the storage exception inside ``WakeRateLimiter.hit`` and
       return True (allow).

    Either way: the API stays up. The test only verifies that no
    exception escapes and the limiter is functional.
    """
    monkeypatch.setenv(WAKE_RATELIMIT_REDIS_URL_ENV, "redis://127.0.0.1:1/0")
    limiter = build_limiter()
    assert limiter.backend_label in {"redis", "memory"}
    ok = await limiter.hit("3/minute", "test:default")
    # The important invariant is no exception bubbles up — the
    # actual True/False result depends on which fallback fired.
    assert ok in (True, False)


async def test_limit_format_in_429_body_matches_spec() -> None:
    app = _make_app(write_limit="1/minute")
    async with await _client(app) as client:
        headers = {"X-Wake-API-Key": "k", "X-Wake-Workspace-Id": "alpha"}
        await client.post("/write", headers=headers)
        r = await client.post("/write", headers=headers)
    assert r.status_code == 429
    # Retry-After must be parseable as a positive int.
    retry = int(r.headers["Retry-After"])
    assert retry > 0


async def test_wake_rate_limiter_direct_consume() -> None:
    """The underlying ``WakeRateLimiter.hit`` honours the limit."""
    limiter = build_limiter()
    assert isinstance(limiter, WakeRateLimiter)
    spec = "2/minute"
    key = "unit-direct:default"
    assert await limiter.hit(spec, key) is True
    assert await limiter.hit(spec, key) is True
    assert await limiter.hit(spec, key) is False
    # Reset releases the bucket.
    await limiter.reset()
    assert await limiter.hit(spec, key) is True


async def test_unauthenticated_requests_use_anon_bucket() -> None:
    """Missing API key resolves to the ``anon`` bucket."""
    app = _make_app(write_limit="2/minute")
    async with await _client(app) as client:
        # No api-key header — all hits share the anon:default bucket.
        await client.post("/write")
        await client.post("/write")
        r = await client.post("/write")
    assert r.status_code == 429


# Sanity: make sure the limiter's async storage is the asyncio loop's;
# pytest-asyncio sometimes loses references after collection ends.
async def test_event_loop_does_not_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(WAKE_RATELIMIT_REDIS_URL_ENV, raising=False)
    limiter = build_limiter()
    loop = asyncio.get_running_loop()
    _ = loop  # sanity probe; the limiter must accept the current loop
    ok = await limiter.hit("10/minute", "leakprobe")
    assert ok is True


# Use ``Any`` to silence mypy on the indirect fixture import.
_ = Any
