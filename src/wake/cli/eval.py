"""``wake eval`` CLI — drive datasets through a Wake agent.

Subcommands
-----------

* ``wake eval run``     run a dataset against an agent, write report
* ``wake eval list``    print the names of registered scorers
* ``wake eval show``    pretty-print a previously saved JSON report

By default ``run`` produces both a markdown summary (``--output``) and
a JSON dump (``--json-output``). When neither is given, markdown goes
to stdout. The CLI talks to the Wake API server through
:class:`wake.cli.client.WakeClient` so no foundation/runtime imports
leak into the CLI tree.
"""

# Typer parameter names overlap with builtins (``input``, ``id``);
# silencing the lint rule keeps the contract names readable.
# ruff: noqa: A002

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Annotated, Any

import typer

from wake.cli.client import WakeAPIError, WakeClient, resolve_server, stream_events
from wake.cli.formatters import console, error_console
from wake.eval.dataset import DatasetError, DatasetRow, load_jsonl
from wake.eval.report import to_markdown, write_json, write_markdown
from wake.eval.runner import AgentInvocation, EvalRunner
from wake.eval.scorer import default_registry

eval_app = typer.Typer(
    help="Run dataset-driven evaluations against a Wake agent.",
    no_args_is_help=True,
)


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


def _abort(message: str, code: int = 1) -> None:
    error_console.print(f"[bold red]error:[/bold red] {message}")
    raise typer.Exit(code=code)


# ---------------------------------------------------------------------------
# Invocation helpers — translate a DatasetRow into a session + stream
# ---------------------------------------------------------------------------


def _row_text(row: DatasetRow) -> str:
    """Extract the user-message text from a row's ``input``.

    A row may carry either a plain string or a structured object. We
    keep the rule simple so authors don't have to learn a schema.
    """
    raw = row.input
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        if isinstance(raw.get("text"), str):
            return raw["text"]
        # Anthropic-style messages array.
        messages = raw.get("messages")
        if isinstance(messages, list):
            for m in messages:
                if isinstance(m, dict) and m.get("role") in {"user", "human"}:
                    content = m.get("content")
                    if isinstance(content, str):
                        return content
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and isinstance(block.get("text"), str):
                                return block["text"]
    return json.dumps(raw, default=str)


async def _consume_session(base_url: str, session_id: str, *, timeout_s: float) -> tuple[str, list[dict[str, Any]], float | None]:
    """Stream a session until end_turn / terminated and return text + events + cost.

    Returns ``(output_text, events, cost_usd)``. Cost is summed from
    any ``metadata.cost_usd`` we see on assistant.message events (the
    LiteLLM provider attaches it there).
    """
    output_chunks: list[str] = []
    events: list[dict[str, Any]] = []
    cost_total: float = 0.0
    have_cost = False
    deadline = asyncio.get_event_loop().time() + timeout_s

    async def _runner() -> None:
        nonlocal cost_total, have_cost
        async for evt in stream_events(base_url, session_id):
            events.append(evt)
            data = evt.get("data") if isinstance(evt.get("data"), dict) else evt
            if not isinstance(data, dict):
                continue
            ev_type = str(data.get("type") or evt.get("event") or "")
            payload = data.get("payload") or {}
            md = data.get("metadata") or payload.get("metadata") or {}
            if isinstance(md, dict):
                cost = md.get("cost_usd")
                if isinstance(cost, (int, float)):
                    cost_total += float(cost)
                    have_cost = True
            if ev_type == "assistant.message":
                output_chunks.append(_text_from_payload(payload))
                if payload.get("stop_reason") == "end_turn":
                    return
            elif ev_type == "status":
                status = payload.get("status") or payload.get("to")
                if status == "terminated":
                    return
            elif ev_type == "error":
                msg = payload.get("message") or payload.get("error") or "unknown error"
                raise RuntimeError(str(msg))

    try:
        await asyncio.wait_for(_runner(), timeout=max(0.01, deadline - asyncio.get_event_loop().time()))
    except asyncio.TimeoutError as exc:
        raise RuntimeError(f"timed out waiting for session {session_id} after {timeout_s}s") from exc

    return "\n".join(c for c in output_chunks if c), events, (cost_total if have_cost else None)


def _text_from_payload(payload: dict[str, Any]) -> str:
    content = payload.get("content")
    if isinstance(content, list):
        chunks = [
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and isinstance(b.get("text"), str)
        ]
        return "\n".join(c for c in chunks if c)
    if isinstance(content, str):
        return content
    return ""


