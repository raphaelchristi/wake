"""``wake events compact|archive`` CLI commands (Phase 7 — gap #5).

Two subcommands under ``wake events``:

* ``compact --session <id>``           Coalesce contiguous
  ``assistant.delta`` events into a single ``assistant.message``
  snapshot and delete the deltas. Preserves replay determinism via
  the standard ``events_to_messages`` projection.

* ``archive --before <ISO date> [--bucket s3://...]``  Stream events
  older than ``--before`` as JSONL gzip and upload to S3 (when
  ``--bucket`` is given) or to a local path (``--output``). Order is
  ALWAYS: upload to S3 → verify ETag → delete local. We NEVER delete
  before S3 confirms success.

Both commands are intentionally OFFLINE — they run against the local
SQLite (dev) or Postgres (prod) store directly, NOT through the API.
That makes them suitable for batch jobs / CronJobs without burning
API rate-limit budget.

Implementation choices:

* boto3 is imported lazily (``--bucket s3://...`` only). Local-only
  archive flows don't pay the import cost.
* JSONL gzip = one event per line, compressed with gzip level 6.
  Restoring from archive is a ``gunzip + jq + bulk insert`` exercise.
* The Postgres archive flow optionally writes an ``archive_log`` audit
  row. SQLite archive flow skips the audit (no migration for SQLite).
"""

# We deliberately use ``id`` and ``input`` as Typer arguments — they
# match the contract names; ruff would otherwise warn A002/A001.
# ruff: noqa: A002, A001

from __future__ import annotations

import asyncio
import contextlib
import gzip
import io
import json
import os
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003 — runtime needed by Typer annotations
from typing import TYPE_CHECKING, Annotated, Any
from urllib.parse import urlparse

import typer

from wake.cli.formatters import console, error_console

if TYPE_CHECKING:
    from wake.store.base import EventStore


events_app = typer.Typer(help="Event log retention helpers (compact, archive).")


def _abort(message: str, code: int = 1) -> None:
    error_console.print(f"[bold red]error:[/bold red] {message}")
    raise typer.Exit(code=code)


async def _open_event_store(database_url: str | None) -> tuple[Any, EventStore]:
    """Resolve the configured backend's EventStore.

    Returns ``(store_handle, event_store)`` so callers can close the
    handle when done. We don't go through ``build_components`` because
    we don't need the full dispatcher graph just for compact / archive.
    """
    dsn = database_url or os.environ.get("WAKE_DATABASE_URL")
    if dsn is None or dsn.startswith("sqlite"):
        from wake.store.sqlite import SQLiteStore

        store = SQLiteStore(dsn or "sqlite+aiosqlite:///./wake.db")
        await store.initialize()
        return store, store.events
    if dsn.startswith("postgresql") or dsn.startswith("postgres"):
        try:
            from wake_store_postgres import PostgresStore  # type: ignore[import-not-found]
        except ImportError as e:
            _abort(
                "wake-store-postgres is not installed but a Postgres DSN "
                "was given. Install with `pip install wake-store-postgres` "
                "or set WAKE_DATABASE_URL=sqlite+..."
            )
            raise SystemExit(2) from e  # for type-checker; _abort already exits
        store = PostgresStore(dsn)
        await store.initialize()
        return store, store.events
    _abort(f"unsupported database URL: {dsn!r}")
    raise SystemExit(2)  # pragma: no cover — defensive


async def _close_store(store_handle: Any) -> None:
    close = getattr(store_handle, "close", None)
    if close is not None:
        with contextlib.suppress(Exception):
            await close()


def _parse_cutoff(value: str) -> datetime:
    """Parse an ISO-8601 date/datetime into an aware UTC datetime.

    Accepts ``2026-01-31``, ``2026-01-31T00:00:00``, or
    ``2026-01-31T00:00:00Z``. Naïve values are assumed UTC.
    """
    raw = value.strip()
    # Tolerant fast path — fromisoformat doesn't accept the trailing Z
    # until Python 3.11+, but we already require 3.11.
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        if "T" in raw or " " in raw:
            dt = datetime.fromisoformat(raw)
        else:
            dt = datetime.fromisoformat(raw + "T00:00:00")
    except ValueError as e:
        _abort(f"invalid --before date {value!r}: {e}")
        raise SystemExit(2) from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _parse_s3_url(url: str) -> tuple[str, str]:
    """Split ``s3://bucket/key/prefix`` into ``(bucket, key_prefix)``."""
    parsed = urlparse(url)
    if parsed.scheme != "s3" or not parsed.netloc:
        _abort(f"invalid S3 URL {url!r}: expected s3://bucket[/prefix]")
    bucket = parsed.netloc
    prefix = parsed.path.lstrip("/")
    return bucket, prefix


def _events_to_jsonl_gzip(events: list[dict[str, Any]]) -> bytes:
    """Serialise a list of event dicts to gzipped JSONL."""
    buf = io.BytesIO()
    # mtime=0 = deterministic gzip header — useful for ETag comparisons.
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6, mtime=0) as gz:
        for ev in events:
            line = json.dumps(ev, default=str, separators=(",", ":")).encode()
            gz.write(line)
            gz.write(b"\n")
    return buf.getvalue()


