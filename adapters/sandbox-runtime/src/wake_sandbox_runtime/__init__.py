"""Wake SandboxAdapter wrapping @anthropic-ai/sandbox-runtime.

A thin Python wrapper around the npm ``@anthropic-ai/sandbox-runtime`` (srt)
CLI from Anthropic (beta research preview). On Linux it uses bubblewrap; on
macOS it uses ``sandbox-exec``. If the CLI is missing or the host platform is
unsupported, :func:`select_sandbox_backend` transparently falls back to the
Phase 1 :class:`wake.sandbox.docker.DockerSandbox`.

Re-exports:

- :class:`SandboxRuntimeAdapter` — the adapter itself
- :func:`select_sandbox_backend` — fallback selector helper
- :class:`SandboxUnavailableError` — raised when no backend is available
- :func:`detect_platform` — returns the sandbox profile for the current OS

The CLI is shelled out via ``asyncio.create_subprocess_exec``; there is no
pip dependency on srt. Install it separately::

    npm install -g @anthropic-ai/sandbox-runtime
"""

from wake_sandbox_runtime.adapter import (
    BACKEND_NAME,
    MANDATORY_DENY_PATHS,
    SandboxRuntimeAdapter,
    create,
)
from wake_sandbox_runtime.platform_detect import (
    PlatformProfile,
    SandboxUnavailableError,
    detect_platform,
)
from wake_sandbox_runtime.selector import select_sandbox_backend

__all__ = [
    "BACKEND_NAME",
    "MANDATORY_DENY_PATHS",
    "PlatformProfile",
    "SandboxRuntimeAdapter",
    "SandboxUnavailableError",
    "create",
    "detect_platform",
    "select_sandbox_backend",
]

__version__ = "0.1.0"