def _make_http_invoke_fn(
    *,
    server: str,
    agent_id: str,
    environment_id: str | None,
    timeout_s: float,
):
    """Build an async invoke_fn that creates a session per row and
    consumes its stream until end_turn.

    Each row gets a fresh session so evals are independent — no
    cross-row context leakage.
    """

    base = resolve_server(server)

    async def _invoke(row: DatasetRow) -> AgentInvocation:
        text = _row_text(row)
        client = WakeClient(base_url=base, timeout=timeout_s)
        try:
            session = client.create_session(
                agent_id=agent_id,
                environment_id=environment_id,
                metadata={"wake_eval_row_id": row.row_id},
            )
            session_id = session.get("id")
            if not session_id:
                raise RuntimeError("server returned a session without an id")
            client.send_message(session_id, text)
        finally:
            client.close()

        t0 = time.perf_counter()
        output_text, events, cost_usd = await _consume_session(
            base, str(session_id), timeout_s=timeout_s
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return AgentInvocation(
            output=output_text,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            events=events,
            session_id=str(session_id),
        )

    return _invoke


# ---------------------------------------------------------------------------
# `wake eval run`
# ---------------------------------------------------------------------------


@eval_app.command("run")
def eval_run(
    dataset: Annotated[
        Path,
        typer.Option(
            "--dataset",
            "-d",
            help="Path to JSONL dataset (one row per line).",
        ),
    ],
    agent: Annotated[
        str,
        typer.Option(
            "--agent",
            "-a",
            help="Agent ID or name to evaluate.",
        ),
    ],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Where to write the markdown report. Default: stdout.",
        ),
    ] = None,
    json_output: Annotated[
        Path | None,
        typer.Option(
            "--json-output",
            help="Where to write the full JSON report.",
        ),
    ] = None,
    scorers: Annotated[
        str,
        typer.Option(
            "--scorers",
            help="Comma-separated default scorer names (rows may override via metadata.scorer).",
        ),
    ] = "exact_match",
    concurrency: Annotated[
        int,
        typer.Option(
            "--concurrency",
            "-c",
            min=1,
            help="Maximum number of rows in flight at once.",
        ),
    ] = 4,
    timeout: Annotated[
        float,
        typer.Option(
            "--timeout",
            min=1.0,
            help="Per-row timeout in seconds (covers session create + stream).",
        ),
    ] = 120.0,
    environment: Annotated[
        str | None,
        typer.Option(
            "--environment",
            help="Environment ID (optional).",
        ),
    ] = None,
    fail_under: Annotated[
        float | None,
        typer.Option(
            "--fail-under",
            help="Exit non-zero if accuracy drops below this threshold (0.0-1.0).",
        ),
    ] = None,
    server: ServerOption = None,
) -> None:
    """Run a dataset against a Wake agent and emit a markdown report."""
    # 1. Load dataset
    try:
        rows = load_jsonl(dataset)
    except DatasetError as exc:
        _abort(str(exc))
        return
    if not rows:
        _abort(f"dataset {dataset} is empty")
        return

    # 2. Resolve agent (allow name OR id, same as `wake run`)
    base = resolve_server(server)
    with WakeClient(base_url=base) as client:
        agent_id = _resolve_agent(client, agent)

    # 3. Build runner
    scorer_names = [s.strip() for s in scorers.split(",") if s.strip()]
    if not scorer_names:
        _abort("--scorers must list at least one scorer")
        return
    registry = default_registry()
    unknown = [s for s in scorer_names if s not in registry.names()]
    if unknown:
        _abort(
            f"unknown scorer(s) {unknown}; registered: {registry.names()}",
        )
        return

    invoke_fn = _make_http_invoke_fn(
        server=server or base,
        agent_id=agent_id,
        environment_id=environment,
        timeout_s=timeout,
    )
    runner = EvalRunner(
        invoke_fn=invoke_fn,
        scorers=scorer_names,
        concurrency=concurrency,
        registry=registry,
    )

    console.print(
        f"[bold cyan]wake eval[/bold cyan] dataset=[cyan]{dataset}[/cyan] "
        f"agent=[cyan]{agent_id}[/cyan] rows={len(rows)} "
        f"scorers={scorer_names} concurrency={concurrency}"
    )

    # 4. Execute
    try:
        report = asyncio.run(
            runner.run(rows, agent_id=agent_id, dataset_path=str(dataset))
        )
    except WakeAPIError as exc:
        _abort(str(exc), code=2)
        return

    # 5. Emit outputs
    if output is not None:
        write_markdown(report, output)
        console.print(f"[green]→[/green] markdown report: {output}")
    if json_output is not None:
        write_json(report, json_output)
        console.print(f"[green]→[/green] json report: {json_output}")
    if output is None and json_output is None:
        # No file destinations — dump markdown to stdout for piping.
        console.print()
        print(to_markdown(report), end="")

    # 6. Summary line + fail-under exit code
    console.print(
        f"[bold]done[/bold] passed={report.passed}/{report.total} "
        f"accuracy={report.accuracy*100:.1f}% "
        f"mean_score={report.mean_score:.3f} "
        f"duration={report.duration_s:.1f}s"
    )
    if fail_under is not None and report.accuracy < fail_under:
        _abort(
            f"accuracy {report.accuracy:.3f} below threshold {fail_under:.3f}",
            code=3,
        )