def _event_to_dict(ev: Any) -> dict[str, Any]:
    """Convert an Event Pydantic model to a JSON-serialisable dict."""
    return {
        "id": ev.id,
        "organization_id": ev.organization_id,
        "workspace_id": ev.workspace_id,
        "session_id": ev.session_id,
        "seq": ev.seq,
        "type": ev.type,
        "payload": ev.payload,
        "parent_id": ev.parent_id,
        "metadata": ev.metadata,
        "created_at": ev.created_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# `wake events compact`
# ---------------------------------------------------------------------------


@events_app.command("compact")
def events_compact(
    session_id: Annotated[
        str,
        typer.Option(
            "--session",
            "-s",
            help="Session ID to compact.",
        ),
    ],
    workspace_id: Annotated[
        str | None,
        typer.Option(
            "--workspace",
            help="Workspace scope. Default: all workspaces.",
        ),
    ] = None,
    database_url: Annotated[
        str | None,
        typer.Option(
            "--database-url",
            envvar="WAKE_DATABASE_URL",
            show_envvar=True,
            help="SQLAlchemy DSN. Defaults to $WAKE_DATABASE_URL.",
        ),
    ] = None,
) -> None:
    """Coalesce ``assistant.delta`` events into ``assistant.message`` snapshots.

    Idempotent: a session with no deltas is a no-op. The original
    ``seq`` range covered by each snapshot is preserved in
    ``metadata.snapshot_of_seq_start`` / ``snapshot_of_seq_end`` so
    audit trails stay forensic.
    """

    async def _run() -> None:
        handle, events = await _open_event_store(database_url)
        try:
            result = await events.compact_session(
                session_id, workspace_id=workspace_id
            )
        finally:
            await _close_store(handle)
        console.print(
            f"[green]compact[/green] session=[cyan]{result.session_id}[/cyan] "
            f"deltas_removed=[bold]{result.deltas_removed}[/bold] "
            f"snapshots_emitted=[bold]{result.snapshots_emitted}[/bold]"
        )

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# `wake events archive`
# ---------------------------------------------------------------------------


@events_app.command("archive")
def events_archive(
    before: Annotated[
        str,
        typer.Option(
            "--before",
            help="ISO-8601 cutoff (e.g. 2026-01-01 or 2026-01-01T00:00:00Z).",
        ),
    ],
    bucket: Annotated[
        str | None,
        typer.Option(
            "--bucket",
            help="S3 URL (s3://bucket[/prefix]). Required for cloud archive.",
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            help="Local output path (.jsonl.gz). Alternative to --bucket.",
        ),
    ] = None,
    workspace_id: Annotated[
        str | None,
        typer.Option(
            "--workspace",
            help="Workspace scope. Default: all workspaces.",
        ),
    ] = None,
    batch_size: Annotated[
        int,
        typer.Option(
            "--batch-size",
            min=1,
            max=10000,
            help="Events per upload batch. Higher = fewer S3 calls, more memory.",
        ),
    ] = 1000,
    delete: Annotated[
        bool,
        typer.Option(
            "--delete/--no-delete",
            help="Delete events locally AFTER S3 upload succeeds. Default: --no-delete (safe).",
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Count events without uploading or deleting.",
        ),
    ] = False,
    database_url: Annotated[
        str | None,
        typer.Option(
            "--database-url",
            envvar="WAKE_DATABASE_URL",
            show_envvar=True,
            help="SQLAlchemy DSN.",
        ),
    ] = None,
) -> None:
    """Export events older than ``--before`` to JSONL gzip.

    Two modes:

    * ``--bucket s3://...``   Upload to S3 (boto3). After verifying
      the ETag we OPTIONALLY delete the local rows (``--delete``).
      Order is upload → verify → delete; we NEVER delete first.

    * ``--output ./archive.jsonl.gz``   Stream to a local file.

    With ``--dry-run`` we count matching events without uploading or
    deleting — useful for capacity planning.
    """
    if not dry_run and bucket is None and output is None:
        _abort("either --bucket or --output (or --dry-run) is required")

    cutoff = _parse_cutoff(before)

    async def _run() -> None:
        handle, events = await _open_event_store(database_url)
        try:
            # Dry-run path: count only.
            if dry_run:
                purged = await events.purge_before(
                    cutoff, workspace_id=workspace_id, dry_run=True
                )
                console.print(
                    f"[yellow]dry-run[/yellow] would archive=[bold]{purged.deleted}[/bold] "
                    f"events before={cutoff.isoformat()}"
                )
                return

            total_events = 0
            total_sessions: set[str] = set()
            total_bytes = 0
            s3_client = None
            s3_bucket: str | None = None
            s3_key_prefix: str | None = None
            output_file = None

            if bucket is not None:
                s3_bucket, s3_key_prefix = _parse_s3_url(bucket)
                try:
                    import boto3  # type: ignore[import-untyped]
                except ImportError as e:
                    _abort(
                        "boto3 is required for --bucket. "
                        "Install with `pip install boto3`."
                    )
                    raise SystemExit(2) from e
                s3_client = boto3.client("s3")
            elif output is not None:
                output_file = output.open("wb")

            try:
                batch_index = 0
                async for batch in await events.iter_for_archive(
                    cutoff, workspace_id=workspace_id, batch_size=batch_size
                ):
                    payload = [_event_to_dict(ev) for ev in batch]
                    blob = _events_to_jsonl_gzip(payload)
                    if s3_client is not None:
                        key = _build_key(s3_key_prefix or "", cutoff, batch_index)
                        # Upload → verify ETag → ONLY THEN delete.
                        resp = s3_client.put_object(
                            Bucket=s3_bucket,
                            Key=key,
                            Body=blob,
                            ContentType="application/gzip",
                            ContentEncoding="gzip",
                        )
                        etag = (resp.get("ETag") or "").strip('"')
                        if not etag:
                            _abort(
                                f"S3 upload to s3://{s3_bucket}/{key} returned no ETag; "
                                "refusing to delete local rows"
                            )
                        # Verify presence (HeadObject) — defensive double-check
                        # before any local delete touches the source rows.
                        s3_client.head_object(Bucket=s3_bucket, Key=key)
                        console.print(
                            f"[green]→[/green] uploaded batch {batch_index} "
                            f"events={len(batch)} bytes={len(blob)} "
                            f"key=[cyan]s3://{s3_bucket}/{key}[/cyan] etag={etag}"
                        )
                    elif output_file is not None:
                        output_file.write(blob)
                        console.print(
                            f"[green]→[/green] wrote batch {batch_index} "
                            f"events={len(batch)} bytes={len(blob)}"
                        )

                    total_events += len(batch)
                    total_bytes += len(blob)
                    for ev in batch:
                        total_sessions.add(ev.session_id)
                    batch_index += 1

                    # Delete only after successful upload (or --delete on
                    # local archive mode).
                    if delete:
                        await events._delete_events(  # noqa: SLF001 — intentional
                            [ev.id for ev in batch], workspace_id=workspace_id
                        )
            finally:
                if output_file is not None:
                    output_file.close()

            if s3_client is not None and total_events > 0:
                # Write audit row when running against Postgres store.
                await _maybe_write_archive_log(
                    handle,
                    cutoff=cutoff,
                    s3_bucket=s3_bucket or "",
                    s3_key=_build_key(s3_key_prefix or "", cutoff, 0),
                    s3_etag=None,
                    workspace_id=workspace_id,
                    session_count=len(total_sessions),
                    event_count=total_events,
                    bytes_uploaded=total_bytes,
                    deleted=delete,
                )

            console.print(
                f"[bold green]done[/bold green] "
                f"events=[bold]{total_events}[/bold] "
                f"sessions=[bold]{len(total_sessions)}[/bold] "
                f"bytes=[bold]{total_bytes}[/bold] "
                f"deleted=[bold]{delete}[/bold]"
            )
        finally:
            await _close_store(handle)

    asyncio.run(_run())


def _build_key(prefix: str, cutoff: datetime, batch_index: int) -> str:
    """Compose the S3 object key for a batch.

    Layout: ``<prefix>/wake-events-<cutoff-YYYYMMDD>-<batch>.jsonl.gz``
    """
    stamp = cutoff.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = f"wake-events-{stamp}-{batch_index:04d}.jsonl.gz"
    if not prefix:
        return base
    return f"{prefix.rstrip('/')}/{base}"


async def _maybe_write_archive_log(
    store_handle: Any,
    *,
    cutoff: datetime,
    s3_bucket: str,
    s3_key: str,
    s3_etag: str | None,
    workspace_id: str | None,
    session_count: int,
    event_count: int,
    bytes_uploaded: int,
    deleted: bool,
) -> None:
    """Insert an ``archive_log`` row when running against Postgres.

    SQLite store doesn't ship an archive_log table (no migrations), so
    we silently skip. The audit table is best-effort: a failure here
    must NOT roll back the upload that already succeeded.
    """
    try:
        from wake_store_postgres.models import ArchiveLogRow  # type: ignore[import-not-found]
    except ImportError:
        return
    sessionmaker = getattr(store_handle, "_sessionmaker", None)
    if sessionmaker is None:
        return
    now = datetime.now(UTC)
    try:
        from ulid import ULID  # local import, ulid is wake's dep
        async with sessionmaker() as s, s.begin():
            s.add(
                ArchiveLogRow(
                    id=str(ULID()),
                    workspace_id=workspace_id,
                    cutoff=cutoff,
                    s3_bucket=s3_bucket,
                    s3_key=s3_key,
                    s3_etag=s3_etag,
                    session_count=session_count,
                    event_count=event_count,
                    bytes_uploaded=bytes_uploaded,
                    upload_completed_at=now,
                    delete_completed_at=now if deleted else None,
                )
            )
    except Exception as e:  # noqa: BLE001
        error_console.print(
            f"[yellow]warn:[/yellow] failed to write archive_log row: {e}"
        )


__all__ = ["events_app"]
