# ruff: noqa: TC001, TC002
"""Tests for :mod:`wake_sandbox_runtime.adapter` with subprocess mocked.

Every test uses ``mock_runner_factory`` from ``conftest.py`` — never the real
srt CLI. The adapter is exercised end-to-end through its
:class:`SandboxAdapter` ABC surface to guarantee isinstance compatibility.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from wake.sandbox.base import SandboxAdapter, SandboxProvisionError
from wake.types import EnvironmentConfig

from wake_sandbox_runtime.adapter import BACKEND_NAME, SandboxRuntimeAdapter
from wake_sandbox_runtime.platform_detect import PlatformProfile
from wake_sandbox_runtime.subprocess_runner import SubprocessResult, SubprocessRunner

RunnerFactory = Callable[..., SubprocessRunner]


def test_adapter_is_sandbox_adapter(linux_profile: PlatformProfile) -> None:
    adapter = SandboxRuntimeAdapter(profile=linux_profile)
    assert isinstance(adapter, SandboxAdapter)


def test_create_factory_returns_adapter() -> None:
    from wake_sandbox_runtime.adapter import create

    instance = create()
    assert isinstance(instance, SandboxRuntimeAdapter)
    assert isinstance(instance, SandboxAdapter)


async def test_provision_returns_handle(
    linux_profile: PlatformProfile,
    env_config: EnvironmentConfig,
    mock_runner_factory: RunnerFactory,
) -> None:
    runner = mock_runner_factory(
        validate=SubprocessResult(0, "", "", False),
    )
    adapter = SandboxRuntimeAdapter(runner=runner, profile=linux_profile)
    handle = await adapter.provision(env_config)
    assert handle.backend == BACKEND_NAME
    assert handle.container_id.startswith("srt_")
    assert handle.workspace_path == "/workspace"


async def test_provision_validates_spec_with_srt(
    linux_profile: PlatformProfile,
    env_config: EnvironmentConfig,
    mock_runner_factory: RunnerFactory,
) -> None:
    runner = mock_runner_factory(validate=SubprocessResult(0, "", "", False))
    adapter = SandboxRuntimeAdapter(runner=runner, profile=linux_profile)
    await adapter.provision(env_config)
    # Runner.run was called with ["validate", "--spec=-"]
    assert runner.run.await_count >= 1  # type: ignore[attr-defined]
    call = runner.run.await_args_list[0]  # type: ignore[attr-defined]
    assert call.args[0][0] == "validate"


async def test_provision_failure_raises_sandbox_provision_error(
    linux_profile: PlatformProfile,
    env_config: EnvironmentConfig,
    mock_runner_factory: RunnerFactory,
) -> None:
    runner = mock_runner_factory(
        validate=SubprocessResult(1, "", "spec invalid: bad workspace", False)
    )
    adapter = SandboxRuntimeAdapter(runner=runner, profile=linux_profile)
    with pytest.raises(SandboxProvisionError, match="spec invalid"):
        await adapter.provision(env_config)


async def test_execute_bash_success(
    linux_profile: PlatformProfile,
    env_config: EnvironmentConfig,
    mock_runner_factory: RunnerFactory,
) -> None:
    runner = mock_runner_factory(
        validate=SubprocessResult(0, "", "", False),
        run=SubprocessResult(0, "hello\n", "", False),
    )
    adapter = SandboxRuntimeAdapter(runner=runner, profile=linux_profile)
    handle = await adapter.provision(env_config)
    result = await adapter.execute(handle, "bash", {"command": "echo hello"})
    assert not result.is_error
    assert result.content[0].text.strip() == "hello"


async def test_execute_bash_nonzero_exit_marks_error(
    linux_profile: PlatformProfile,
    env_config: EnvironmentConfig,
    mock_runner_factory: RunnerFactory,
) -> None:
    runner = mock_runner_factory(
        validate=SubprocessResult(0, "", "", False),
        run=SubprocessResult(2, "boom", "stderr details", False),
    )
    adapter = SandboxRuntimeAdapter(runner=runner, profile=linux_profile)
    handle = await adapter.provision(env_config)
    result = await adapter.execute(handle, "bash", {"command": "false"})
    assert result.is_error
    assert "boom" in result.content[0].text or "stderr" in result.content[0].text


async def test_execute_bash_rejects_empty_command(
    linux_profile: PlatformProfile,
    env_config: EnvironmentConfig,
    mock_runner_factory: RunnerFactory,
) -> None:
    runner = mock_runner_factory(validate=SubprocessResult(0, "", "", False))
    adapter = SandboxRuntimeAdapter(runner=runner, profile=linux_profile)
    handle = await adapter.provision(env_config)
    result = await adapter.execute(handle, "bash", {"command": "   "})
    assert result.is_error
    assert result.error_code == "invalid_tool_input"


async def test_execute_unknown_tool(
    linux_profile: PlatformProfile,
    env_config: EnvironmentConfig,
    mock_runner_factory: RunnerFactory,
) -> None:
    runner = mock_runner_factory(validate=SubprocessResult(0, "", "", False))
    adapter = SandboxRuntimeAdapter(runner=runner, profile=linux_profile)
    handle = await adapter.provision(env_config)
    result = await adapter.execute(handle, "nonexistent", {})
    assert result.is_error
    assert result.error_code == "not_found"


async def test_execute_unknown_handle(
    linux_profile: PlatformProfile,
    env_config: EnvironmentConfig,
    mock_runner_factory: RunnerFactory,
) -> None:
    from datetime import UTC, datetime

    from wake.types import SandboxHandle

    runner = mock_runner_factory()
    adapter = SandboxRuntimeAdapter(runner=runner, profile=linux_profile)
    fake = SandboxHandle(
        backend=BACKEND_NAME,
        container_id="srt_unknown",
        workspace_path="/workspace",
        created_at=datetime.now(UTC),
    )
    result = await adapter.execute(fake, "bash", {"command": "echo x"})
    assert result.is_error
    assert result.error_code == "container_expired"


async def test_destroy_removes_handle(
    linux_profile: PlatformProfile,
    env_config: EnvironmentConfig,
    mock_runner_factory: RunnerFactory,
) -> None:
    runner = mock_runner_factory(validate=SubprocessResult(0, "", "", False))
    adapter = SandboxRuntimeAdapter(runner=runner, profile=linux_profile)
    handle = await adapter.provision(env_config)
    await adapter.destroy(handle)
    # After destroy, execute should fail with container_expired.
    result = await adapter.execute(handle, "bash", {"command": "echo x"})
    assert result.is_error
    assert result.error_code == "container_expired"


async def test_execute_file_write_then_read(
    linux_profile: PlatformProfile,
    env_config: EnvironmentConfig,
) -> None:
    """Round-trip: write a file, then read it. The runner serves both calls
    with a stateful stub so we can assert the actual flow."""
    from unittest.mock import AsyncMock

    state: dict[str, str] = {}
    runner = SubprocessRunner("sandbox-runtime")

    async def _stub(
        argv: list[str],
        *,
        config_json: dict[str, object] | None = None,
        input_text: str | None = None,
        timeout_seconds: float | None = None,
    ) -> SubprocessResult:
        del config_json, input_text, timeout_seconds
        if argv[0] == "validate":
            return SubprocessResult(0, "", "", False)
        # argv = ["run", "--spec=-", "--", "/bin/sh", "-lc", <cmd>]
        cmd = argv[5]
        if cmd.startswith("mkdir -p "):
            # Capture the path from the trailing > redirect.
            # heuristic: last token after `> ` (single quoted)
            tail = cmd.split("> ")[-1].strip()
            path = tail.strip("'\"")
            # Capture content from the base64 echo.
            # cmd format: "mkdir -p $(dirname X) && echo 'B64' | base64 -d > X"
            import base64

            quoted_b64 = cmd.split("echo ", 1)[1].split(" | base64", 1)[0]
            b64 = quoted_b64.strip("'\"")
            state[path] = base64.b64decode(b64).decode("utf-8")
            return SubprocessResult(0, "", "", False)
        if cmd.startswith("cat "):
            path = cmd[len("cat ") :].strip("'\"")
            return SubprocessResult(0, state.get(path, ""), "", False)
        return SubprocessResult(0, "", "", False)

    runner.run = AsyncMock(side_effect=_stub)  # type: ignore[method-assign]
    adapter = SandboxRuntimeAdapter(runner=runner, profile=linux_profile)
    handle = await adapter.provision(env_config)

    write = await adapter.execute(
        handle, "file_write", {"path": "/workspace/x.txt", "content": "hi\n"}
    )
    assert not write.is_error

    read = await adapter.execute(handle, "file_read", {"path": "/workspace/x.txt"})
    assert not read.is_error
    assert read.content[0].text == "hi\n"


async def test_file_edit_unique_replacement(
    linux_profile: PlatformProfile,
    env_config: EnvironmentConfig,
) -> None:
    """file_edit reads, modifies, re-writes."""
    from unittest.mock import AsyncMock

    state: dict[str, str] = {"/workspace/y.txt": "alpha beta gamma"}
    runner = SubprocessRunner("sandbox-runtime")

    async def _stub(
        argv: list[str],
        *,
        config_json: dict[str, object] | None = None,
        input_text: str | None = None,
        timeout_seconds: float | None = None,
    ) -> SubprocessResult:
        del config_json, input_text, timeout_seconds
        if argv[0] == "validate":
            return SubprocessResult(0, "", "", False)
        cmd = argv[5]
        if cmd.startswith("cat "):
            path = cmd[len("cat ") :].strip("'\"")
            return SubprocessResult(0, state.get(path, ""), "", False)
        if "base64 -d > " in cmd:
            import base64

            tail = cmd.split("> ")[-1].strip()
            path = tail.strip("'\"")
            quoted_b64 = cmd.split("echo ", 1)[1].split(" | base64", 1)[0]
            b64 = quoted_b64.strip("'\"")
            state[path] = base64.b64decode(b64).decode("utf-8")
            return SubprocessResult(0, "", "", False)
        return SubprocessResult(0, "", "", False)

    runner.run = AsyncMock(side_effect=_stub)  # type: ignore[method-assign]
    adapter = SandboxRuntimeAdapter(runner=runner, profile=linux_profile)
    handle = await adapter.provision(env_config)

    result = await adapter.execute(
        handle,
        "file_edit",
        {"path": "/workspace/y.txt", "old_string": "beta", "new_string": "BETA"},
    )
    assert not result.is_error
    assert state["/workspace/y.txt"] == "alpha BETA gamma"


async def test_file_edit_missing_old_string(
    linux_profile: PlatformProfile,
    env_config: EnvironmentConfig,
) -> None:
    from unittest.mock import AsyncMock

    runner = SubprocessRunner("sandbox-runtime")

    async def _stub(
        argv: list[str],
        *,
        config_json: dict[str, object] | None = None,
        input_text: str | None = None,
        timeout_seconds: float | None = None,
    ) -> SubprocessResult:
        del config_json, input_text, timeout_seconds
        if argv[0] == "validate":
            return SubprocessResult(0, "", "", False)
        cmd = argv[5]
        if cmd.startswith("cat "):
            return SubprocessResult(0, "hello world", "", False)
        return SubprocessResult(0, "", "", False)

    runner.run = AsyncMock(side_effect=_stub)  # type: ignore[method-assign]
    adapter = SandboxRuntimeAdapter(runner=runner, profile=linux_profile)
    handle = await adapter.provision(env_config)

    result = await adapter.execute(
        handle,
        "file_edit",
        {
            "path": "/workspace/y.txt",
            "old_string": "absent",
            "new_string": "x",
        },
    )
    assert result.is_error
    assert result.error_code == "string_not_found"


async def test_file_edit_duplicate_without_replace_all(
    linux_profile: PlatformProfile,
    env_config: EnvironmentConfig,
) -> None:
    from unittest.mock import AsyncMock

    runner = SubprocessRunner("sandbox-runtime")

    async def _stub(
        argv: list[str],
        *,
        config_json: dict[str, object] | None = None,
        input_text: str | None = None,
        timeout_seconds: float | None = None,
    ) -> SubprocessResult:
        del config_json, input_text, timeout_seconds
        if argv[0] == "validate":
            return SubprocessResult(0, "", "", False)
        cmd = argv[5]
        if cmd.startswith("cat "):
            return SubprocessResult(0, "foo foo bar", "", False)
        return SubprocessResult(0, "", "", False)

    runner.run = AsyncMock(side_effect=_stub)  # type: ignore[method-assign]
    adapter = SandboxRuntimeAdapter(runner=runner, profile=linux_profile)
    handle = await adapter.provision(env_config)

    result = await adapter.execute(
        handle,
        "file_edit",
        {"path": "/x", "old_string": "foo", "new_string": "FOO"},
    )
    assert result.is_error
    assert result.error_code == "invalid_tool_input"


async def test_provision_propagates_proxy_url_into_spec(
    linux_profile: PlatformProfile,
    env_proxied: EnvironmentConfig,
    mock_runner_factory: RunnerFactory,
) -> None:
    runner = mock_runner_factory(validate=SubprocessResult(0, "", "", False))
    adapter = SandboxRuntimeAdapter(
        runner=runner,
        profile=linux_profile,
        proxy_url="http://agentgateway:8888",
    )
    await adapter.provision(env_proxied)
    call = runner.run.await_args_list[0]  # type: ignore[attr-defined]
    spec = call.kwargs["config_json"]
    assert spec["env"]["HTTPS_PROXY"] == "http://agentgateway:8888"


async def test_provision_raises_on_unsupported_platform(
    env_config: EnvironmentConfig,
    mock_runner_factory: RunnerFactory,
) -> None:
    """Adapter constructed without a profile detects on first provision."""
    from unittest.mock import patch

    from wake_sandbox_runtime.platform_detect import SandboxUnavailableError

    runner = mock_runner_factory()
    adapter = SandboxRuntimeAdapter(runner=runner)
    with (
        patch(
            "wake_sandbox_runtime.adapter.detect_platform",
            side_effect=SandboxUnavailableError("nope"),
        ),
        pytest.raises(SandboxProvisionError, match="nope"),
    ):
        await adapter.provision(env_config)
