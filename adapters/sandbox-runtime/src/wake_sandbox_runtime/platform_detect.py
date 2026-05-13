"""Platform detection for sandbox-runtime.

The npm ``@anthropic-ai/sandbox-runtime`` CLI ships profiles for two host
families:

- **Linux** — uses bubblewrap (``bwrap``). On Ubuntu 24.04+ you also need
  ``sysctl kernel.apparmor_restrict_unprivileged_userns=0`` (see README).
- **macOS** — uses the built-in ``sandbox-exec`` (Seatbelt). Available on
  Darwin out of the box.

Everything else (Windows, BSDs, exotic kernels) is unsupported; the selector
will fall back to Docker. Calling :func:`detect_platform` on an unsupported
host raises :class:`SandboxUnavailableError` so callers can decide whether to
fall back or fail hard.
"""

from __future__ import annotations

import platform
import shutil
from dataclasses import dataclass
from typing import Literal

ProfileName = Literal["linux-bwrap", "macos-sandbox-exec"]

# Sentinel meaning "probe the actual host" — distinct from None which can be
# passed by tests to force "binary missing".
_PROBE: object = object()


class SandboxUnavailableError(RuntimeError):
    """Raised when no sandbox backend is available on this host."""


@dataclass(frozen=True)
class PlatformProfile:
    """Describes which sandbox profile srt should use on this host."""

    name: ProfileName
    system: str  # "Linux" | "Darwin"
    backend_binary: str | None  # e.g. "bwrap" on Linux, None on macOS
    notes: str = ""

    @property
    def is_linux(self) -> bool:
        return self.name == "linux-bwrap"

    @property
    def is_macos(self) -> bool:
        return self.name == "macos-sandbox-exec"


def _which(binary: str) -> str | None:
    """Thin wrapper around :func:`shutil.which` to ease monkeypatching in tests."""
    return shutil.which(binary)


def detect_platform(
    *,
    system: str | None = None,
    bwrap_path: str | None | object = _PROBE,
) -> PlatformProfile:
    """Return the sandbox profile for the current host.

    Parameters are exposed for testability — production callers should pass
    nothing.

    Args:
        system: Override :func:`platform.system` (``"Linux"`` / ``"Darwin"``).
            ``None`` means "probe the real host".
        bwrap_path: Override the ``bwrap`` lookup. The default sentinel means
            "probe via ``shutil.which``". Pass ``None`` or ``""`` to simulate
            "not found"; pass a path string to simulate "found".

    Raises:
        SandboxUnavailableError: If the host is neither Linux-with-bwrap nor
            macOS.
    """
    sys_name = system if system is not None else platform.system()

    if sys_name == "Linux":
        bwrap: str | None
        if bwrap_path is _PROBE:
            bwrap = _which("bwrap")
        else:
            # Caller-supplied override; coerce truthy types to str | None.
            bwrap = bwrap_path if isinstance(bwrap_path, str) and bwrap_path else None
        if not bwrap:
            raise SandboxUnavailableError(
                "Linux host detected but 'bwrap' (bubblewrap) is not on PATH. "
                "Install via 'apt install bubblewrap' / 'dnf install bubblewrap'. "
                "On Ubuntu 24.04+ also run: "
                "sysctl kernel.apparmor_restrict_unprivileged_userns=0"
            )
        return PlatformProfile(
            name="linux-bwrap",
            system="Linux",
            backend_binary=bwrap,
            notes=(
                "Ubuntu 24.04+ requires 'sysctl kernel.apparmor_restrict_unprivileged_userns=0'."
            ),
        )

    if sys_name == "Darwin":
        return PlatformProfile(
            name="macos-sandbox-exec",
            system="Darwin",
            backend_binary=None,
            notes="Uses macOS sandbox-exec (Seatbelt); no extra setup required.",
        )

    raise SandboxUnavailableError(
        f"Sandbox-runtime supports Linux and macOS only; detected platform.system()={sys_name!r}."
    )


__all__ = [
    "PlatformProfile",
    "ProfileName",
    "SandboxUnavailableError",
    "detect_platform",
]
