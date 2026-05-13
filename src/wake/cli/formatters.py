"""Rich-based output formatters for the Wake CLI.

Two responsibilities:

1. Render table views for ``wake agent/environment/session list`` and
   ``wake session events``.
2. Render colourful per-event streams for ``wake session stream`` and
   ``wake run``.

Formatters are deliberately tolerant of partial event shapes — Phase 1
events may not yet carry every field — so missing keys never raise.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

console = Console()
"""Shared console — one instance per CLI invocation."""
error_console = Console(stderr=True, style="red")
"""Stderr console for errors and warnings, in red."""


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def render_agents(agents: Iterable[dict[str, Any]]) -> None:
    """Pretty-print a list of agents as a table."""
    table = Table(title="Agents", show_lines=False)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="bold")
    table.add_column("Model", style="green")
    table.add_column("Tools", style="yellow")
    table.add_column("Version", justify="right")
    table.add_column("Status")
    rows = 0
    for agent in agents:
        model = _extract_model(agent)
        tools = _extract_tool_names(agent.get("tools") or [])
        status = "archived" if agent.get("archived_at") else "active"
        table.add_row(
            str(agent.get("id", "-")),
            str(agent.get("name", "-")),
            model,
            ", ".join(tools) if tools else "-",
            str(agent.get("version", 1)),
            status,
        )
        rows += 1
    if rows == 0:
        console.print("[dim]No agents yet. Try `wake agent create --name hello --model claude-opus-4-7`.[/dim]")
        return
    console.print(table)


def render_environments(envs: Iterable[dict[str, Any]]) -> None:
    table = Table(title="Environments", show_lines=False)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="bold")
    table.add_column("Backend", style="green")
    table.add_column("Status")
    rows = 0
    for env in envs:
        config = env.get("config") or {}
        sandbox = config.get("sandbox") if isinstance(config, dict) else None
        backend = "-"
        if isinstance(sandbox, dict):
            backend = str(sandbox.get("backend", "-"))
        status = "archived" if env.get("archived_at") else "active"
        table.add_row(
            str(env.get("id", "-")),
            str(env.get("name", "-")),
            backend,
            status,
        )
        rows += 1
    if rows == 0:
        console.print("[dim]No environments yet.[/dim]")
        return
    console.print(table)


def render_sessions(sessions: Iterable[dict[str, Any]]) -> None:
    table = Table(title="Sessions", show_lines=False)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Agent", style="bold")
    table.add_column("Status", style="green")
    table.add_column("Container")
    table.add_column("Updated", style="dim")
    rows = 0
    for session in sessions:
        table.add_row(
            str(session.get("id", "-")),
            str(session.get("agent_id", "-")),
            str(session.get("status", "-")),
            str(session.get("container_id") or "-"),
            str(session.get("updated_at") or "-"),
        )
        rows += 1
    if rows == 0:
        console.print("[dim]No sessions yet.[/dim]")
        return
    console.print(table)


def render_events_table(events: Iterable[dict[str, Any]]) -> None:
    """Render an event log as a compact table.

    Used by ``wake session events <id>``. For live streaming we use
    :func:`render_event_line` instead, which writes one line per event.
    """
    table = Table(title="Events", show_lines=False)
    table.add_column("Seq", justify="right", style="dim")
    table.add_column("Type", style="cyan")
    table.add_column("Summary")
    table.add_column("Created", style="dim")
    rows = 0
    for event in events:
        table.add_row(
            str(event.get("seq", "-")),
            str(event.get("type", "-")),
            _summarise_payload(event.get("type"), event.get("payload") or {}),
            str(event.get("created_at") or "-"),
        )
        rows += 1
    if rows == 0:
        console.print("[dim]No events for this session.[/dim]")
        return
    console.print(table)


def render_detail(title: str, obj: dict[str, Any]) -> None:
    """Render a single object (agent/env/session) as a key-value panel."""
    if not obj:
        console.print(f"[dim]No {title.lower()} found.[/dim]")
        return
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")
    for key, value in obj.items():
        table.add_row(key, _format_value(value))
    console.print(Panel(table, title=title, title_align="left", border_style="cyan"))


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


_EVENT_STYLES: dict[str, str] = {
    "user.message": "bold magenta",
    "assistant.message": "bold green",
    "assistant.delta": "green",
    "assistant.thinking": "italic dim cyan",
    "tool_use": "bold yellow",
    "tool_result": "yellow",
    "status": "blue",
    "provision": "blue",
    "error": "bold red",
    "interrupt": "bold red",
    "artifact": "magenta",
    "vault.access": "cyan",
    "pause_turn": "dim",
}


def render_event_line(event: dict[str, Any]) -> None:
    """Render one event as a single (or multi-line) coloured block.

    ``event`` is the dict shape yielded by :func:`stream_events` —
    i.e. SSE-framed: keys ``id``, ``event``, ``data``. Falls back to
    treating the whole dict as a raw event if ``data`` is missing.
    """
    data = event.get("data") if "data" in event else event
    if not isinstance(data, dict):
        console.print(f"[dim]{escape(str(data))}[/dim]")
        return
    event_type = str(data.get("type") or event.get("event") or "?")
    style = _EVENT_STYLES.get(event_type, "white")
    seq = data.get("seq")
    prefix = f"[dim]seq {seq:>3}[/dim] " if isinstance(seq, int) else ""
    summary = _summarise_payload(event_type, data.get("payload") or {})
    console.print(f"{prefix}[{style}]{event_type:<22}[/{style}] {summary}")


def render_run_event(event: dict[str, Any]) -> bool:
    """Render an event for the cleaner ``wake run`` UX.

    Returns ``True`` when the event indicates the turn is complete and
    the caller should stop consuming the stream (assistant ``end_turn``
    or ``terminated``).
    """
    data = event.get("data") if "data" in event else event
    if not isinstance(data, dict):
        return False
    event_type = str(data.get("type") or event.get("event") or "")
    payload = data.get("payload") or {}

    if event_type == "assistant.delta":
        # Stream partial text inline, without a newline, so it reads
        # like one continuous assistant response.
        text = _extract_text(payload)
        if text:
            console.print(text, end="", style="green", soft_wrap=True, highlight=False)
        return False

    if event_type == "assistant.message":
        text = _extract_text(payload)
        if text:
            # If we already streamed deltas, this final message may be a
            # duplicate — print on its own line to clarify boundary.
            console.print()
            console.print(text, style="bold green", soft_wrap=True, highlight=False)
        stop_reason = payload.get("stop_reason")
        return stop_reason == "end_turn"

    if event_type == "tool_use":
        name = payload.get("name", "?")
        tool_input = payload.get("input", {})
        snippet = _format_tool_input(tool_input)
        console.print()
        console.print(f"[bold yellow]tool[/bold yellow] [yellow]{escape(str(name))}[/yellow] {snippet}")
        return False

    if event_type == "tool_result":
        snippet = _summarise_tool_result(payload)
        console.print(f"[dim yellow]→[/dim yellow] {snippet}")
        return False

    if event_type == "assistant.thinking":
        text = _extract_text(payload)
        if text:
            console.print(f"[italic dim cyan]thinking:[/italic dim cyan] [dim]{escape(text)}[/dim]")
        return False

    if event_type == "error":
        msg = payload.get("message") or payload.get("error") or "unknown error"
        console.print(f"[bold red]error:[/bold red] {escape(str(msg))}")
        return True

    if event_type == "status":
        new_status = payload.get("status") or payload.get("to")
        if new_status == "terminated":
            return True
        return False

    return False


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _extract_model(agent: dict[str, Any]) -> str:
    model = agent.get("model")
    if isinstance(model, dict):
        return str(model.get("id", "-"))
    if isinstance(model, str):
        return model
    return "-"


def _extract_tool_names(tools: Iterable[Any]) -> list[str]:
    names: list[str] = []
    for tool in tools:
        if isinstance(tool, dict):
            names.append(str(tool.get("type", "?")))
        elif isinstance(tool, str):
            names.append(tool)
    return names


def _summarise_payload(event_type: str | None, payload: dict[str, Any]) -> str:
    """Cheap, lossy one-line summary of an event payload.

    Designed for table rows — see ``render_event_line`` for richer
    multi-line rendering.
    """
    if not isinstance(payload, dict):
        return escape(str(payload))[:120]
    match event_type:
        case "user.message" | "assistant.message":
            text = _extract_text(payload)
            return escape(text[:120]) if text else "(empty)"
        case "assistant.delta":
            text = _extract_text(payload)
            return escape(text[:120]) if text else "(delta)"
        case "tool_use":
            name = payload.get("name", "?")
            snippet = _format_tool_input(payload.get("input", {}))
            return f"{escape(str(name))} {snippet}"
        case "tool_result":
            return _summarise_tool_result(payload)
        case "status":
            from_ = payload.get("from") or payload.get("prev")
            to_ = payload.get("to") or payload.get("status")
            if from_ and to_:
                return f"{from_} → {to_}"
            return escape(str(to_ or payload))
        case "error":
            return escape(str(payload.get("message") or payload.get("error") or payload))[:120]
        case _:
            return escape(str(payload))[:120]


def _extract_text(payload: dict[str, Any]) -> str:
    """Pull a printable text blob out of an Anthropic-shaped payload.

    Handles three shapes we expect on the wire:

    * ``{"content": [{"type": "text", "text": "..."}, ...]}``
    * ``{"text": "..."}``
    * ``{"delta": "..."}``
    """
    if "text" in payload and isinstance(payload["text"], str):
        return payload["text"]
    if "delta" in payload and isinstance(payload["delta"], str):
        return payload["delta"]
    content = payload.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return "".join(parts)
    if isinstance(content, str):
        return content
    return ""


def _format_tool_input(tool_input: Any) -> str:
    """Render a tool's input compactly for a one-line summary."""
    if not isinstance(tool_input, dict):
        return escape(str(tool_input))[:80]
    # Special-case common shapes for readability.
    if "command" in tool_input:
        return f"[dim]$[/dim] {escape(str(tool_input['command']))[:80]}"
    if "path" in tool_input:
        return f"[dim]{escape(str(tool_input['path']))}[/dim]"
    parts = [f"{k}={_short(v)}" for k, v in list(tool_input.items())[:3]]
    return " ".join(parts)


def _summarise_tool_result(payload: dict[str, Any]) -> str:
    is_error = bool(payload.get("is_error"))
    content = payload.get("content")
    text = ""
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text")
                if isinstance(t, str):
                    text = t
                    break
    elif isinstance(content, str):
        text = content
    snippet = escape(text.strip().splitlines()[0][:100]) if text.strip() else "(empty)"
    if is_error:
        return f"[red]error:[/red] {snippet}"
    return snippet


def _format_value(value: Any) -> str:
    if value is None:
        return "[dim]null[/dim]"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list | dict):
        return escape(str(value))[:200]
    return escape(str(value))


def _short(value: Any) -> str:
    s = str(value)
    return s if len(s) <= 30 else s[:27] + "..."


__all__ = [
    "console",
    "error_console",
    "render_agents",
    "render_detail",
    "render_environments",
    "render_event_line",
    "render_events_table",
    "render_run_event",
    "render_sessions",
]
