"""SandboxRuntimeAdapter — Wake :class:`SandboxAdapter` over the srt CLI.

Tool mapping (Phase 1 ABI):

- ``bash`` → ``srt run --spec=- -- /bin/sh -lc "<command>"``
- ``file_read`` → ``srt run`` wrapping ``cat`` / ``sed -n`` (matches
  :class:`wake.sandbox.docker.DockerSandbox` semantics)
- ``file_write`` → ``srt run`` wrapping a heredoc-style write
- ``file_edit`` → composed read + write, identical to the Docker reference

Every invocation re-loads the per-session spec from
:func:`wake_sandbox_runtime.config.build_srt_config` and pipes it on stdin.
The session has no long-running daemon; "provisioning" just validates that
srt accepts the spec and records a :class:`SandboxHandle` we can use to
correlate subsequent ``execute`` calls.
"""

from __future__ import annotations

import shlex
from datetime import UTC, datetime
from typing import Any

import structlog
from ulid import ULID
from wake.sandbox.base import SandboxAdapter, SandboxProvisionError
from wake.types import EnvironmentConfig, SandboxHandle, TextBlock, ToolResult

from wake_sandbox_runtime.config import (
    DEFAULT_WORKSPACE,
    MANDATORY_DENY_PATHS,
    build_srt_config,
)
from wake_sandbox_runtime.platform_detect import (
    PlatformProfile,
    SandboxUnavailableError,
    detect_platform,
)
from wake_sandbox_runtime.subprocess_runner import (
    SandboxRuntimeError,
    SubprocessRunner,
)

logger = structlog.get_logger(__name__)

BACKEND_NAME = "sandbox-runtime"
DEFAULT_TIMEOUT_S = 60


def _now() -> datetime:
    return datetime.now(UTC)


def _err(message: str, code: str) -> ToolResult:
    return ToolResult(
        content=[TextBlock(text=message)],
        is_error=True,
        error_code=code,
    )


def _ok(text: str) -> ToolResult:
    return ToolResult(content=[TextBlock(text=text)], is_error=False)


