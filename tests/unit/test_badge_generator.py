"""Tests for ``wake adapter badge`` SVG/markdown generator."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from wake.cli.badge import adapter_badge_app, render_markdown, render_svg


def test_render_svg_full_score_green() -> None:
    """Score == max produces green badge (#4c1)."""
    svg = render_svg("claude-sdk", 10, 10)
    assert "<svg" in svg
    assert "wake claude-sdk" in svg
    assert "10/10" in svg
    assert "#4c1" in svg


def test_render_svg_partial_score_yellow() -> None:
    """Score in 70-99% range produces yellow badge."""
    svg = render_svg("foo", 8, 10)
    assert "8/10" in svg
    assert "#dfb317" in svg


def test_render_svg_low_score_red() -> None:
    """Score < 70% produces red badge."""
    svg = render_svg("foo", 5, 10)
    assert "5/10" in svg
    assert "#e05d44" in svg


def test_render_markdown_includes_catalog_url() -> None:
    """Markdown snippet links to catalog detail page + badge SVG."""
    md = render_markdown("claude-sdk", "claude-sdk", 10, 10)
    assert "catalog.wake.dev" in md
    assert "claude-sdk.svg" in md
    assert "/adapters/claude-sdk/" in md


def test_cli_generates_svg_to_stdout() -> None:
    """`wake adapter badge --name X --score 10` prints SVG."""
    runner = CliRunner()
    result = runner.invoke(adapter_badge_app, ["-n", "claude-sdk", "-s", "10"])
    assert result.exit_code == 0, result.output
    assert "<svg" in result.stdout
    assert "wake claude-sdk" in result.stdout
    assert "10/10" in result.stdout


def test_cli_generates_svg_to_file(tmp_path: Path) -> None:
    """--output writes SVG to file."""
    out = tmp_path / "badge.svg"
    runner = CliRunner()
    result = runner.invoke(
        adapter_badge_app,
        ["-n", "langgraph", "-s", "10", "-o", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    content = out.read_text()
    assert "<svg" in content
    assert "wake langgraph" in content


def test_cli_custom_max_score() -> None:
    """--max changes the denominator in score text."""
    runner = CliRunner()
    result = runner.invoke(
        adapter_badge_app,
        ["-n", "custom", "-s", "5", "-m", "7"],
    )
    assert result.exit_code == 0, result.output
    assert "5/7" in result.stdout
