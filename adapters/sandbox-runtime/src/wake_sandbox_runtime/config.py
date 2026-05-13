# ruff: noqa: TC001, TC002
"""Build srt JSON config dicts from Wake :class:`EnvironmentConfig`.

The npm ``@anthropic-ai/sandbox-runtime`` CLI consumes a JSON spec describing:

- read-allow / read-deny path lists
- write-allow / write-deny path lists
- environment variables to pass through
- network mode (``none`` | ``host`` | ``proxied``)
- optional HTTP/HTTPS proxy endpoint
- platform profile (``linux-bwrap`` / ``macos-sandbox-exec``)

This module produces that spec from an :class:`EnvironmentConfig`. It is the
*only* place in the package that knows the srt JSON schema; everything else
treats it as an opaque ``dict[str, Any]``.

**Security invariant:** the paths listed in :data:`MANDATORY_DENY_PATHS` are
always added to ``read_deny`` and ``write_deny`` — caller config cannot remove
them. This is enforced by :func:`build_srt_config`.
"""

from __future__ import annotations

import os
from typing import Any

from wake.types import EnvironmentConfig

from wake_sandbox_runtime.platform_detect import PlatformProfile

# Override-proof deny list. ``~`` is resolved per-call against the current
# ``HOME`` so tests can use a temp HOME and prod uses the real one.
_HOME_RELATIVE_DENY = (
    "~/.ssh",
    "~/.aws",
    "~/.gnupg",
    "~/.config/gh",
    "~/.kube",
    "~/.docker/config.json",
)
_ABSOLUTE_DENY = (
    "/etc/shadow",
    "/etc/sudoers",
    "/etc/sudoers.d",
    "/root/.ssh",
)

# Public for tests / docs.
MANDATORY_DENY_PATHS: tuple[str, ...] = _HOME_RELATIVE_DENY + _ABSOLUTE_DENY

DEFAULT_WORKSPACE = "/workspace"
DEFAULT_NETWORK_MODE = "none"
ALLOWED_NETWORK_MODES = frozenset({"none", "host", "proxied"})

# Env vars worth passing through by default (purely operational; never secrets).
_DEFAULT_PASSTHROUGH_ENV: tuple[str, ...] = (
    "PATH",
    "LANG",
    "LC_ALL",
    "TERM",
)


def _expand_home(path: str, home: str | None = None) -> str:
    """Resolve ``~`` against the given (or real) ``HOME``.

    We do *not* use :func:`os.path.expanduser` directly because it consults
    pwd databases on Linux which can be surprising in containers; passing an
    explicit ``home`` lets tests be hermetic.
    """
    if not path.startswith("~"):
        return path
    base = home if home is not None else os.environ.get("HOME", "/root")
    return base + path[1:]


def _resolve_deny_paths(home: str | None = None) -> list[str]:
    """Return :data:`MANDATORY_DENY_PATHS` with ``~`` expanded."""
    return [_expand_home(p, home=home) for p in MANDATORY_DENY_PATHS]


