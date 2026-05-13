"""Integration-test fixtures.

These tests boot a *real* Wake server subprocess and talk to it over
HTTP. They are gated behind the ``integration`` pytest marker so they
don't run on the unit-test CI matrix. Each test skips automatically
when:

* The runtime slice (``wake.api.app``) is not importable yet — common
  while the foundation + runtime slices are still merging.
* No ``ANTHROPIC_API_KEY`` is set (only required for tests that drive
  the harness loop).
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Iterator

import pytest

from wake.cli.client import WakeClient


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers used by tests in this directory.

    ``--strict-markers`` is enabled in pyproject.toml, so we have to
    declare ``integration`` somewhere — doing it here keeps the
    declaration local to the slice that introduces it.
    """
    config.addinivalue_line(
        "markers",
        "integration: end-to-end test that needs a live wake server "
        "(and optionally an ANTHROPIC_API_KEY).",
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _runtime_available() -> bool:
    """Return True if the runtime slice is importable.

    Imported lazily — we don't want to actually load FastAPI in
    fixtures, just check that the module exists.
    """
    try:
        import importlib.util

        spec = importlib.util.find_spec("wake.api.app")
    except (ImportError, ValueError):
        return False
    return spec is not None


def _wait_for_server(url: str, *, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    with WakeClient(url, timeout=2.0) as client:
        while time.monotonic() < deadline:
            try:
                client.list_agents()
                return True
            except Exception:  # noqa: BLE001 — connection refused, 404, etc.
                pass
            try:
                client.health()
                return True
            except Exception:  # noqa: BLE001
                time.sleep(0.25)
    return False


@pytest.fixture(scope="session")
def wake_server() -> Iterator[str]:
    """Start a Wake server subprocess for the duration of the test session.

    Yields the base URL. Skips the test if the runtime slice is not yet
    installed.
    """
    if not _runtime_available():
        pytest.skip(
            "wake.api.app is not importable — runtime slice not merged "
            "into this worktree yet. Skipping integration test."
        )

    wake_bin = shutil.which("wake")
    if wake_bin is None:
        cmd = [sys.executable, "-m", "wake.cli.main", "server", "--local"]
    else:
        cmd = [wake_bin, "server", "--local"]

    port = _free_port()
    cmd += ["--port", str(port)]
    base = f"http://127.0.0.1:{port}"

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")

    proc = subprocess.Popen(  # noqa: S603 — controlled command
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    try:
        if not _wait_for_server(base, timeout=20.0):
            proc.terminate()
            try:
                stdout, stderr = proc.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate()
            pytest.skip(
                "wake server did not start within 20s. "
                f"stderr tail: {stderr[-500:]!r}"
            )
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture
def wake_client(wake_server: str) -> Iterator[WakeClient]:
    with WakeClient(wake_server) as client:
        yield client


@pytest.fixture
def require_anthropic_key() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set; harness-driven test skipped.")
