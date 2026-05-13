"""Tests for :mod:`wake_sandbox_runtime.selector` graceful fallback."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from wake.sandbox.base import SandboxAdapter

from wake_sandbox_runtime.adapter import SandboxRuntimeAdapter
from wake_sandbox_runtime.platform_detect import (
    PlatformProfile,
    SandboxUnavailableError,
)
from wake_sandbox_runtime.selector import select_sandbox_backend
from wake_sandbox_runtime.subprocess_runner import SubprocessResult, SubprocessRunner


class _FakeDocker(SandboxAdapter):
    """Drop-in stand-in for DockerSandbox used as the fallback target."""

    async def provision(self, env: Any) -> Any:  # noqa: D401, ARG002
        ...

    async def execute(self, handle: Any, tool_name: str, input: Any) -> Any:  # noqa: A002, ARG002
        ...

    async def destroy(self, handle: Any) -> None:  # noqa: ARG002
        ...


def _runner_that_says(version_exit: int) -> SubprocessRunner:
    runner = SubprocessRunner("sandbox-runtime")

    async def _stub(
        argv: list[str],
        *,
        config_json: dict[str, Any] | None = None,
        input_text: str | None = None,
        timeout_seconds: float | None = None,
    ) -> SubprocessResult:
        del config_json, input_text, timeout_seconds
        if argv == ["--version"]:
            return SubprocessResult(version_exit, "srt 0.1\n", "", False)
        return SubprocessResult(0, "", "", False)

    runner.run = AsyncMock(side_effect=_stub)  # type: ignore[method-assign]
    return runner


async def test_returns_sandbox_runtime_when_available(
    linux_profile: PlatformProfile,
) -> None:
    runner = _runner_that_says(version_exit=0)
    with patch(
        "wake_sandbox_runtime.selector.detect_platform",
        return_value=linux_profile,
    ):
        backend = await select_sandbox_backend(runner=runner)
    assert isinstance(backend, SandboxRuntimeAdapter)


async def test_falls_back_to_docker_when_cli_missing(
    linux_profile: PlatformProfile,
) -> None:
    runner = _runner_that_says(version_exit=127)  # cli error
    with patch(
        "wake_sandbox_runtime.selector.detect_platform",
        return_value=linux_profile,
    ):
        backend = await select_sandbox_backend(runner=runner, docker_factory=_FakeDocker)
    assert isinstance(backend, _FakeDocker)


async def test_falls_back_to_docker_on_unsupported_platform() -> None:
    runner = _runner_that_says(version_exit=0)
    with patch(
        "wake_sandbox_runtime.selector.detect_platform",
        side_effect=SandboxUnavailableError("Windows"),
    ):
        backend = await select_sandbox_backend(runner=runner, docker_factory=_FakeDocker)
    assert isinstance(backend, _FakeDocker)


async def test_strict_refuses_fallback(linux_profile: PlatformProfile) -> None:
    runner = _runner_that_says(version_exit=127)
    with (
        patch(
            "wake_sandbox_runtime.selector.detect_platform",
            return_value=linux_profile,
        ),
        pytest.raises(SandboxUnavailableError, match="strict"),
    ):
        await select_sandbox_backend(runner=runner, strict=True, docker_factory=_FakeDocker)


async def test_no_backend_available_raises() -> None:
    runner = _runner_that_says(version_exit=127)

    def _broken_docker() -> SandboxAdapter:
        raise RuntimeError("daemon down")

    with (
        patch(
            "wake_sandbox_runtime.selector.detect_platform",
            side_effect=SandboxUnavailableError("Windows"),
        ),
        pytest.raises(SandboxUnavailableError, match="No sandbox backend"),
    ):
        await select_sandbox_backend(
            runner=runner,
            docker_factory=_broken_docker,  # type: ignore[arg-type]
        )


async def test_prefer_docker_skips_srt_probe() -> None:
    """When ``prefer='docker'``, the selector should never touch srt."""
    runner = _runner_that_says(version_exit=0)
    backend = await select_sandbox_backend(
        prefer="docker", runner=runner, docker_factory=_FakeDocker
    )
    assert isinstance(backend, _FakeDocker)
    # Runner.run should NOT have been called for --version.
    calls = runner.run.await_args_list  # type: ignore[attr-defined]
    assert all(c.args[0] != ["--version"] for c in calls)


async def test_proxy_url_propagated_to_adapter(
    linux_profile: PlatformProfile,
) -> None:
    runner = _runner_that_says(version_exit=0)
    with patch(
        "wake_sandbox_runtime.selector.detect_platform",
        return_value=linux_profile,
    ):
        backend = await select_sandbox_backend(
            runner=runner,
            proxy_url="http://gw:8888",
        )
    assert isinstance(backend, SandboxRuntimeAdapter)
    assert backend._proxy_url == "http://gw:8888"  # type: ignore[attr-defined]
