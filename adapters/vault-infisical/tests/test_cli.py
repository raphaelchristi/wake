"""Tests for the ``wake vault`` Typer CLI.

Uses ``typer.testing.CliRunner`` plus the in-memory backend so no real
Infisical or browser is involved.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from wake_vault_infisical.cli import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner(mix_stderr=False)


def test_init_in_memory(runner: CliRunner) -> None:
    result = runner.invoke(app, ["init", "--in-memory"])
    assert result.exit_code == 0
    assert "vault ready" in result.stdout


def test_add_with_value(runner: CliRunner) -> None:
    result = runner.invoke(
        app,
        [
            "add",
            "github_token",
            "--provider",
            "github",
            "--value",
            "ghp_FAKE_TOKEN_FOR_TEST",
            "--in-memory",
        ],
    )
    assert result.exit_code == 0
    assert "stored" in result.stdout
    # CLI must not echo the value back.
    assert "ghp_FAKE_TOKEN_FOR_TEST" not in result.stdout


def test_add_via_prompt(runner: CliRunner) -> None:
    # When --value is omitted, the CLI prompts (hidden). Provide via stdin.
    result = runner.invoke(
        app,
        ["add", "secret_a", "--provider", "custom", "--in-memory"],
        input="my-prompt-value\n",
    )
    assert result.exit_code == 0
    # Prompted value also must not be echoed.
    assert "my-prompt-value" not in result.stdout


def test_list_empty(runner: CliRunner) -> None:
    result = runner.invoke(app, ["list", "--in-memory"])
    assert result.exit_code == 0


def test_remove_unknown_is_idempotent(runner: CliRunner) -> None:
    # Each CliRunner invocation builds a fresh in-memory vault — so
    # this id was never registered. Revoke must not error.
    result = runner.invoke(app, ["remove", "vault_does_not_exist", "--in-memory"])
    assert result.exit_code == 0
    assert "revoked" in result.stdout


def test_oauth_requires_client_credentials(runner: CliRunner) -> None:
    result = runner.invoke(
        app,
        [
            "add",
            "gh",
            "--provider",
            "github",
            "--oauth",
            "--in-memory",
        ],
    )
    # Typer reports BadParameter as exit code 2.
    assert result.exit_code != 0


def test_help_message_lists_commands(runner: CliRunner) -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("init", "add", "list", "remove"):
        assert cmd in result.stdout


def test_remove_unknown_does_not_print_secret(runner: CliRunner) -> None:
    """Just in case: ensure 'remove' command output never echoes a token-like string."""
    result = runner.invoke(app, ["remove", "vault_xxx", "--in-memory"])
    assert "ghp_" not in result.stdout
