"""Async subprocess wrapper for the ``@anthropic-ai/sandbox-runtime`` CLI.

Centralises all interaction with the ``srt`` binary so the adapter and the
tests can mock a single seam.

We deliberately use :func:`asyncio.create_subprocess_exec` (with an explicit
argv list — never a shell) so that:

- timeouts work via :func:`asyncio.wait_for`
- argv is not interpolated through a shell
- stdout/stderr capture is straightforward
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)

MAX_OUTPUT_BYTES = 256 * 1024  # 256 KiB — match DockerSandbox


class SandboxRuntimeError(RuntimeError):
    """Raised when the srt CLI returns a non-zero exit or cannot be invoked."""


@dataclass(frozen=True)
class SubprocessResult:
    """Captured outcome of an srt CLI invocation."""

    exit_code: int
    stdout: str
    stderr: str
    truncated: bool

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def _truncate(raw: bytes, limit: int = MAX_OUTPUT_BYTES) -> tuple[str, bool]:
    if len(raw) <= limit:
        return raw.decode("utf-8", errors="replace"), False
    return (
        raw[:limit].decode("utf-8", errors="replace") + "\n... [truncated]",
        True,
    )


class SubprocessRunner:
    """Invokes the srt CLI.

    The ``srt_binary`` argument is the executable name or absolute path; it is
    resolved via the caller's PATH at exec time. We do not pre-resolve so that
    tests can monkeypatch :func:`asyncio.create_subprocess_exec`.
    """

    def __init__(self, srt_binary: str = "sandbox-runtime") -> None:
        self._binary = srt_binary

    @property
    def binary(self) -> str:
        return self._binary

    async def run(
        self,
        argv: list[str],
        *,
        config_json: dict[str, object] | None = None,
        input_text: str | None = None,
        timeout_seconds: float | None = None,
    ) -> SubprocessResult:
        """Spawn ``srt <argv...>``; optionally pipe a JSON config / stdin.

        Args:
            argv: Arguments AFTER the binary (e.g. ``["run", "--spec=-"]``).
            config_json: Optional dict; serialised to JSON and merged with
                ``input_text`` on stdin if both are present.
            input_text: Optional raw stdin payload.
            timeout_seconds: Wall-clock kill after this many seconds.

        Returns:
            :class:`SubprocessResult`.

        Raises:
            SandboxRuntimeError: If the binary cannot be spawned at all.
            TimeoutError: If ``timeout_seconds`` elapses; the process is
                terminated.
        """
        stdin_blob: bytes | None = None
        if config_json is not None and input_text is not None:
            stdin_blob = (json.dumps(config_json) + "\n" + input_text).encode("utf-8")
        elif config_json is not None:
            stdin_blob = json.dumps(config_json).encode("utf-8")
        elif input_text is not None:
            stdin_blob = input_text.encode("utf-8")

        try:
            proc = await asyncio.create_subprocess_exec(
                self._binary,
                *argv,
                stdin=asyncio.subprocess.PIPE if stdin_blob is not None else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as e:
            raise SandboxRuntimeError(
                f"sandbox-runtime CLI not found on PATH (binary={self._binary!r}). "
                f"Install via: npm install -g @anthropic-ai/sandbox-runtime"
            ) from e
        except OSError as e:
            raise SandboxRuntimeError(f"failed to spawn sandbox-runtime: {e}") from e

        async def _communicate() -> tuple[bytes, bytes]:
            return await proc.communicate(input=stdin_blob)

        try:
            stdout_b, stderr_b = await asyncio.wait_for(_communicate(), timeout=timeout_seconds)
        except TimeoutError:
            with _suppress():
                proc.kill()
                await proc.wait()
            logger.warning(
                "sandbox_runtime_timeout",
                binary=self._binary,
                argv=argv,
                timeout_seconds=timeout_seconds,
            )
            raise

        stdout_s, stdout_trunc = _truncate(stdout_b)
        stderr_s, stderr_trunc = _truncate(stderr_b)
        exit_code = proc.returncode if proc.returncode is not None else -1

        return SubprocessResult(
            exit_code=exit_code,
            stdout=stdout_s,
            stderr=stderr_s,
            truncated=stdout_trunc or stderr_trunc,
        )

    async def is_available(self) -> bool:
        """Return ``True`` if ``srt --version`` succeeds.

        Used by :func:`wake_sandbox_runtime.selector.select_sandbox_backend`
        to decide between srt and the Docker fallback.
        """
        try:
            result = await self.run(["--version"], timeout_seconds=5.0)
        except SandboxRuntimeError:
            return False
        except TimeoutError:
            return False
        return result.exit_code == 0


class _Suppress:
    """Tiny contextmanager that swallows everything — used during cleanup."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: object) -> bool:
        return True


_suppress = _Suppress  # public alias kept for the internal call site


__all__ = [
    "MAX_OUTPUT_BYTES",
    "SandboxRuntimeError",
    "SubprocessResult",
    "SubprocessRunner",
]
