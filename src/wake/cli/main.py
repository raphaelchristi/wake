"""Wake CLI entry point.

Run with ``wake --help`` after ``pip install -e .``. Talks to a Wake
server at ``$WAKE_SERVER`` (default ``http://localhost:8080``).

Command groups
--------------

* ``server``        — start the Wake API server locally (uvicorn).
* ``worker``        — run a headless Wake worker (drains sessions).
* ``agent``         — CRUD on agents.
* ``environment``   — CRUD on environments.
* ``session``       — CRUD on sessions + send/stream/events/interrupt.
* ``run``           — one-shot ephemeral agent → message → stream.

Design choices
--------------

* Typer for the CLI shell (decorator-based, comes with Click + Rich).
* ``rich`` for all stdout — colours degrade gracefully on dumb terms.
* Every subcommand resolves the server URL through ``WAKE_SERVER`` env
  with a ``--server`` flag for one-off overrides.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
import subprocess
import sys
import time
from typing import TYPE_CHECKING, Annotated

import typer

from wake import __version__
from wake.cli.client import WakeAPIError, WakeClient, resolve_server, stream_events
from wake.cli.formatters import (
    console,
    error_console,
    render_agents,
    render_detail,
    render_environments,
    render_event_line,
    render_events_table,
    render_run_event,
    render_sessions,
)

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Top-level app
# ---------------------------------------------------------------------------


app = typer.Typer(
    name="wake",
    help="Wake — durable runtime substrate for AI agents.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=False,
)

agent_app = typer.Typer(help="Manage agents.", no_args_is_help=True)
environment_app = typer.Typer(help="Manage environments.", no_args_is_help=True)
session_app = typer.Typer(help="Manage sessions.", no_args_is_help=True)

# Phase 7 — retention helpers (compact + archive).
from wake.cli.retention import events_app  # noqa: E402

# Phase 8 — dataset-driven evaluation framework.
from wake.cli.eval import eval_app  # noqa: E402

app.add_typer(agent_app, name="agent")
app.add_typer(environment_app, name="environment")
app.add_typer(session_app, name="session")
app.add_typer(events_app, name="events")
app.add_typer(eval_app, name="eval")


# ---------------------------------------------------------------------------
# Shared options
# ---------------------------------------------------------------------------

ServerOption = Annotated[
    str | None,
    typer.Option(
        "--server",
        help="Wake server URL. Defaults to $WAKE_SERVER or http://localhost:8080.",
        envvar="WAKE_SERVER",
        show_envvar=True,
    ),
]


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"wake {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option("--version", "-V", help="Show wake version and exit.", callback=_version_callback, is_eager=True),
    ] = False,
) -> None:
    """Wake CLI root callback (handles ``--version``)."""
    # Nothing else to do here — the callback exists purely so Typer
    # registers the global ``--version`` flag.
    _ = version


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client(server: str | None) -> WakeClient:
    return WakeClient(base_url=server)


def _abort(message: str, code: int = 1) -> None:
    """Print an error to stderr and exit with the given code."""
    error_console.print(f"[bold red]error:[/bold red] {message}")
    raise typer.Exit(code=code)


def _handle_api_error(exc: WakeAPIError) -> None:
    _abort(str(exc), code=2)


def _emit_resource(
    label: str,
    resource: dict[str, object],
    *,
    output_json: bool = False,
    id_only: bool = False,
) -> None:
    """Print a freshly-created resource according to user preferences.

    ``--id-only`` and ``--json`` give callers a script-friendly output
    so example shell scripts (and downstream automation) don't have to
    parse the rich-rendered panel. Default remains the human-readable
    panel + a ``→ created`` summary line.
    """
    if id_only:
        rid = resource.get("id", "")
        # Plain print (no rich markup, no colour) so subshell capture
        # sees only the ID.
        print(rid)
        return
    if output_json:
        import json as _json

        print(_json.dumps(resource, default=str))
        return
    render_detail(label, resource)
    rid = resource.get("id")
    if rid:
        console.print(
            f"[dim]→ created {label.lower()}[/dim] [bold cyan]{rid}[/bold cyan]"
        )


# ---------------------------------------------------------------------------
# `wake server`
# ---------------------------------------------------------------------------


@app.command()
def server(
    local: Annotated[
        bool,
        typer.Option("--local", help="Bind to 127.0.0.1 with a single worker (dev mode)."),
    ] = False,
    host: Annotated[
        str,
        typer.Option("--host", help="Host interface to bind."),
    ] = "0.0.0.0",
    port: Annotated[
        int,
        typer.Option("--port", help="Port to bind."),
    ] = 8080,
    reload: Annotated[
        bool,
        typer.Option("--reload", help="Reload on code changes (dev only)."),
    ] = False,
) -> None:
    """Start the Wake API server (uvicorn pointed at ``wake.api.app:app``).

    With ``--local``, binds to 127.0.0.1 with reload disabled — the
    recommended mode for trying out the examples.
    """
    bind_host = "127.0.0.1" if local else host
    try:
        import uvicorn  # local import — avoids loading FastAPI on every CLI call
    except ImportError:  # pragma: no cover — dev install always has uvicorn
        _abort(
            "uvicorn is not installed. Install with `pip install 'wake-ai[dev]'` or `pip install uvicorn[standard]`."
        )

    console.print(
        f"[bold cyan]wake[/bold cyan] starting server at "
        f"[underline]http://{bind_host}:{port}[/underline]"
    )
    console.print("[dim]press Ctrl+C to stop[/dim]")
    # We point uvicorn at the async factory in ``wake.api.bootstrap`` so
    # the module-level ``wake.api.app:app`` (which is intentionally empty
    # to keep imports cheap) is never used in production. ``--reload``
    # requires an import string, so we pass the factory through one too.
    try:
        uvicorn.run(  # type: ignore[no-untyped-call]
            "wake.api.bootstrap:create_production_app",
            host=bind_host,
            port=port,
            reload=reload,
            log_level="info",
            factory=True,
        )
    except KeyboardInterrupt:  # pragma: no cover — interactive
        console.print("\n[dim]server stopped[/dim]")
    except ModuleNotFoundError as exc:
        _abort(
            f"Server module not found: {exc.name}. The runtime slice "
            "(wake.api.bootstrap) must be installed alongside the CLI."
        )


# ---------------------------------------------------------------------------
# `wake worker`
# ---------------------------------------------------------------------------


@app.command()
def worker(
    concurrency: Annotated[
        int,
        typer.Option(
            "--concurrency",
            "-c",
            min=1,
            help="Maximum number of sessions to dispatch concurrently per worker.",
        ),
    ] = 1,
    database_url: Annotated[
        str | None,
        typer.Option(
            "--database-url",
            help="SQLAlchemy DSN. Defaults to $WAKE_DATABASE_URL.",
            envvar="WAKE_DATABASE_URL",
            show_envvar=True,
        ),
    ] = None,
    worker_id: Annotated[
        str | None,
        typer.Option(
            "--worker-id",
            help="Stable worker identifier (defaults to a fresh ULID).",
        ),
    ] = None,
    poll_interval: Annotated[
        float,
        typer.Option(
            "--poll-interval",
            help="Seconds between store polls when idle.",
        ),
    ] = 1.0,
) -> None:
    """Run a headless Wake worker.

    The worker connects to the configured store (Postgres in production,
    SQLite in dev), discovers harness adapters via Python entry points,
    and drives ``running`` sessions through ``SessionDispatcher.run_step``
    one step at a time. Multiple workers can run safely against the same
    Postgres store thanks to ``pg_try_advisory_lock`` claiming.

    Stop the worker with SIGTERM or SIGINT — the loop will drain
    in-flight sessions before exiting.
    """

    async def _entrypoint() -> None:
        from wake.api.bootstrap import build_components
        from wake.runtime.worker import WakeWorker, install_signal_handlers

        components = await build_components(dsn=database_url)
        wk = WakeWorker(
            store=components["store"],
            dispatcher=components["dispatcher"],
            concurrency=concurrency,
            worker_id=worker_id,
            poll_interval_s=poll_interval,
        )
        loop = asyncio.get_running_loop()
        install_signal_handlers(loop, wk)
        console.print(
            f"[bold cyan]wake[/bold cyan] worker "
            f"[dim]id=[/dim][cyan]{wk.worker_id}[/cyan] "
            f"[dim]concurrency=[/dim]{concurrency}"
        )
        try:
            await wk.run()
        finally:
            import contextlib as _contextlib

            close = getattr(components["store"], "close", None)
            if close is not None:
                with _contextlib.suppress(Exception):
                    await close()

    try:
        asyncio.run(_entrypoint())
    except KeyboardInterrupt:  # pragma: no cover — interactive
        console.print("\n[dim]worker stopped[/dim]")


# ---------------------------------------------------------------------------
# `wake agent`
# ---------------------------------------------------------------------------


@agent_app.command("create")
def agent_create(
    name: Annotated[str, typer.Option("--name", help="Agent name.")],
    model: Annotated[str, typer.Option("--model", help="Model id, e.g. claude-opus-4-7.")],
    system: Annotated[str | None, typer.Option("--system", help="System prompt.")] = None,
    tools: Annotated[
        str | None,
        typer.Option("--tools", help="Comma-separated tool types, e.g. bash,file_read."),
    ] = None,
    description: Annotated[str | None, typer.Option("--description")] = None,
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the raw JSON object instead of a pretty panel."),
    ] = False,
    id_only: Annotated[
        bool,
        typer.Option("--id-only", help="Print just the agent ID — handy for shell scripting."),
    ] = False,
    server: ServerOption = None,
) -> None:
    """Create a new agent and print its ID."""
    tool_list = [t.strip() for t in tools.split(",")] if tools else None
    with _client(server) as client:
        try:
            agent = client.create_agent(
                name=name,
                model=model,
                system=system,
                tools=tool_list,
                description=description,
            )
        except WakeAPIError as exc:
            _handle_api_error(exc)
            return
    _emit_resource("Agent", agent, output_json=output_json, id_only=id_only)


@agent_app.command("list")
def agent_list(server: ServerOption = None) -> None:
    """List all agents on the server."""
    with _client(server) as client:
        try:
            agents = client.list_agents()
        except WakeAPIError as exc:
            _handle_api_error(exc)
            return
    render_agents(agents)


@agent_app.command("get")
def agent_get(
    agent_id: Annotated[str, typer.Argument(help="Agent ID.")],
    server: ServerOption = None,
) -> None:
    """Show a single agent's full config."""
    with _client(server) as client:
        try:
            agent = client.get_agent(agent_id)
        except WakeAPIError as exc:
            _handle_api_error(exc)
            return
    render_detail("Agent", agent)


