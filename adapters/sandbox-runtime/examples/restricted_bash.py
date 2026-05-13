"""Example: run a restricted bash command via wake-sandbox-runtime.

This example demonstrates the **fallback** API: it asks for the
``sandbox-runtime`` backend, but transparently falls back to Docker when the
CLI is missing or the platform is unsupported. Useful for documentation and
as a smoke test you can run on any developer machine.

Run::

    python adapters/sandbox-runtime/examples/restricted_bash.py

What it does:

1. Selects the best sandbox backend (sandbox-runtime → Docker → error).
2. Provisions an environment that only allows writes under ``/workspace``.
3. Runs ``ls /etc`` and tries ``cat ~/.ssh/id_rsa``. The latter must be
   denied by the sandbox (or, in the Docker fallback, by the lack of mount).
4. Cleans up.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import structlog
from wake.types import EnvironmentConfig

from wake_sandbox_runtime import (
    SandboxUnavailableError,
    select_sandbox_backend,
)

logger = structlog.get_logger("restricted_bash")


async def main() -> None:
    try:
        backend = await select_sandbox_backend(prefer="sandbox-runtime")
    except SandboxUnavailableError as e:
        logger.error("no_sandbox_backend", error=str(e))
        return

    logger.info("selected_backend", backend=type(backend).__name__)

    env = EnvironmentConfig(
        id="env_example",
        name="restricted-bash-example",
        config={
            "workspace": "/workspace",
            "network_mode": "none",
            # No additional read_allow — only the workspace + system defaults.
        },
        created_at=datetime.now(UTC),
    )

    handle = await backend.provision(env)
    logger.info(
        "provisioned",
        backend=handle.backend,
        container_id=handle.container_id,
        workspace=handle.workspace_path,
    )

    try:
        # Allowed: list /etc (read-only, no sensitive paths).
        result = await backend.execute(handle, "bash", {"command": "ls /etc | head -5"})
        print("ls /etc | head -5 →", repr(result.content[0].text))

        # Denied: ~/.ssh access must fail.
        result = await backend.execute(
            handle,
            "bash",
            {"command": "cat ~/.ssh/id_rsa 2>&1 || echo BLOCKED"},
        )
        print("cat ~/.ssh/id_rsa →", repr(result.content[0].text))
    finally:
        await backend.destroy(handle)
        logger.info("destroyed", container_id=handle.container_id)


if __name__ == "__main__":
    asyncio.run(main())
