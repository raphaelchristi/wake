"""``wake adapter badge`` — generate conformance SVG badges.

Produces SVG snippet + Markdown embed code for adapter conformance results.

Phase 9 deliverable (Tier 3 gap #13).
"""

from __future__ import annotations

from pathlib import Path

import typer

_SVG_TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="20" role="img" aria-label="{label}: {score}">
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r"><rect width="{w}" height="20" rx="3" fill="#fff"/></clipPath>
  <g clip-path="url(#r)">
    <rect width="{label_w}" height="20" fill="#555"/>
    <rect x="{label_w}" width="{value_w}" height="20" fill="{color}"/>
    <rect width="{w}" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">
    <text x="{label_x}" y="15" fill="#010101" fill-opacity=".3">{label}</text>
    <text x="{label_x}" y="14">{label}</text>
    <text x="{value_x}" y="15" fill="#010101" fill-opacity=".3">{score}</text>
    <text x="{value_x}" y="14">{score}</text>
  </g>
</svg>
"""


def render_svg(name: str, score: int, max_score: int = 10) -> str:
    """Render an SVG badge string for a conformance score."""
    label = f"wake {name}"
    score_text = f"{score}/{max_score}"
    label_w = max(80, len(label) * 7)
    value_w = max(40, len(score_text) * 7 + 10)
    color = "#4c1" if score == max_score else "#dfb317" if score >= max_score * 0.7 else "#e05d44"
    return _SVG_TEMPLATE.format(
        w=label_w + value_w,
        label=label,
        label_w=label_w,
        value_w=value_w,
        label_x=label_w // 2,
        value_x=label_w + value_w // 2,
        color=color,
        score=score_text,
    )


def render_markdown(name: str, slug: str, score: int, max_score: int = 10) -> str:
    """Render the Markdown snippet adapter authors paste into their README."""
    return (
        f"[![Wake conformance {score}/{max_score}]"
        f"(https://catalog.wake.dev/badge/{slug}.svg)]"
        f"(https://catalog.wake.dev/adapters/{slug}/)"
    )


adapter_badge_app = typer.Typer(help="Generate conformance badges for adapter listings.")


@adapter_badge_app.callback(invoke_without_command=True)
def badge_main(
    name: str = typer.Option(..., "--name", "-n", help="Adapter name (e.g. claude-sdk)."),
    score: int = typer.Option(..., "--score", "-s", help="Conformance score (0-N)."),
    max_score: int = typer.Option(10, "--max", "-m", help="Max score (default 10)."),
    output: str | None = typer.Option(None, "--output", "-o", help="Write SVG to this file."),
) -> None:
    """Print SVG + Markdown badge for the adapter."""
    svg = render_svg(name, score, max_score)
    md = render_markdown(name, name, score, max_score)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(svg, encoding="utf-8")
        typer.echo(f"wrote {path}")
    else:
        typer.echo(svg)
    typer.echo("")
    typer.echo("# Markdown snippet")
    typer.echo(md)


__all__ = ["adapter_badge_app", "render_markdown", "render_svg"]