@agent_app.command("archive")
def agent_archive(
    agent_id: Annotated[str, typer.Argument(help="Agent ID.")],
    server: ServerOption = None,
) -> None:
    """Archive an agent (soft delete)."""
    with _client(server) as client:
        try:
            agent = client.archive_agent(agent_id)
        except WakeAPIError as exc:
            _handle_api_error(exc)
            return
    console.print(f"[yellow]archived[/yellow] agent {agent_id}")
    if agent:
        render_detail("Agent", agent)


# ---------------------------------------------------------------------------
# `wake environment`
# ---------------------------------------------------------------------------


@environment_app.command("create")
def environment_create(
    name: Annotated[str, typer.Option("--name", help="Environment name.")],
    config: Annotated[
        Path | None,
        typer.Option("--config", help="Path to a YAML file with the environment config."),
    ] = None,
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the raw JSON object instead of a pretty panel."),
    ] = False,
    id_only: Annotated[
        bool,
        typer.Option("--id-only", help="Print just the environment ID."),
    ] = False,
    server: ServerOption = None,
) -> None:
    """Create an environment, optionally loading config from a YAML file."""
    cfg: dict[str, object] | None = None
    if config is not None:
        cfg = _load_yaml(config)
        # Allow the user to pass either the bare environment config or
        # a doc with a top-level `environment:` key (matching wake.yaml).
        if isinstance(cfg, dict) and "environment" in cfg and isinstance(cfg["environment"], dict):
            cfg = cfg["environment"]
    with _client(server) as client:
        try:
            env = client.create_environment(name=name, config=cfg or {})
        except WakeAPIError as exc:
            _handle_api_error(exc)
            return
    _emit_resource("Environment", env, output_json=output_json, id_only=id_only)


