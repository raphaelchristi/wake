"""Typer CLI — ``wake vault init/add/list/remove``.

This module is exported as a Typer ``app`` and registered under the
``wake.cli`` entry point group. The main Wake CLI loads it lazily so
that installing this package adds ``wake vault ...`` without any patch
to ``src/wake/cli/main.py``.

Commands
--------

* ``wake vault init``    — sanity-check the Infisical sidecar / fallback.
* ``wake vault add``     — interactive credential add (with optional OAuth flow).
* ``wake vault list``    — list known credentials (metadata only, no values).
* ``wake vault remove``  — revoke a credential by vault_id.

Design note: this CLI is intentionally **standalone** — it runs against
the local vault instance and never talks to the Wake server. That keeps
``wake vault`` usable on machines that don't run a Wake server at all
(e.g. an operator's laptop bootstrapping creds for production).
"""

from __future__ import annotations

import asyncio
import os
import webbrowser
from typing import Annotated, Any

import typer

from wake_vault_infisical.oauth import OAuthFlow, get_provider
from wake_vault_infisical.vault import InfisicalVault

# Console import is deferred so the module imports cleanly even on
# systems missing ``rich`` (it ships with typer but technically optional).
try:
    from rich.console import Console
    from rich.table import Table

    _console: Any = Console()
except ImportError:  # pragma: no cover — typer always pulls rich
    _console = None
    Console = None  # type: ignore[assignment,misc]
    Table = None  # type: ignore[assignment,misc]


app = typer.Typer(
    name="vault",
    help="Manage credentials in the Wake vault (Infisical).",
    no_args_is_help=True,
)


def _print(msg: str) -> None:
    """Print via rich if available, else plain stdout. Never prints secrets."""
    if _console is not None:
        _console.print(msg)
    else:
        print(msg)


def _build_vault(in_memory: bool = False) -> InfisicalVault:
    return InfisicalVault(in_memory=in_memory or not os.getenv("INFISICAL_TOKEN"))


# ---------------------------------------------------------------------------
# `wake vault init`
# ---------------------------------------------------------------------------


@app.command("init")
def init(
    in_memory: Annotated[
        bool,
        typer.Option("--in-memory", help="Use the in-memory fallback (dev only)."),
    ] = False,
) -> None:
    """Probe the vault and report whether it is reachable.

    Exits with 0 if the vault responds (or the in-memory fallback is
    active), 1 otherwise. Useful in CI to gate downstream commands.
    """
    vault = _build_vault(in_memory=in_memory)

    async def _check() -> int:
        try:
            await vault.list()
            mode = "in-memory" if vault.memory_backend is not None else "infisical"
            _print(f"[green]vault ready[/green] (mode={mode})")
            return 0
        except Exception as exc:  # noqa: BLE001 — top-level user-facing CLI
            _print(f"[red]vault init failed:[/red] {exc}")
            return 1
        finally:
            await vault.aclose()

    raise typer.Exit(code=asyncio.run(_check()))


# ---------------------------------------------------------------------------
# `wake vault add`
# ---------------------------------------------------------------------------


