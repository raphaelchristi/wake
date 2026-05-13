"""Tests for :mod:`wake_sandbox_runtime.platform_detect`."""

from __future__ import annotations

import pytest

from wake_sandbox_runtime.platform_detect import (
    SandboxUnavailableError,
    detect_platform,
)


def test_detect_linux_with_bwrap() -> None:
    profile = detect_platform(system="Linux", bwrap_path="/usr/bin/bwrap")
    assert profile.name == "linux-bwrap"
    assert profile.system == "Linux"
    assert profile.backend_binary == "/usr/bin/bwrap"
    assert profile.is_linux
    assert not profile.is_macos
    assert "apparmor_restrict_unprivileged_userns" in profile.notes


def test_detect_linux_missing_bwrap_raises() -> None:
    with pytest.raises(SandboxUnavailableError, match="bwrap"):
        detect_platform(system="Linux", bwrap_path=None)


def test_detect_linux_empty_bwrap_treated_as_missing() -> None:
    with pytest.raises(SandboxUnavailableError):
        detect_platform(system="Linux", bwrap_path="")


def test_detect_macos() -> None:
    profile = detect_platform(system="Darwin")
    assert profile.name == "macos-sandbox-exec"
    assert profile.system == "Darwin"
    assert profile.backend_binary is None
    assert profile.is_macos
    assert not profile.is_linux


def test_detect_unsupported_os_raises() -> None:
    with pytest.raises(SandboxUnavailableError, match="Linux and macOS"):
        detect_platform(system="Windows")


def test_detect_freebsd_raises() -> None:
    with pytest.raises(SandboxUnavailableError):
        detect_platform(system="FreeBSD")