@environment_app.command("list")
def environment_list(server: ServerOption = None) -> None:
    """List environments."""
    with _client(server) as client:
        try:
            envs = client.list_environments()
        except WakeAPIError as exc:
            _handle_api_error(exc)
            return
    render_environments(envs)


@environment_app.command("get")
def environment_get(
    env_id: Annotated[str, typer.Argument(help="Environment ID.")],
    server: ServerOption = None,
) -> None:
    """Show one environment's config."""
    with _client(server) as client:
        try:
            env = client.get_environment(env_id)
        except WakeAPIError as exc:
            _handle_api_error(exc)
            return
    render_detail("Environment", env)


# ---------------------------------------------------------------------------
# `wake session`
# ---------------------------------------------------------------------------


@session_app.command("create")
def session_create(
    agent: Annotated[str, typer.Option("--agent", help="Agent ID.")],
    environment: Annotated[
        str | None, typer.Option("--environment", help="Environment ID (optional).")
    ] = None,
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Emit the raw JSON object instead of a pretty panel."),
    ] = False,
    id_only: Annotated[
        bool,
        typer.Option("--id-only", help="Print just the session ID."),
    ] = False,
    server: ServerOption = None,
) -> None:
    """Create a new session for the given agent."""
    with _client(server) as client:
        try:
            session = client.create_session(agent_id=agent, environment_id=environment)
        except WakeAPIError as exc:
            _handle_api_error(exc)
            return
    _emit_resource("Session", session, output_json=output_json, id_only=id_only)