@app.command("add")
def add(
    name: Annotated[str, typer.Argument(help="Friendly name, e.g. github_token.")],
    provider: Annotated[
        str,
        typer.Option("--provider", help="OAuth provider (github|slack|notion|custom)."),
    ] = "custom",
    value: Annotated[
        str | None,
        typer.Option(
            "--value",
            help="Credential value. Omit to be prompted (hidden). Ignored if --oauth.",
        ),
    ] = None,
    oauth: Annotated[
        bool,
        typer.Option("--oauth", help="Run interactive OAuth flow against --provider."),
    ] = False,
    client_id: Annotated[
        str | None,
        typer.Option("--client-id", help="OAuth client_id (or $OAUTH_CLIENT_ID)."),
    ] = None,
    client_secret: Annotated[
        str | None,
        typer.Option("--client-secret", help="OAuth client_secret (or $OAUTH_CLIENT_SECRET)."),
    ] = None,
    redirect_uri: Annotated[
        str,
        typer.Option("--redirect-uri", help="OAuth redirect_uri."),
    ] = "http://localhost:8765/callback",
    scopes: Annotated[
        str | None,
        typer.Option("--scopes", help="Comma-separated scopes (overrides provider default)."),
    ] = None,
    in_memory: Annotated[
        bool,
        typer.Option("--in-memory", help="Use the in-memory fallback."),
    ] = False,
) -> None:
    """Store a credential. Either via ``--value`` or via interactive OAuth."""
    vault = _build_vault(in_memory=in_memory)
    scope_list = [s.strip() for s in scopes.split(",")] if scopes else None

    async def _run() -> None:
        try:
            if oauth:
                cid = client_id or os.getenv("OAUTH_CLIENT_ID", "")
                csec = client_secret or os.getenv("OAUTH_CLIENT_SECRET", "")
                if not cid or not csec:
                    raise typer.BadParameter(
                        "--oauth requires --client-id and --client-secret "
                        "(or OAUTH_CLIENT_ID / OAUTH_CLIENT_SECRET env vars)"
                    )
                # Validate provider name early.
                if provider != "custom":
                    get_provider(provider)
                flow = OAuthFlow.for_provider(
                    provider if provider != "custom" else "github",
                    client_id=cid,
                    client_secret=csec,
                    redirect_uri=redirect_uri,
                )
                url, state = flow.build_authorize_url(scopes=scope_list)
                _print(f"[dim]opening browser to authorize {provider}…[/dim]")
                _print(f"[dim]authorize URL:[/dim] {url}")
                import contextlib

                with contextlib.suppress(Exception):  # pragma: no cover — headless CI
                    webbrowser.open(url, new=2)
                code = typer.prompt("Paste the ?code=... value from the callback URL")
                got_state = typer.prompt(
                    "Paste the ?state=... value (for CSRF check)",
                    default=state,
                    show_default=False,
                )
                data = await flow.exchange_code(code, state=got_state)
                token = data.get("access_token", "")
                if not token:
                    raise typer.BadParameter("provider returned no access_token")
                meta = await vault.add(
                    name=name,
                    provider=provider,
                    value=token,
                    scopes=scope_list or list(flow.provider.default_scopes),
                )
            else:
                v = value
                if v is None:
                    v = typer.prompt("Credential value", hide_input=True)
                meta = await vault.add(
                    name=name,
                    provider=provider,
                    value=v,
                    scopes=scope_list,
                )
            _print(
                f"[green]stored[/green] {meta.name!r} as "
                f"[bold cyan]{meta.vault_id}[/bold cyan] (provider={meta.provider})"
            )
        finally:
            await vault.aclose()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# `wake vault list`
# ---------------------------------------------------------------------------


@app.command("list")
def list_(
    in_memory: Annotated[
        bool,
        typer.Option("--in-memory", help="Use the in-memory fallback."),
    ] = False,
) -> None:
    """List credentials (metadata only; values stay in the vault)."""
    vault = _build_vault(in_memory=in_memory)

    async def _run() -> None:
        try:
            items = await vault.list()
        finally:
            await vault.aclose()

        if Table is None:
            for item in items:
                print(f"{item.vault_id}\t{item.name}\t{item.provider}")
            return
        table = Table(title="Vault entries")
        table.add_column("vault_id", style="cyan")
        table.add_column("name")
        table.add_column("provider")
        table.add_column("scopes")
        for item in items:
            table.add_row(
                item.vault_id,
                item.name,
                str(item.provider),
                ",".join(item.scopes),
            )
        _console.print(table)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# `wake vault remove`
# ---------------------------------------------------------------------------


@app.command("remove")
def remove(
    vault_id: Annotated[str, typer.Argument(help="vault_id to revoke.")],
    in_memory: Annotated[
        bool,
        typer.Option("--in-memory", help="Use the in-memory fallback."),
    ] = False,
) -> None:
    """Permanently delete a credential. Idempotent."""
    vault = _build_vault(in_memory=in_memory)

    async def _run() -> None:
        try:
            await vault.revoke(vault_id)
        finally:
            await vault.aclose()
        _print(f"[yellow]revoked[/yellow] {vault_id}")

    asyncio.run(_run())


if __name__ == "__main__":  # pragma: no cover
    app()
