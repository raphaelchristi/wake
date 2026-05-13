# ruff: noqa: TC002
"""Graceful fallback selector for sandbox backends.

Production callers should prefer :func:`select_sandbox_backend` over
constructing :class:`SandboxRuntimeAdapter` directly — it returns the
sandbox-runtime adapter when usable, otherwise transparently falls back to
:class:`wake.sandbox.docker.DockerSandbox`.

Order of attempts when ``prefer="sandbox-runtime"`` (default):

1. Probe the host platform via :func:`detect_platform`.
2. Probe the ``srt`` CLI via ``--version``.
3. If both succeed → return :class:`SandboxRuntimeAdapter`.
4. Otherwise → try to instantiate :class:`DockerSandbox`; emit a
   ``structlog`` warning explaining why we fell back.
5. If Docker is also unavailable → raise :class:`SandboxUnavailableError`.

Setting ``prefer="docker"`` skips srt entirely. Setting
``prefer="sandbox-runtime"`` and ``strict=True`` disables fallback (raises
instead of using Docker).
"""

from __future__ import annotations

from typing import Literal

import structlog
from wake.sandbox.base import SandboxAdapter

from wake_sandbox_runtime.adapter import SandboxRuntimeAdapter
from wake_sandbox_runtime.platform_detect import (
    SandboxUnavailableError,
    detect_platform,
)
from wake_sandbox_runtime.subprocess_runner import SubprocessRunner

logger = structlog.get_logger(__name__)

Preference = Literal["sandbox-runtime", "docker"]


async def select_sandbox_backend(
    prefer: Preference = "sandbox-runtime",
    *,
    srt_binary: str = "sandbox-runtime",
    proxy_url: str | None = None,
    strict: bool = False,
    runner: SubprocessRunner | None = None,
    docker_factory: type[SandboxAdapter] | None = None,
) -> SandboxAdapter:
    """Return the best available sandbox backend, with graceful fallback.

    Args:
        prefer: ``"sandbox-runtime"`` (default) tries srt first; ``"docker"``
            goes straight to Docker.
        srt_binary: CLI name passed to :class:`SubprocessRunner`.
        proxy_url: Forwarded to :class:`SandboxRuntimeAdapter` for
            agentgateway integration.
        strict: When ``True`` and ``prefer == "sandbox-runtime"``, refuse to
            fall back — raise :class:`SandboxUnavailableError` instead.
        runner: Inject a pre-built :class:`SubprocessRunner` (tests).
        docker_factory: Override the Docker adapter class (tests). Defaults
            to :class:`wake.sandbox.docker.DockerSandbox`.

    Returns:
        A ready-to-use :class:`SandboxAdapter` instance.

    Raises:
        SandboxUnavailableError: When no backend is available.
    """
    if prefer == "sandbox-runtime":
        adapter = await _try_sandbox_runtime(
            srt_binary=srt_binary, proxy_url=proxy_url, runner=runner
        )
        if adapter is not None:
            return adapter
        if strict:
            raise SandboxUnavailableError(
                "sandbox-runtime requested with strict=True but it is not "
                "available on this host (missing CLI or unsupported platform)."
            )
        logger.warning(
            "sandbox_runtime_unavailable_falling_back",
            prefer=prefer,
            srt_binary=srt_binary,
        )

    docker = _try_docker(docker_factory)
    if docker is not None:
        return docker

    raise SandboxUnavailableError(
        "No sandbox backend available: sandbox-runtime is missing/unsupported "
        "and Docker could not be instantiated. Install one of:\n"
        "  - npm install -g @anthropic-ai/sandbox-runtime  (preferred)\n"
        "  - Docker Desktop / docker engine                 (fallback)"
    )


async def _try_sandbox_runtime(
    *,
    srt_binary: str,
    proxy_url: str | None,
    runner: SubprocessRunner | None,
) -> SandboxRuntimeAdapter | None:
    """Return a configured adapter if srt is usable on this host, else ``None``."""
    try:
        profile = detect_platform()
    except SandboxUnavailableError:
        logger.info("sandbox_runtime_platform_unsupported")
        return None

    probe_runner = runner if runner is not None else SubprocessRunner(srt_binary)
    if not await probe_runner.is_available():
        logger.info("sandbox_runtime_cli_missing", binary=srt_binary)
        return None

    return SandboxRuntimeAdapter(
        srt_binary=srt_binary,
        runner=probe_runner,
        profile=profile,
        proxy_url=proxy_url,
    )


def _try_docker(
    docker_factory: type[SandboxAdapter] | None,
) -> SandboxAdapter | None:
    """Return a Docker adapter instance or ``None`` if Docker is unusable."""
    if docker_factory is not None:
        try:
            return docker_factory()
        except Exception as e:  # noqa: BLE001 — fallback should never propagate
            logger.warning("docker_factory_failed", error=str(e))
            return None

    try:
        from wake.sandbox.docker import DockerSandbox
    except ImportError as e:
        logger.warning("docker_import_failed", error=str(e))
        return None

    try:
        return DockerSandbox()
    except Exception as e:  # noqa: BLE001 — daemon missing, perms, etc.
        logger.warning("docker_init_failed", error=str(e))
        return None


__all__ = [
    "Preference",
    "SandboxUnavailableError",
    "select_sandbox_backend",
]