@session_app.command("list")
def session_list(server: ServerOption = None) -> None:
    """List all sessions."""
    with _client(server) as client:
        try:
            sessions = client.list_sessions()
        except WakeAPIError as exc:
            _handle_api_error(exc)
            return
    render_sessions(sessions)


@session_app.command("get")
def session_get(
    session_id: Annotated[str, typer.Argument(help="Session ID.")],
    server: ServerOption = None,
) -> None:
    """Show one session's status."""
    with _client(server) as client:
        try:
            session = client.get_session(session_id)
        except WakeAPIError as exc:
            _handle_api_error(exc)
            return
    render_detail("Session", session)


@session_app.command("send")
def session_send(
    session_id: Annotated[str, typer.Argument(help="Session ID.")],
    message: Annotated[str, typer.Argument(help="Message text.")],
    server: ServerOption = None,
) -> None:
    """Send a ``user.message`` to a session (does not wait for the response)."""
    with _client(server) as client:
        try:
            event = client.send_message(session_id, message)
        except WakeAPIError as exc:
            _handle_api_error(exc)
            return
    if event:
        seq = event.get("seq")
        seq_str = f" (seq {seq})" if isinstance(seq, int) else ""
        console.print(f"[green]→[/green] event sent{seq_str}")


@session_app.command("events")
def session_events(
    session_id: Annotated[str, typer.Argument(help="Session ID.")],
    event_type: Annotated[
        str | None, typer.Option("--type", help="Filter by event type.")
    ] = None,
    tool_only: Annotated[
        bool, typer.Option("--tool-only", help="Show only tool_use / tool_result events.")
    ] = False,
    server: ServerOption = None,
) -> None:
    """List events for a session as a table."""
    with _client(server) as client:
        try:
            events = client.list_events(session_id, event_type=event_type)
        except WakeAPIError as exc:
            _handle_api_error(exc)
            return
    if tool_only:
        events = [e for e in events if e.get("type") in {"tool_use", "tool_result"}]
    render_events_table(events)


