# ruff: noqa: TC003
"""Test fixtures for wake-sandbox-runtime.

The package never invokes the real srt CLI in unit tests — we mock the
:class:`SubprocessRunner` seam instead. These fixtures provide the
canonical mocks plus a deterministic :class:`EnvironmentConfig`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from wake.types import EnvironmentConfig

from wake_sandbox_runtime.platform_detect import PlatformProfile
from wake_sandbox_runtime.subprocess_runner import SubprocessResult, SubprocessRunner


@pytest.fixture
def linux_profile() -> PlatformProfile:
    return PlatformProfile(
        name="linux-bwrap",
        system="Linux",
        backend_binary="/usr/bin/bwrap",
        notes="test fixture",
    )


@pytest.fixture
def macos_profile() -> PlatformProfile:
    return PlatformProfile(
        name="macos-sandbox-exec",
        system="Darwin",
        backend_binary=None,
        notes="test fixture",
    )


@pytest.fixture
def env_config() -> EnvironmentConfig:
    return EnvironmentConfig(
        id="env_test",
        name="test-env",
        config={
            "workspace": "/workspace",
            "network_mode": "none",
            "read_allow": ["/tmp/data"],
            "write_allow": ["/workspace"],
            "env": {"PYTHONUNBUFFERED": "1"},
        },
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def env_proxied() -> EnvironmentConfig:
    return EnvironmentConfig(
        id="env_proxied",
        name="proxied-env",
        config={
            "workspace": "/workspace",
            "network_mode": "proxied",
        },
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_runner_factory() -> Callable[..., SubprocessRunner]:
    """Build a :class:`SubprocessRunner` whose :meth:`run` returns scripted
    outcomes per-argv-prefix.

    Usage::

        runner = mock_runner_factory(
            validate=SubprocessResult(0, "", "", False),
            run=SubprocessResult(0, "hello", "", False),
            version=SubprocessResult(0, "srt 0.1\\n", "", False),
        )
    """

    def _factory(
        *,
        validate: SubprocessResult | None = None,
        run: SubprocessResult | None = None,
        version: SubprocessResult | None = None,
        binary: str = "sandbox-runtime",
    ) -> SubprocessRunner:
        runner = SubprocessRunner(binary)

        async def _stub(
            argv: list[str],
            *,
            config_json: dict[str, Any] | None = None,
            input_text: str | None = None,
            timeout_seconds: float | None = None,
        ) -> SubprocessResult:
            del config_json, input_text, timeout_seconds
            if argv[:1] == ["validate"] and validate is not None:
                return validate
            if argv[:1] == ["run"] and run is not None:
                return run
            if argv[:1] == ["--version"] and version is not None:
                return version
            return SubprocessResult(0, "", "", False)

        runner.run = AsyncMock(side_effect=_stub)  # type: ignore[method-assign]
        return runner

    return _factory
