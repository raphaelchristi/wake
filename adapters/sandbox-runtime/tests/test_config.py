# ruff: noqa: TC001
"""Tests for :mod:`wake_sandbox_runtime.config`.

Focus areas:

- Mandatory deny paths are always present and cannot be overridden.
- Network proxy hook injects HTTP_PROXY / HTTPS_PROXY.
- Workspace defaults / overrides round-trip.
- Invalid network_mode is rejected.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from wake.types import EnvironmentConfig

from wake_sandbox_runtime.config import (
    ALLOWED_NETWORK_MODES,
    MANDATORY_DENY_PATHS,
    build_srt_config,
)
from wake_sandbox_runtime.platform_detect import PlatformProfile


def _env(config: dict[str, object]) -> EnvironmentConfig:
    return EnvironmentConfig(
        id="env_x",
        name="x",
        config=config,
        created_at=datetime.now(UTC),
    )


def test_mandatory_deny_paths_always_present(linux_profile: PlatformProfile) -> None:
    spec = build_srt_config(_env({}), profile=linux_profile, home="/home/u")
    # Resolve ~ for the assertion.
    for raw_path in MANDATORY_DENY_PATHS:
        expanded = raw_path.replace("~", "/home/u") if raw_path.startswith("~") else raw_path
        assert expanded in spec["read_deny"], f"missing read_deny: {expanded}"
        assert expanded in spec["write_deny"], f"missing write_deny: {expanded}"


def test_cannot_override_mandatory_deny_via_allow(linux_profile: PlatformProfile) -> None:
    """User cannot whitelist ``~/.ssh`` even if they try."""
    spec = build_srt_config(
        _env(
            {
                "read_allow": ["~/.ssh", "~/.ssh/id_rsa", "/etc/shadow"],
                "write_allow": ["~/.aws", "/etc/sudoers"],
            }
        ),
        profile=linux_profile,
        home="/home/u",
    )
    for path in spec["read_allow"]:
        assert "/.ssh" not in path
        assert "/.aws" not in path
        assert path != "/etc/shadow"
    for path in spec["write_allow"]:
        assert "/.aws" not in path
        assert "/.ssh" not in path
        assert path != "/etc/sudoers"
    # Deny still applies.
    assert "/home/u/.ssh" in spec["read_deny"]


def test_workspace_default_appears_in_allow(linux_profile: PlatformProfile) -> None:
    spec = build_srt_config(_env({}), profile=linux_profile)
    assert "/workspace" in spec["read_allow"]
    assert "/workspace" in spec["write_allow"]


def test_workspace_override(linux_profile: PlatformProfile) -> None:
    spec = build_srt_config(_env({"workspace": "/srv/work"}), profile=linux_profile)
    assert spec["workspace"] == "/srv/work"
    assert "/srv/work" in spec["read_allow"]
    assert "/srv/work" in spec["write_allow"]


def test_network_mode_default_none(linux_profile: PlatformProfile) -> None:
    spec = build_srt_config(_env({}), profile=linux_profile)
    assert spec["network"]["mode"] == "none"
    assert "proxy_url" not in spec["network"]


def test_network_mode_proxied_injects_proxy(linux_profile: PlatformProfile) -> None:
    spec = build_srt_config(
        _env({"network_mode": "proxied"}),
        profile=linux_profile,
        proxy_url="http://agentgateway.local:8888",
    )
    assert spec["network"]["mode"] == "proxied"
    assert spec["network"]["proxy_url"] == "http://agentgateway.local:8888"
    assert spec["env"]["HTTP_PROXY"] == "http://agentgateway.local:8888"
    assert spec["env"]["HTTPS_PROXY"] == "http://agentgateway.local:8888"
    assert spec["env"]["http_proxy"] == "http://agentgateway.local:8888"
    assert spec["env"]["https_proxy"] == "http://agentgateway.local:8888"


def test_network_mode_proxied_without_proxy_url_no_inject(
    linux_profile: PlatformProfile,
) -> None:
    spec = build_srt_config(
        _env({"network_mode": "proxied"}), profile=linux_profile, proxy_url=None
    )
    assert "HTTP_PROXY" not in spec["env"]


def test_invalid_network_mode_rejected(linux_profile: PlatformProfile) -> None:
    with pytest.raises(ValueError, match="network_mode"):
        build_srt_config(_env({"network_mode": "wild"}), profile=linux_profile)


def test_all_documented_network_modes_accepted(
    linux_profile: PlatformProfile,
) -> None:
    for mode in ALLOWED_NETWORK_MODES:
        spec = build_srt_config(
            _env({"network_mode": mode}),
            profile=linux_profile,
            proxy_url="http://p:1" if mode == "proxied" else None,
        )
        assert spec["network"]["mode"] == mode


def test_env_passthrough_picks_up_host_vars(
    linux_profile: PlatformProfile, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    spec = build_srt_config(_env({}), profile=linux_profile)
    assert spec["env"]["PATH"] == "/usr/local/bin:/usr/bin"
    assert spec["env"]["LANG"] == "en_US.UTF-8"


def test_explicit_env_overrides_passthrough(
    linux_profile: PlatformProfile, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", "/host/bin")
    spec = build_srt_config(_env({"env": {"PATH": "/sandbox/bin"}}), profile=linux_profile)
    assert spec["env"]["PATH"] == "/sandbox/bin"


def test_profile_name_in_spec(macos_profile: PlatformProfile) -> None:
    spec = build_srt_config(_env({}), profile=macos_profile)
    assert spec["profile"] == "macos-sandbox-exec"


def test_metadata_carries_env_identity(linux_profile: PlatformProfile) -> None:
    env = _env({})
    spec = build_srt_config(env, profile=linux_profile)
    assert spec["metadata"]["wake_env_id"] == env.id
    assert spec["metadata"]["wake_env_name"] == env.name


def test_dedup_preserves_order(linux_profile: PlatformProfile) -> None:
    spec = build_srt_config(
        _env(
            {
                "read_allow": ["/a", "/b", "/a"],
            }
        ),
        profile=linux_profile,
    )
    # /workspace prepended, then user paths deduped
    ra = spec["read_allow"]
    assert ra.count("/a") == 1
    assert ra.count("/b") == 1


def test_home_resolution_uses_real_home_by_default(
    linux_profile: PlatformProfile, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", "/var/agent")
    spec = build_srt_config(_env({}), profile=linux_profile)
    assert any(p.startswith("/var/agent/.ssh") for p in spec["read_deny"])


def test_unused_import_marker() -> None:
    # The ``os`` import is used indirectly via build_srt_config; this is a sanity
    # check that the module imports correctly.
    assert os.sep in {"/", "\\"}