def _resolve_agent(client: WakeClient, ident: str) -> str:
    """Look up an agent by ID first, then by name. Aborts if neither hits."""
    try:
        candidate = client.get_agent(ident)
    except WakeAPIError as exc:
        if exc.status_code != 404:
            _abort(str(exc), code=2)
            return ident
        candidate = {}
    if candidate.get("id"):
        return str(candidate["id"])
    for entry in client.list_agents():
        if entry.get("name") == ident:
            cid = entry.get("id")
            if cid:
                return str(cid)
    _abort(f"agent {ident!r} not found")
    return ident  # unreachable


# ---------------------------------------------------------------------------
# `wake eval list`
# ---------------------------------------------------------------------------


@eval_app.command("list")
def eval_list() -> None:
    """List registered scorers (built-in + plugins)."""
    registry = default_registry()
    for name in registry.names():
        scorer = registry.get(name)
        cls_name = type(scorer).__name__
        console.print(f"- [bold]{name}[/bold] [dim]({cls_name})[/dim]")


# ---------------------------------------------------------------------------
# `wake eval show`
# ---------------------------------------------------------------------------


@eval_app.command("show")
def eval_show(
    report_path: Annotated[
        Path,
        typer.Argument(help="Path to a JSON report (the output of `wake eval run --json-output`)."),
    ],
) -> None:
    """Pretty-print a saved JSON eval report as a markdown summary."""
    if not report_path.exists():
        _abort(f"report not found: {report_path}")
        return
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _abort(f"invalid JSON in {report_path}: {exc}")
        return
    if not isinstance(data, dict):
        _abort(f"expected an object at the top of {report_path}")
        return
    # Reconstruct enough of the report to render markdown without
    # re-running anything. We use the same renderer for consistency.
    from wake.eval.dataset import DatasetRow as _Row
    from wake.eval.report import to_markdown as _to_markdown
    from wake.eval.runner import AgentInvocation as _Inv, EvalReport as _Report, RowReport as _RowReport
    from wake.eval.scorer import ScorerResult as _ScRes

    rows = []
    for r in data.get("rows", []):
        ds_row = _Row(
            row_id=r.get("row_id", ""),
            input=r.get("input"),
            expected=r.get("expected"),
            metadata=r.get("metadata", {}) or {},
            raw={},
        )
        inv_d = r.get("invocation")
        inv = None
        if isinstance(inv_d, dict):
            inv = _Inv(
                output=inv_d.get("output"),
                latency_ms=inv_d.get("latency_ms"),
                cost_usd=inv_d.get("cost_usd"),
                events=inv_d.get("events") or [],
                session_id=inv_d.get("session_id"),
                metadata=inv_d.get("metadata") or {},
            )
        scores = [
            _ScRes(
                name=s.get("name", ""),
                score=float(s.get("score", 0.0)),
                passed=bool(s.get("passed", False)),
                details=s.get("details", ""),
                metadata=s.get("metadata") or {},
            )
            for s in r.get("scores", [])
        ]
        rows.append(
            _RowReport(
                row_id=r.get("row_id", ""),
                row=ds_row,
                invocation=inv,
                scores=scores,
                error=r.get("error"),
            )
        )
    report = _Report(
        agent_id=str(data.get("agent_id", "")),
        dataset_path=str(data.get("dataset_path", "")),
        rows=rows,
        started_at=float(data.get("started_at") or 0.0),
        finished_at=float(data.get("finished_at") or 0.0),
        metadata=data.get("metadata") or {},
    )
    print(_to_markdown(report), end="")


__all__ = ["eval_app"]