@session_app.command("stream")
def session_stream(
    session_id: Annotated[str, typer.Argument(help="Session ID.")],
    follow: Annotated[
        bool, typer.Option("--follow", "-f", help="Keep the stream open after the turn completes."),
    ] = False,
    server: ServerOption = None,
) -> None:
    """Subscribe to a session's SSE stream and print events as they arrive."""
    base = resolve_server(server)
    console.print(f"[dim]streaming[/dim] {base}/v1/sessions/{session_id}/stream")
    try:
        asyncio.run(_stream_loop(base, session_id, follow=follow, render=render_event_line))
    except WakeAPIError as exc:
        _handle_api_error(exc)
    except KeyboardInterrupt:
        console.print("\n[dim]stream closed[/dim]")


@session_app.command("interrupt")
def session_interrupt(
    session_id: Annotated[str, typer.Argument(help="Session ID.")],
    server: ServerOption = None,
) -> None:
    """Interrupt a running session."""
    with _client(server) as client:
        try:
            client.interrupt_session(session_id)
        except WakeAPIError as exc:
            _handle_api_error(exc)
            return
    console.print(f"[yellow]interrupted[/yellow] {session_id}")


# ---------------------------------------------------------------------------
# `wake run` — one-shot flow
# ---------------------------------------------------------------------------


@app.command()
def run(
    message: Annotated[str, typer.Argument(help="User message to send.")],
    agent: Annotated[
        str | None,
        typer.Option("--agent", help="Existing agent ID or name. If omitted, an ephemeral agent is created."),
    ] = None,
    model: Annotated[
        str,
        typer.Option("--model", help="Model id (used when creating an ephemeral agent)."),
    ] = "claude-opus-4-7",
    system: Annotated[
        str | None,
        typer.Option("--system", help="System prompt for the ephemeral agent."),
    ] = None,
    tools: Annotated[
        str | None,
        typer.Option("--tools", help="Comma-separated tool list for the ephemeral agent."),
    ] = None,
    server: ServerOption = None,
) -> None:
    """One-shot: create agent + session, send message, stream the answer, exit.

    The recommended way to try Wake. With no flags, you get a quick
    ephemeral agent for the given model — no resources stick around in
    the catalog you'd want to clean up later.
    """
    base = resolve_server(server)
    tool_list = [t.strip() for t in tools.split(",")] if tools else None

    with _client(server) as client:
        # Step 1: agent — reuse if --agent is given.
        try:
            agent_id = _resolve_or_create_agent(
                client,
                explicit=agent,
                model=model,
                system=system,
                tools=tool_list,
            )
        except WakeAPIError as exc:
            _handle_api_error(exc)
            return

        # Step 2: session.
        try:
            session = client.create_session(agent_id=agent_id)
        except WakeAPIError as exc:
            _handle_api_error(exc)
            return
        session_id = session.get("id")
        if not session_id:
            _abort("server returned a session without an id")
            return

        console.print(
            f"[dim]session[/dim] [bold cyan]{session_id}[/bold cyan] "
            f"[dim]on agent[/dim] [cyan]{agent_id}[/cyan]"
        )

        # Step 3: send + stream. We send the message FIRST, then attach
        # the stream — the server is expected to retain events so we
        # don't miss any (this matches the SSE Last-Event-ID model).
        try:
            client.send_message(session_id, message)
        except WakeAPIError as exc:
            _handle_api_error(exc)
            return

    try:
        asyncio.run(_stream_loop(base, session_id, follow=False, render=render_run_event))
    except WakeAPIError as exc:
        _handle_api_error(exc)
    except KeyboardInterrupt:
        console.print("\n[dim]interrupted[/dim]")
    console.print()  # final newline so the prompt comes back cleanly


