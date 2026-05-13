# ruff: noqa: A002, TC001, SIM105
"""Docker-backed sandbox.

Provisions a container per session. Runs tool calls inside it via `docker exec`.

Phase 1 scope: simple Docker, single host, no high-security isolation. This is
"namespace isolation," not a real sandbox — adequate for local dev and stated
as such. Higher-security backends (sandbox-runtime, gVisor, Firecracker) plug in
later via the same interface.
"""

from __future__ import annotations

import asyncio
import shlex
from datetime import UTC, datetime
from typing import Any

import structlog
from ulid import ULID

from wake.sandbox.base import SandboxAdapter, SandboxProvisionError
from wake.types import EnvironmentConfig, SandboxHandle, TextBlock, ToolResult

logger = structlog.get_logger(__name__)

DEFAULT_IMAGE = "python:3.12-slim"
DEFAULT_WORKSPACE = "/workspace"
DEFAULT_TIMEOUT_S = 60
MAX_OUTPUT_BYTES = 256 * 1024  # 256 KiB
BACKEND_NAME = "docker"


def _now() -> datetime:
    return datetime.now(UTC)


def _truncate(text: str, limit: int = MAX_OUTPUT_BYTES) -> tuple[str, bool]:
    raw = text.encode("utf-8", errors="replace")
    if len(raw) <= limit:
        return text, False
    return raw[:limit].decode("utf-8", errors="replace") + "\n... [truncated]", True


def _err(message: str, code: str) -> ToolResult:
    return ToolResult(
        content=[TextBlock(text=message)],
        is_error=True,
        error_code=code,
    )