class SandboxRuntimeAdapter(SandboxAdapter):  # type: ignore[misc]
    """Wrap @anthropic-ai/sandbox-runtime as a Wake :class:`SandboxAdapter`.

    Args:
        srt_binary: CLI name or path. Defaults to ``"sandbox-runtime"``.
        runner: Inject a pre-built :class:`SubprocessRunner` (tests use this
            to mock the subprocess seam). When provided, ``srt_binary`` is
            ignored.
        profile: Override platform detection. Production callers should
            leave this ``None``.
        proxy_url: Endpoint passed to :func:`build_srt_config` when an
            :class:`EnvironmentConfig` requests ``network_mode="proxied"``.
            Typically points at the agentgateway sidecar.
    """

    def __init__(
        self,
        srt_binary: str = "sandbox-runtime",
        *,
        runner: SubprocessRunner | None = None,
        profile: PlatformProfile | None = None,
        proxy_url: str | None = None,
    ) -> None:
        self._runner = runner if runner is not None else SubprocessRunner(srt_binary)
        self._profile = profile  # lazy-detect on first provision
        self._proxy_url = proxy_url
        # session_id → JSON spec, so execute() can rebuild the per-call command.
        self._specs: dict[str, dict[str, Any]] = {}

    # -- ABC surface --------------------------------------------------------

    async def provision(self, env: EnvironmentConfig) -> SandboxHandle:
        profile = self._ensure_profile()
        spec = build_srt_config(env, profile=profile, proxy_url=self._proxy_url)

        # Sanity-check the spec via `srt validate`. Many CLIs use slightly
        # different subcommand names — we try `validate`, then fall back to a
        # dry `init` if `validate` exits 64 (EX_USAGE). Both must accept the
        # spec on stdin via `--spec=-`.
        await self._validate_spec(spec)

        handle_id = f"srt_{ULID()}".lower()
        self._specs[handle_id] = spec

        workspace = str(spec.get("workspace") or DEFAULT_WORKSPACE)
        logger.info(
            "sandbox_runtime_provisioned",
            handle_id=handle_id,
            profile=profile.name,
            workspace=workspace,
            network_mode=spec.get("network", {}).get("mode"),
        )

        return SandboxHandle(
            backend=BACKEND_NAME,
            container_id=handle_id,
            workspace_path=workspace,
            created_at=_now(),
        )

    async def execute(
        self,
        handle: SandboxHandle,
        tool_name: str,
        input: dict[str, Any],  # noqa: A002 — matches ABC signature
    ) -> ToolResult:
        spec = self._specs.get(handle.container_id)
        if spec is None:
            return _err(
                f"sandbox handle not found: {handle.container_id}",
                "container_expired",
            )

        match tool_name:
            case "bash":
                return await self._exec_bash(handle, spec, input)
            case "file_read":
                return await self._exec_file_read(handle, spec, input)
            case "file_write":
                return await self._exec_file_write(handle, spec, input)
            case "file_edit":
                return await self._exec_file_edit(handle, spec, input)
            case _:
                return _err(f"unknown sandboxed tool: {tool_name}", "not_found")

    async def destroy(self, handle: SandboxHandle) -> None:
        self._specs.pop(handle.container_id, None)
        logger.info("sandbox_runtime_destroyed", handle_id=handle.container_id)

    # -- helpers ------------------------------------------------------------

    def _ensure_profile(self) -> PlatformProfile:
        if self._profile is None:
            try:
                self._profile = detect_platform()
            except SandboxUnavailableError as e:
                raise SandboxProvisionError(str(e)) from e
        return self._profile

    async def _validate_spec(self, spec: dict[str, Any]) -> None:
        try:
            result = await self._runner.run(
                ["validate", "--spec=-"],
                config_json=spec,
                timeout_seconds=15.0,
            )
        except SandboxRuntimeError as e:
            raise SandboxProvisionError(str(e)) from e
        except TimeoutError as e:
            raise SandboxProvisionError("srt validate timed out") from e

        if not result.ok:
            raise SandboxProvisionError(
                f"srt rejected spec (exit {result.exit_code}): "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )

    async def _run_in_sandbox(
        self,
        spec: dict[str, Any],
        command: list[str],
        *,
        timeout_seconds: float,
    ) -> tuple[int, str, bool]:
        """Invoke ``srt run`` with the spec on stdin and ``command`` as argv.

        Returns ``(exit_code, output, truncated)``. ``output`` is stdout with
        stderr appended if non-empty — matching DockerSandbox semantics where
        bash exec_run captures both streams.
        """
        # We pass the spec via stdin to avoid leaking it onto disk / in argv.
        argv = ["run", "--spec=-", "--"] + command
        try:
            result = await self._runner.run(
                argv,
                config_json=spec,
                timeout_seconds=timeout_seconds,
            )
        except SandboxRuntimeError as e:
            return -1, f"sandbox-runtime invocation failed: {e}", False
        except TimeoutError:
            return -1, f"command exceeded {timeout_seconds}s timeout.", False

        # Combine streams: bash users expect stderr inline.
        combined = result.stdout
        if result.stderr:
            combined = combined + ("\n" if combined else "") + result.stderr
        return result.exit_code, combined, result.truncated

    # -- per-tool implementations ------------------------------------------

    async def _exec_bash(
        self,
        handle: SandboxHandle,  # noqa: ARG002 — kept for symmetry / future use
        spec: dict[str, Any],
        input: dict[str, Any],  # noqa: A002
    ) -> ToolResult:
        command = input.get("command")
        if not isinstance(command, str) or not command.strip():
            return _err(
                "bash: 'command' is required and must be a non-empty string.",
                "invalid_tool_input",
            )
        timeout_s = float(input.get("timeout_seconds", DEFAULT_TIMEOUT_S))

        exit_code, text, truncated = await self._run_in_sandbox(
            spec,
            ["/bin/sh", "-lc", command],
            timeout_seconds=timeout_s,
        )
        if exit_code == -1:
            # Marker we set on subprocess failure / timeout.
            if "timeout" in text:
                return _err(text, "execution_time_exceeded")
            return _err(text, "unknown")
        if exit_code != 0:
            return ToolResult(
                content=[TextBlock(text=text or f"(exit {exit_code})")],
                is_error=True,
                error_code="output_too_large" if truncated else "unknown",
            )
        return _ok(text)

    async def _exec_file_read(
        self,
        handle: SandboxHandle,  # noqa: ARG002
        spec: dict[str, Any],
        input: dict[str, Any],  # noqa: A002
    ) -> ToolResult:
        path = input.get("path")
        if not isinstance(path, str) or not path:
            return _err("file_read: 'path' is required.", "invalid_tool_input")

        start = input.get("start_line")
        end = input.get("end_line")
        if isinstance(start, int) or isinstance(end, int):
            s = max(int(start or 1), 1)
            e = int(end) if isinstance(end, int) else 0
            cmd = (
                f"sed -n '{s},{e}p' {shlex.quote(path)}"
                if e
                else f"sed -n '{s},$p' {shlex.quote(path)}"
            )
        else:
            cmd = f"cat {shlex.quote(path)}"

        exit_code, text, _ = await self._run_in_sandbox(
            spec,
            ["/bin/sh", "-lc", cmd],
            timeout_seconds=float(DEFAULT_TIMEOUT_S),
        )
        if exit_code != 0:
            code = "not_found" if "No such file" in text else "unknown"
            return _err(text or f"file_read failed (exit {exit_code})", code)
        return _ok(text)

    async def _exec_file_write(
        self,
        handle: SandboxHandle,  # noqa: ARG002
        spec: dict[str, Any],
        input: dict[str, Any],  # noqa: A002
    ) -> ToolResult:
        path = input.get("path")
        content = input.get("content")
        if not isinstance(path, str) or not path:
            return _err("file_write: 'path' is required.", "invalid_tool_input")
        if not isinstance(content, str):
            return _err("file_write: 'content' must be a string.", "invalid_tool_input")

        # Use a base64-piped write — safer than heredoc for arbitrary content
        # and free of quoting hazards.
        import base64

        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        cmd = (
            f"mkdir -p $(dirname {shlex.quote(path)}) && "
            f"echo {shlex.quote(encoded)} | base64 -d > {shlex.quote(path)}"
        )
        exit_code, text, _ = await self._run_in_sandbox(
            spec,
            ["/bin/sh", "-lc", cmd],
            timeout_seconds=float(DEFAULT_TIMEOUT_S),
        )
        if exit_code != 0:
            return _err(text or f"file_write failed (exit {exit_code})", "unknown")
        return _ok(f"wrote {path}")

    async def _exec_file_edit(
        self,
        handle: SandboxHandle,
        spec: dict[str, Any],
        input: dict[str, Any],  # noqa: A002
    ) -> ToolResult:
        path = input.get("path")
        old = input.get("old_string")
        new = input.get("new_string")
        replace_all = bool(input.get("replace_all", False))

        if not isinstance(path, str) or not path:
            return _err("file_edit: 'path' required.", "invalid_tool_input")
        if not isinstance(old, str) or not isinstance(new, str):
            return _err(
                "file_edit: 'old_string' and 'new_string' required.",
                "invalid_tool_input",
            )

        read = await self._exec_file_read(handle, spec, {"path": path})
        if read.is_error:
            return read
        current = "".join(b.text for b in read.content)

        if old not in current:
            return _err("file_edit: old_string not found in file.", "string_not_found")

        if replace_all:
            updated = current.replace(old, new)
        elif current.count(old) > 1:
            return _err(
                "file_edit: old_string appears more than once; "
                "use replace_all=true or disambiguate.",
                "invalid_tool_input",
            )
        else:
            updated = current.replace(old, new, 1)

        return await self._exec_file_write(handle, spec, {"path": path, "content": updated})


# -- factory used by the ``wake.sandboxes`` entry-point --------------------


def create() -> SandboxRuntimeAdapter:
    """Return a default-configured :class:`SandboxRuntimeAdapter`.

    Wired up via ``[project.entry-points."wake.sandboxes"]`` so a registry
    discoverer can construct the adapter without knowing about the package.
    """
    return SandboxRuntimeAdapter()


__all__ = [
    "BACKEND_NAME",
    "DEFAULT_TIMEOUT_S",
    "MANDATORY_DENY_PATHS",
    "SandboxRuntimeAdapter",
    "create",
]
