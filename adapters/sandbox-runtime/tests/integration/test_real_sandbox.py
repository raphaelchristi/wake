"""Opt-in integration test against the real srt CLI.

Skipped unless ``sandbox-runtime`` is on PATH. Validates that the mandatory
deny paths are honored by the actual sandbox: a ``cat ~/.ssh/id_rsa`` from
inside the sandbox must fail.

Run via::

    pytest adapters/sandbox-runtime/tests/integration -m integration

(The package's :file:`pyproject.toml` declares the ``integration`` marker.)
"""

from __future__ import annotations

import asyncio
import shutil
from datetime import UTC, datetime

import pytest
from wake.types import EnvironmentConfig

from wake_sandbox_runtime.adapter import SandboxRuntimeAdapter
from wake_sandbox_runtime.platform_detect import (
    SandboxUnavailableError,
    detect_platform,
)

pytestmark = pytest.mark.integration


def _srt_available() -> bool:
    if shutil.which("sandbox-runtime") is None:
        return False
    try:
        detect_platform()
    except SandboxUnavailableError:
        return False
    return True


@pytest.mark.skipif(not _srt_available(), reason="sandbox-runtime CLI not on PATH")
async def test_real_sandbox_denies_ssh_key_access() -> None:
    adapter = SandboxRuntimeAdapter()
    env = EnvironmentConfig(
        id="env_integration",
        name="integration",
        config={
            "workspace": "/tmp/wake-sandbox-int",
            "network_mode": "none",
        },
        created_at=datetime.now(UTC),
    )

    handle = await adapter.provision(env)
    try:
        # Try to read the operator's SSH key. Mandatory deny must block this
        # even if the host file exists.
        result = await adapter.execute(
            handle,
            "bash",
            {"command": "cat ~/.ssh/id_rsa || echo DENIED"},
        )
    finally:
        await adapter.destroy(handle)

    text = "".join(b.text for b in result.content)
    assert "DENIED" in text or result.is_error, (
        f"sandbox-runtime should deny ~/.ssh access; got is_error={result.is_error}, text={text!r}"
    )


@pytest.mark.skipif(not _srt_available(), reason="sandbox-runtime CLI not on PATH")
async def test_real_sandbox_basic_echo() -> None:
    adapter = SandboxRuntimeAdapter()
    env = EnvironmentConfig(
        id="env_basic",
        name="basic",
        config={"workspace": "/tmp/wake-sandbox-int"},
        created_at=datetime.now(UTC),
    )
    handle = await adapter.provision(env)
    try:
        await asyncio.sleep(0)  # let event loop settle
        result = await adapter.execute(handle, "bash", {"command": "echo hello"})
    finally:
        await adapter.destroy(handle)
    assert not result.is_error
    assert "hello" in result.content[0].text
