"""Tests for the Docker sandbox adapter.

Docker daemon is mocked; we only verify that the adapter's plumbing is right.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from wake.sandbox.base import SandboxAdapter, SandboxProvisionError
from wake.sandbox.docker import DockerSandbox
from wake.types import EnvironmentConfig, SandboxHandle


def _env() -> EnvironmentConfig:
    return EnvironmentConfig(
        id="env_1",
        name="test",
        config={"image": "python:3.12-slim"},
        created_at=datetime.now(timezone.utc),
    )


def _handle(cid: str = "container1", ws: str = "/workspace") -> SandboxHandle:
    return SandboxHandle(
        backend="docker",
        container_id=cid,
        workspace_path=ws,
        created_at=datetime.now(timezone.utc),
    )


class _FakeExecResult:
    def __init__(self, exit_code: int, output: bytes) -> None:
        self.exit_code = exit_code
        self.output = output


class _FakeContainer:
    def __init__(self) -> None:
        self.id = "container1"
        self.removed = False
        self._files: dict[str, bytes] = {}

    def exec_run(self, *args: Any, **kwargs: Any) -> _FakeExecResult:
        cmd = args[0] if args else kwargs.get("cmd")
        if isinstance(cmd, list):
            cmd_str = " ".join(cmd)
        else:
            cmd_str = str(cmd)
        if "mkdir" in cmd_str:
            return _FakeExecResult(0, b"")
        if "cat " in cmd_str:
            path = cmd_str.split("cat ", 1)[1].strip().strip("'").strip('"')
            data = self._files.get(path, None)
            if data is None:
                return _FakeExecResult(1, b"No such file or directory")
            return _FakeExecResult(0, data)
        if cmd_str.startswith("/bin/sh") or "-lc" in cmd_str:
            inner = args[0][-1] if isinstance(args[0], list) else cmd_str
            if "false" in inner:
                return _FakeExecResult(1, b"fail")
            return _FakeExecResult(0, b"hello\n")
        return _FakeExecResult(0, b"")

    def put_archive(self, path: str, data: bytes) -> bool:
        # Decode the tar to store contents
        import io
        import tarfile

        buf = io.BytesIO(data)
        try:
            with tarfile.open(fileobj=buf, mode="r") as tf:
                for member in tf.getmembers():
                    f = tf.extractfile(member)
                    if f is not None:
                        self._files[member.name] = f.read()
        except Exception:  # noqa: BLE001
            return False
        return True

    def remove(self, force: bool = False) -> None:
        self.removed = True


class _FakeContainers:
    def __init__(self) -> None:
        self.last: _FakeContainer | None = None

    def run(self, **kwargs: Any) -> _FakeContainer:
        c = _FakeContainer()
        self.last = c
        return c

    def get(self, container_id: str) -> _FakeContainer:
        if self.last is None or self.last.removed:
            raise RuntimeError("no such container")
        return self.last


class _FakeDockerClient:
    def __init__(self) -> None:
        self.containers = _FakeContainers()


@pytest.fixture
def fake_client() -> _FakeDockerClient:
    return _FakeDockerClient()


@pytest.fixture
def sandbox(fake_client: _FakeDockerClient) -> DockerSandbox:
    return DockerSandbox(client=fake_client)


@pytest.mark.asyncio
async def test_provision_returns_handle(sandbox: DockerSandbox, fake_client: _FakeDockerClient) -> None:
    handle = await sandbox.provision(_env())
    assert handle.backend == "docker"
    assert handle.container_id == "container1"
    assert handle.workspace_path == "/workspace"
    assert fake_client.containers.last is not None


@pytest.mark.asyncio
async def test_provision_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeDockerClient()

    def _raise(**kwargs: Any) -> Any:
        raise RuntimeError("docker is down")

    client.containers.run = _raise  # type: ignore[assignment]
    sb = DockerSandbox(client=client)
    with pytest.raises(SandboxProvisionError):
        await sb.provision(_env())


@pytest.mark.asyncio
async def test_execute_bash(sandbox: DockerSandbox) -> None:
    h = await sandbox.provision(_env())
    res = await sandbox.execute(h, "bash", {"command": "echo hello"})
    assert not res.is_error
    assert "hello" in res.content[0].text


@pytest.mark.asyncio
async def test_execute_bash_failure(sandbox: DockerSandbox) -> None:
    h = await sandbox.provision(_env())
    res = await sandbox.execute(h, "bash", {"command": "false"})
    assert res.is_error


@pytest.mark.asyncio
async def test_execute_bash_invalid_input(sandbox: DockerSandbox) -> None:
    h = await sandbox.provision(_env())
    res = await sandbox.execute(h, "bash", {"command": ""})
    assert res.is_error
    assert res.error_code == "invalid_tool_input"


@pytest.mark.asyncio
async def test_execute_unknown_tool(sandbox: DockerSandbox) -> None:
    h = await sandbox.provision(_env())
    res = await sandbox.execute(h, "made_up_tool", {})
    assert res.is_error
    assert res.error_code == "not_found"


@pytest.mark.asyncio
async def test_file_write_then_read(sandbox: DockerSandbox) -> None:
    h = await sandbox.provision(_env())
    w = await sandbox.execute(h, "file_write", {"path": "foo.txt", "content": "bar"})
    assert not w.is_error
    r = await sandbox.execute(h, "file_read", {"path": "foo.txt"})
    assert not r.is_error
    assert "bar" in r.content[0].text


@pytest.mark.asyncio
async def test_file_read_missing(sandbox: DockerSandbox) -> None:
    h = await sandbox.provision(_env())
    r = await sandbox.execute(h, "file_read", {"path": "missing.txt"})
    assert r.is_error
    assert r.error_code == "not_found"


@pytest.mark.asyncio
async def test_file_write_invalid_path(sandbox: DockerSandbox) -> None:
    h = await sandbox.provision(_env())
    r = await sandbox.execute(h, "file_write", {"path": "", "content": "x"})
    assert r.is_error


@pytest.mark.asyncio
async def test_file_edit(sandbox: DockerSandbox) -> None:
    h = await sandbox.provision(_env())
    await sandbox.execute(h, "file_write", {"path": "x.txt", "content": "hello world"})
    r = await sandbox.execute(
        h, "file_edit", {"path": "x.txt", "old_string": "world", "new_string": "wake"}
    )
    assert not r.is_error
    read = await sandbox.execute(h, "file_read", {"path": "x.txt"})
    assert "hello wake" in read.content[0].text


@pytest.mark.asyncio
async def test_file_edit_string_not_found(sandbox: DockerSandbox) -> None:
    h = await sandbox.provision(_env())
    await sandbox.execute(h, "file_write", {"path": "x.txt", "content": "hello"})
    r = await sandbox.execute(
        h, "file_edit", {"path": "x.txt", "old_string": "nope", "new_string": "x"}
    )
    assert r.is_error
    assert r.error_code == "string_not_found"


@pytest.mark.asyncio
async def test_file_edit_ambiguous_without_replace_all(sandbox: DockerSandbox) -> None:
    h = await sandbox.provision(_env())
    await sandbox.execute(h, "file_write", {"path": "x.txt", "content": "a a"})
    r = await sandbox.execute(
        h, "file_edit", {"path": "x.txt", "old_string": "a", "new_string": "b"}
    )
    assert r.is_error
    assert r.error_code == "invalid_tool_input"


@pytest.mark.asyncio
async def test_file_edit_replace_all(sandbox: DockerSandbox) -> None:
    h = await sandbox.provision(_env())
    await sandbox.execute(h, "file_write", {"path": "x.txt", "content": "a a"})
    r = await sandbox.execute(
        h,
        "file_edit",
        {"path": "x.txt", "old_string": "a", "new_string": "b", "replace_all": True},
    )
    assert not r.is_error
    read = await sandbox.execute(h, "file_read", {"path": "x.txt"})
    assert read.content[0].text == "b b"


@pytest.mark.asyncio
async def test_destroy(sandbox: DockerSandbox, fake_client: _FakeDockerClient) -> None:
    h = await sandbox.provision(_env())
    await sandbox.destroy(h)
    assert fake_client.containers.last is not None
    assert fake_client.containers.last.removed


@pytest.mark.asyncio
async def test_execute_after_destroy_returns_error(
    sandbox: DockerSandbox, fake_client: _FakeDockerClient
) -> None:
    h = await sandbox.provision(_env())
    await sandbox.destroy(h)
    res = await sandbox.execute(h, "bash", {"command": "echo x"})
    assert res.is_error
    assert res.error_code == "container_expired"


@pytest.mark.asyncio
async def test_implements_adapter_abc() -> None:
    sb = DockerSandbox(client=_FakeDockerClient())
    assert isinstance(sb, SandboxAdapter)