class DockerSandbox(SandboxAdapter):
    """Docker-backed sandbox adapter.

    Uses the official `docker` Python SDK. Calls are wrapped in
    `asyncio.to_thread` since the SDK is synchronous.
    """

    def __init__(self, client: Any | None = None) -> None:
        # Defer import so that environments without docker can still import this module.
        if client is None:
            import docker  # type: ignore[import-untyped]

            self._client = docker.from_env()
        else:
            self._client = client

    async def provision(self, env: EnvironmentConfig) -> SandboxHandle:
        config = env.config or {}
        image = str(config.get("image", DEFAULT_IMAGE))
        workspace = str(config.get("workspace", DEFAULT_WORKSPACE))
        cpu_limit = config.get("cpu", 1)
        mem_limit = config.get("memory", "1g")
        network = config.get("network_mode", "none")  # default: no network
        cmd = config.get(
            "command",
            ["sleep", "infinity"],
        )

        name = f"wake_sb_{ULID()}".lower()

        def _run() -> Any:
            try:
                return self._client.containers.run(
                    image=image,
                    name=name,
                    command=cmd,
                    detach=True,
                    network_mode=network,
                    cpu_period=100000,
                    cpu_quota=int(100000 * float(cpu_limit)),
                    mem_limit=mem_limit,
                    working_dir=workspace,
                    labels={"wake.sandbox": "1", "wake.env": env.id},
                    auto_remove=False,
                )
            except Exception as e:  # noqa: BLE001
                raise SandboxProvisionError(f"failed to provision sandbox: {e}") from e

        container = await asyncio.to_thread(_run)
        logger.info(
            "sandbox_provisioned",
            container_id=container.id,
            image=image,
            workspace=workspace,
        )

        # Ensure workspace exists.
        try:
            await asyncio.to_thread(
                container.exec_run, f"mkdir -p {shlex.quote(workspace)}"
            )
        except Exception:  # noqa: BLE001
            logger.warning("workspace_mkdir_failed", container_id=container.id)

        return SandboxHandle(
            backend=BACKEND_NAME,
            container_id=container.id,
            workspace_path=workspace,
            created_at=_now(),
        )

    async def execute(
        self,
        handle: SandboxHandle,
        tool_name: str,
        input: dict[str, Any],
    ) -> ToolResult:
        try:
            container = await asyncio.to_thread(
                self._client.containers.get, handle.container_id
            )
        except Exception as e:  # noqa: BLE001
            return _err(f"container not found: {e}", "container_expired")

        match tool_name:
            case "bash":
                return await self._exec_bash(container, handle, input)
            case "file_read":
                return await self._exec_file_read(container, handle, input)
            case "file_write":
                return await self._exec_file_write(container, handle, input)
            case "file_edit":
                return await self._exec_file_edit(container, handle, input)
            case _:
                return _err(f"unknown sandboxed tool: {tool_name}", "not_found")

    async def destroy(self, handle: SandboxHandle) -> None:
        def _stop() -> None:
            try:
                container = self._client.containers.get(handle.container_id)
                container.remove(force=True)
            except Exception:  # noqa: BLE001
                logger.warning("sandbox_destroy_failed", container_id=handle.container_id)

        await asyncio.to_thread(_stop)
        logger.info("sandbox_destroyed", container_id=handle.container_id)

    # -- per-tool execution helpers -----------------------------------------

    async def _exec_bash(
        self, container: Any, handle: SandboxHandle, input: dict[str, Any]
    ) -> ToolResult:
        command = input.get("command")
        if not isinstance(command, str) or not command.strip():
            return _err("bash: 'command' is required and must be a non-empty string.", "invalid_tool_input")

        timeout_s = int(input.get("timeout_seconds", DEFAULT_TIMEOUT_S))

        def _run() -> tuple[int, bytes]:
            res = container.exec_run(
                ["/bin/sh", "-lc", command],
                workdir=handle.workspace_path,
                demux=False,
            )
            exit_code = getattr(res, "exit_code", None)
            if exit_code is None and isinstance(res, tuple):
                exit_code, output = res
                return int(exit_code or 0), output or b""
            return int(exit_code or 0), getattr(res, "output", b"") or b""

        try:
            exit_code, raw = await asyncio.wait_for(
                asyncio.to_thread(_run), timeout=timeout_s
            )
        except TimeoutError:
            return _err(
                f"bash: command exceeded {timeout_s}s timeout.",
                "execution_time_exceeded",
            )
        except Exception as e:  # noqa: BLE001
            return _err(f"bash: {e}", "unknown")

        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        text, truncated = _truncate(text)
        if exit_code != 0:
            return ToolResult(
                content=[TextBlock(text=text or f"(exit {exit_code})")],
                is_error=True,
                error_code="output_too_large" if truncated else "unknown",
            )
        return ToolResult(content=[TextBlock(text=text)], is_error=False)

    async def _exec_file_read(
        self, container: Any, handle: SandboxHandle, input: dict[str, Any]
    ) -> ToolResult:
        path = input.get("path")
        if not isinstance(path, str) or not path:
            return _err("file_read: 'path' is required.", "invalid_tool_input")

        start = input.get("start_line")
        end = input.get("end_line")

        # Use cat or sed depending on slicing.
        if isinstance(start, int) or isinstance(end, int):
            s = max(int(start or 1), 1)
            e = int(end) if isinstance(end, int) else 0
            if e:
                cmd = f"sed -n '{s},{e}p' {shlex.quote(path)}"
            else:
                cmd = f"sed -n '{s},$p' {shlex.quote(path)}"
        else:
            cmd = f"cat {shlex.quote(path)}"

        def _run() -> tuple[int, bytes]:
            res = container.exec_run(
                ["/bin/sh", "-lc", cmd], workdir=handle.workspace_path
            )
            return int(getattr(res, "exit_code", 0) or 0), getattr(res, "output", b"") or b""

        try:
            exit_code, raw = await asyncio.to_thread(_run)
        except Exception as e:  # noqa: BLE001
            return _err(f"file_read: {e}", "unknown")

        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        text, _ = _truncate(text)
        if exit_code != 0:
            code = "not_found" if "No such file" in text else "unknown"
            return _err(text or f"file_read failed (exit {exit_code})", code)
        return ToolResult(content=[TextBlock(text=text)], is_error=False)

    async def _exec_file_write(
        self, container: Any, handle: SandboxHandle, input: dict[str, Any]
    ) -> ToolResult:
        path = input.get("path")
        content = input.get("content")
        if not isinstance(path, str) or not path:
            return _err("file_write: 'path' is required.", "invalid_tool_input")
        if not isinstance(content, str):
            return _err("file_write: 'content' must be a string.", "invalid_tool_input")

        # Use a heredoc with a randomized delimiter; safer than echo for arbitrary content.
        import io
        import tarfile

        def _run() -> int:
            tar_buf = io.BytesIO()
            with tarfile.open(fileobj=tar_buf, mode="w") as tf:
                data = content.encode("utf-8")
                info = tarfile.TarInfo(name=path.lstrip("/"))
                info.size = len(data)
                info.mtime = int(_now().timestamp())
                tf.addfile(info, io.BytesIO(data))
            tar_buf.seek(0)
            ok = container.put_archive(handle.workspace_path, tar_buf.read())
            return 0 if ok else 1

        try:
            rc = await asyncio.to_thread(_run)
        except Exception as e:  # noqa: BLE001
            return _err(f"file_write: {e}", "unknown")

        if rc != 0:
            return _err("file_write: put_archive failed", "unknown")
        return ToolResult(content=[TextBlock(text=f"wrote {path}")], is_error=False)

    async def _exec_file_edit(
        self, container: Any, handle: SandboxHandle, input: dict[str, Any]
    ) -> ToolResult:
        path = input.get("path")
        old = input.get("old_string")
        new = input.get("new_string")
        replace_all = bool(input.get("replace_all", False))

        if not isinstance(path, str) or not path:
            return _err("file_edit: 'path' required.", "invalid_tool_input")
        if not isinstance(old, str) or not isinstance(new, str):
            return _err("file_edit: 'old_string' and 'new_string' required.", "invalid_tool_input")

        # Read current contents
        read = await self._exec_file_read(container, handle, {"path": path})
        if read.is_error:
            return read
        current = "".join(b.text for b in read.content)

        if old not in current:
            return _err("file_edit: old_string not found in file.", "string_not_found")

        if replace_all:
            updated = current.replace(old, new)
        else:
            if current.count(old) > 1:
                return _err(
                    "file_edit: old_string appears more than once; use replace_all=true or disambiguate.",
                    "invalid_tool_input",
                )
            updated = current.replace(old, new, 1)

        return await self._exec_file_write(
            container, handle, {"path": path, "content": updated}
        )
