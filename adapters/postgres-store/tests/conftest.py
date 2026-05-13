"""Shared fixtures for the postgres-store test suite.

Strategy: every test that needs a database receives a fresh
``PostgresStore`` bundle backed by a testcontainers-spun Postgres 16
instance. The container is reused across the whole module (one boot
per pytest module) and each test gets its own schema by truncating
the four tables at function scope — much faster than restarting the
container per test.

If Docker is unavailable the fixtures emit a ``pytest.skip`` so the
suite still runs in CI environments without a daemon.

The fixtures here are intentionally function-scoped where data isolation
matters and module-scoped where boot time dominates.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
import pytest_asyncio

# ``testcontainers`` import is gated so missing-Docker environments
# don't cause collection errors.
try:
    from testcontainers.postgres import PostgresContainer  # type: ignore[import-not-found]

    _HAVE_TESTCONTAINERS = True
except Exception:  # noqa: BLE001
    PostgresContainer = None  # type: ignore[misc,assignment]
    _HAVE_TESTCONTAINERS = False


def pytest_addoption(parser: Any) -> None:
    parser.addoption(
        "--run-load",
        action="store_true",
        default=False,
        help="Run opt-in load tests (the load/ suite). Requires Docker.",
    )


def pytest_collection_modifyitems(config: Any, items: Any) -> None:
    if not config.getoption("--run-load"):
        skip_load = pytest.mark.skip(reason="load tests require --run-load")
        for item in items:
            if "load" in item.keywords:
                item.add_marker(skip_load)


def _docker_available() -> bool:
    """Probe whether a usable Docker daemon is reachable.

    Returns False if testcontainers is missing, if the user explicitly
    disabled testcontainers via env, or if the Docker daemon socket
    itself rejects a basic ping. We swallow any exception from the
    docker SDK — a False return is enough to flip every fixture into
    skip mode.
    """
    if not _HAVE_TESTCONTAINERS:
        return False
    if os.environ.get("WAKE_PG_SKIP_TESTCONTAINERS") == "1":
        return False
    try:
        import docker  # type: ignore[import-not-found]

        client = docker.from_env()
        client.ping()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[Any]:
    """Boot a single Postgres 16 container for the whole pytest session."""
    if not _docker_available():
        pytest.skip("Docker / testcontainers unavailable — skipping pg tests")
    container = PostgresContainer("postgres:16-alpine")
    try:
        container.start()
        yield container
    finally:
        with contextlib.suppress(Exception):
            container.stop()


@pytest.fixture(scope="session")
def postgres_dsn(postgres_container: Any) -> str:
    """SQLAlchemy DSN for the test container."""
    # testcontainers' default URL uses psycopg2; rewrite to asyncpg.
    raw = postgres_container.get_connection_url()  # e.g. postgresql+psycopg2://...
    if raw.startswith("postgresql+psycopg2://"):
        return "postgresql+asyncpg://" + raw[len("postgresql+psycopg2://") :]
    if raw.startswith("postgresql+psycopg://"):
        return "postgresql+asyncpg://" + raw[len("postgresql+psycopg://") :]
    if raw.startswith("postgresql://"):
        return "postgresql+asyncpg://" + raw[len("postgresql://") :]
    return raw


@pytest_asyncio.fixture
async def store(postgres_dsn: str) -> AsyncIterator[Any]:
    """Yield a fresh ``PostgresStore`` with schema migrated to head.

    Tables are TRUNCATEd between tests so the schema migration cost
    (Alembic + index creation) is paid once per session.
    """
    from sqlalchemy import text

    from wake_store_postgres import PostgresStore

    s = PostgresStore(postgres_dsn)
    await s.initialize()
    # TRUNCATE all four tables (events partitions cascade automatically
    # via the parent). CASCADE clears any FK dependents.
    async with s.engine.begin() as conn:
        await conn.execute(
            text(
                """
                TRUNCATE TABLE events, sessions, agent_versions, agents,
                               environments
                RESTART IDENTITY CASCADE
                """
            )
        )
    try:
        yield s
    finally:
        await s.close()