def _resolve_or_create_agent(
    client: WakeClient,
    *,
    explicit: str | None,
    model: str,
    system: str | None,
    tools: list[str] | None,
) -> str:
    """Pick an existing agent or create an ephemeral one.

    ``explicit`` may be an ID or a name. We try ``get`` first (cheap),
    and fall back to scanning ``list`` for a name match before giving
    up and creating a new agent.
    """
    if explicit:
        # Try direct ID lookup.
        try:
            agent = client.get_agent(explicit)
        except WakeAPIError as exc:
            if exc.status_code != 404:
                raise
            agent = None
        if agent and agent.get("id"):
            return str(agent["id"])
        # Fall back to name lookup.
        for candidate in client.list_agents():
            if candidate.get("name") == explicit:
                cid = candidate.get("id")
                if cid:
                    return str(cid)
        _abort(f"agent {explicit!r} not found (and refusing to create one named like an ID)")
    # Ephemeral path.
    agent = client.create_agent(
        name=f"wake-run-{int(time.time())}",
        model=model,
        system=system,
        tools=tools,
        description="ephemeral agent created by `wake run`",
    )
    agent_id = agent.get("id")
    if not agent_id:
        _abort("server returned an agent without an id")
    return str(agent_id)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


async def _stream_loop(
    base: str,
    session_id: str,
    *,
    follow: bool,
    render: object,
) -> None:
    """Drive the SSE stream and dispatch each event to ``render``.

    ``render`` may return ``True`` to signal an early stop; otherwise we
    only exit when the server closes the stream (or, with ``--follow``,
    on Ctrl+C).
    """
    async for event in stream_events(base, session_id):
        # render is either render_event_line (returns None) or
        # render_run_event (returns bool).
        if callable(render):
            result = render(event)  # type: ignore[operator]
            if result is True and not follow:
                return


def _load_yaml(path: Path) -> dict[str, object]:
    """Load a YAML file into a dict. Surfaced as a helper so tests can
    stub it; ``pyyaml`` is a hard dep so import-time failures should
    never happen in a properly installed environment."""
    import yaml

    if not path.exists():
        _abort(f"config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if data is None:
        return {}
    if not isinstance(data, dict):
        _abort(f"config file {path} must be a mapping, got {type(data).__name__}")
    return data


# ---------------------------------------------------------------------------
# Misc utilities used by examples/tests
# ---------------------------------------------------------------------------


def wait_for_server(url: str, *, timeout: float = 30.0) -> bool:
    """Poll ``url`` until it responds 2xx (used by example scripts).

    Returns ``True`` if the server became responsive within ``timeout``
    seconds, ``False`` otherwise.
    """
    deadline = time.monotonic() + timeout
    with WakeClient(url) as client:
        while time.monotonic() < deadline:
            try:
                client.health()
                return True
            except WakeAPIError:
                return True  # server replied — health endpoint just isn't there
            except Exception:  # noqa: BLE001 — connection refused, etc.
                time.sleep(0.25)
    return False


def _exec_self() -> str:
    """Locate the ``wake`` executable for child-process invocations."""
    candidate = shutil.which("wake")
    return candidate or sys.executable + " -m wake.cli.main"


def _stop_subprocess(proc: subprocess.Popen[bytes]) -> None:  # pragma: no cover
    """Terminate a child server process cleanly; used by integration helpers."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        proc.terminate()
    else:
        proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


if __name__ == "__main__":  # pragma: no cover
    app()