def build_srt_config(
    env: EnvironmentConfig,
    *,
    profile: PlatformProfile,
    proxy_url: str | None = None,
    home: str | None = None,
) -> dict[str, Any]:
    """Translate an :class:`EnvironmentConfig` into an srt JSON spec.

    Args:
        env: Wake environment config. Reads from ``env.config``:
            - ``workspace``: workspace path (default ``/workspace``)
            - ``read_allow``: list[str] additional read-allow paths
            - ``write_allow``: list[str] additional write-allow paths
            - ``read_deny``: list[str] additional read-deny paths
            - ``write_deny``: list[str] additional write-deny paths
            - ``network_mode``: ``"none"`` | ``"host"`` | ``"proxied"``
            - ``env``: dict[str, str] env vars to set inside the sandbox
            - ``passthrough_env``: list[str] env var names to inherit from host
            - ``timeout_seconds``: int default tool timeout
        profile: Detected platform profile.
        proxy_url: Endpoint for HTTP_PROXY/HTTPS_PROXY when
            ``network_mode == "proxied"`` (typically agentgateway sidecar).
        home: Override ``$HOME`` for ``~`` expansion. Mostly for tests.

    Returns:
        A JSON-serializable dict ready to be handed to the srt CLI.
    """
    raw = dict(env.config or {})

    workspace = str(raw.get("workspace", DEFAULT_WORKSPACE))
    network_mode = str(raw.get("network_mode", DEFAULT_NETWORK_MODE))
    if network_mode not in ALLOWED_NETWORK_MODES:
        raise ValueError(
            f"invalid network_mode={network_mode!r}; must be one of {sorted(ALLOWED_NETWORK_MODES)}"
        )

    timeout_s = int(raw.get("timeout_seconds", 60))

    user_read_allow = [str(p) for p in raw.get("read_allow", [])]
    user_write_allow = [str(p) for p in raw.get("write_allow", [])]
    user_read_deny = [str(p) for p in raw.get("read_deny", [])]
    user_write_deny = [str(p) for p in raw.get("write_deny", [])]

    # Mandatory deny — applied AFTER user lists so it always wins. The srt CLI
    # treats deny as override of allow; we additionally filter the allow lists
    # to drop any path that would resolve under a mandatory-deny path, so the
    # config is obviously safe even when read by a human auditor.
    mandatory = _resolve_deny_paths(home=home)
    expanded_user_read_allow = [_expand_home(p, home=home) for p in user_read_allow]
    expanded_user_write_allow = [_expand_home(p, home=home) for p in user_write_allow]

    def _is_under_deny(path: str) -> bool:
        normalized = os.path.normpath(path)
        for deny in mandatory:
            d = os.path.normpath(deny)
            if normalized == d or normalized.startswith(d.rstrip("/") + "/"):
                return True
        return False

    read_allow = [p for p in expanded_user_read_allow if not _is_under_deny(p)]
    write_allow = [p for p in expanded_user_write_allow if not _is_under_deny(p)]

    # Dedup while preserving order.
    def _dedup(items: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for item in items:
            if item not in seen:
                seen.add(item)
                out.append(item)
        return out

    read_deny = _dedup([_expand_home(p, home=home) for p in user_read_deny] + mandatory)
    write_deny = _dedup([_expand_home(p, home=home) for p in user_write_deny] + mandatory)

    # Env: explicit map > passthrough.
    env_vars: dict[str, str] = {}
    passthrough = list(raw.get("passthrough_env", _DEFAULT_PASSTHROUGH_ENV))
    for name in passthrough:
        if name in os.environ:
            env_vars[name] = os.environ[name]
    for k, v in (raw.get("env") or {}).items():
        env_vars[str(k)] = str(v)

    # Proxy hook: if network_mode == "proxied" and a proxy_url is configured,
    # inject HTTP/HTTPS_PROXY so child processes route through agentgateway.
    if network_mode == "proxied" and proxy_url:
        env_vars.setdefault("HTTP_PROXY", proxy_url)
        env_vars.setdefault("HTTPS_PROXY", proxy_url)
        # Many tools also look at lowercase versions.
        env_vars.setdefault("http_proxy", proxy_url)
        env_vars.setdefault("https_proxy", proxy_url)

    spec: dict[str, Any] = {
        "version": 1,
        "profile": profile.name,
        "workspace": workspace,
        "read_allow": _dedup([workspace] + read_allow),
        "write_allow": _dedup([workspace] + write_allow),
        "read_deny": read_deny,
        "write_deny": write_deny,
        "network": {
            "mode": network_mode,
        },
        "env": env_vars,
        "timeout_seconds": timeout_s,
        "metadata": {
            "wake_env_id": env.id,
            "wake_env_name": env.name,
        },
    }

    if network_mode == "proxied" and proxy_url:
        spec["network"]["proxy_url"] = proxy_url

    return spec


__all__ = [
    "ALLOWED_NETWORK_MODES",
    "DEFAULT_NETWORK_MODE",
    "DEFAULT_WORKSPACE",
    "MANDATORY_DENY_PATHS",
    "build_srt_config",
]
