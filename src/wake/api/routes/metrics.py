# ruff: noqa: B008, TC001
"""Metrics routes — feeds the dashboard ``/metrics`` page.

* ``GET /v1/metrics/summary?window=1h|24h|7d|30d`` — JSON aggregate
* ``GET /v1/workers`` — list of workers with heartbeat status

Both routes are *additive*: they sit alongside the existing FastAPI
shape without changing any other endpoint. Aggregation logic lives in
``wake.api.metrics_aggregation`` so it is pure-function testable.

Worker liveness is read directly from the ``SessionStore``'s session
metadata (``meta._heartbeat`` populated by ``WorkerHeartbeat``). If the
store doesn't carry heartbeats (e.g. SQLite single-process), we degrade
to a single in-process "worker" entry derived from sessions that are
currently ``running``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query

from wake.api.dependencies import (
    get_event_log,
    get_session_store,
    get_tenant_context,
)
from wake.api.metrics_aggregation import build_summary, parse_window
from wake.core.event_log import EventLog
from wake.store.base import SessionStore
from wake.tenancy import TenantContext
from wake.types import Event, Session

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/v1", tags=["metrics"])


WindowCode = Literal["1h", "24h", "7d", "30d"]
HEARTBEAT_TIMEOUT_S = 30


# ---------------------------------------------------------------------------
# /metrics/summary
# ---------------------------------------------------------------------------


@router.get("/metrics/summary")
async def metrics_summary(
    window: WindowCode = Query("24h", description="Aggregation window"),
    session_store: SessionStore = Depends(get_session_store),
    event_log: EventLog = Depends(get_event_log),
    tenant: TenantContext = Depends(get_tenant_context),
) -> dict[str, Any]:
    """Return aggregated metrics over the given window.

    The shape matches ``wake.api.metrics_aggregation.build_summary``;
    see that module for field-by-field semantics.
    """
    try:
        window_delta = parse_window(window)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    now = datetime.now(UTC)
    cutoff = now - window_delta

    # Gather events for every session that may overlap the window. We
    # over-fetch (whole session) on purpose because event_log.get is
    # session-scoped; build_summary filters by ``cutoff`` per event.
    sessions = await session_store.list(workspace_id=tenant.workspace_id)
    events: list[Event] = []
    for sess in sessions:
        if sess.created_at < cutoff and sess.status == "terminated":
            # Skip sessions that ended before the window — they cannot
            # contribute any events inside the cutoff.
            continue
        events.extend(await event_log.get(sess.id, workspace_id=tenant.workspace_id))

    # Worker liveness — derived from session meta heartbeats if any.
    workers_alive = _count_alive_workers(sessions, now=now)
    queue_depth = sum(1 for s in sessions if s.status == "idle")

    return build_summary(
        events=events,
        window=window_delta,
        now=now,
        workers_alive=workers_alive,
        queue_depth=queue_depth,
    )


# ---------------------------------------------------------------------------
# /workers
# ---------------------------------------------------------------------------


@router.get("/workers")
async def list_workers(
    session_store: SessionStore = Depends(get_session_store),
    tenant: TenantContext = Depends(get_tenant_context),
) -> dict[str, list[dict[str, Any]]]:
    """List workers with heartbeat status.

    A "worker" is identified by ``meta._heartbeat.worker`` written into
    a running session by the Postgres heartbeat. SQLite mode returns a
    synthetic ``{worker_id: "local"}`` entry covering any running
    sessions in the single-process backend.

    Returned shape::

        {
            "data": [
                {
                    "worker_id": "...",
                    "status": "alive" | "stale" | "idle",
                    "last_heartbeat_at": "ISO8601" | null,
                    "current_session_id": "...",
                    "current_sessions": ["..."]
                },
                ...
            ]
        }
    """
    now = datetime.now(UTC)
    sessions = await session_store.list(workspace_id=tenant.workspace_id)

    # Group sessions by worker_id discovered in meta.
    grouped: dict[str, dict[str, Any]] = {}
    has_pg_heartbeat = False

    for sess in sessions:
        worker_id, hb_at = _extract_heartbeat(sess)
        if worker_id is None:
            continue
        has_pg_heartbeat = True
        bucket = grouped.setdefault(
            worker_id,
            {
                "worker_id": worker_id,
                "status": "idle",
                "last_heartbeat_at": None,
                "current_session_id": None,
                "current_sessions": [],
            },
        )
        if sess.status in ("running", "rescheduling"):
            bucket["current_sessions"].append(sess.id)
            if bucket["current_session_id"] is None:
                bucket["current_session_id"] = sess.id
        if hb_at is not None:
            prev = bucket["last_heartbeat_at"]
            if prev is None or hb_at.isoformat() > prev:
                bucket["last_heartbeat_at"] = hb_at.isoformat()

    # Mark stale / alive based on the freshest heartbeat per worker.
    for entry in grouped.values():
        latest = entry["last_heartbeat_at"]
        if latest is None:
            entry["status"] = "idle"
            continue
        latest_dt = datetime.fromisoformat(latest)
        delta = (now - latest_dt).total_seconds()
        if delta > HEARTBEAT_TIMEOUT_S:
            entry["status"] = "stale"
        elif entry["current_sessions"]:
            entry["status"] = "alive"
        else:
            entry["status"] = "idle"

    # Fallback for SQLite/single-process: surface a "local" worker if
    # we found no heartbeat metadata and there are running sessions.
    if not has_pg_heartbeat:
        running = [s for s in sessions if s.status in ("running", "rescheduling")]
        if running:
            grouped["local"] = {
                "worker_id": "local",
                "status": "alive",
                "last_heartbeat_at": now.isoformat(),
                "current_session_id": running[0].id,
                "current_sessions": [s.id for s in running],
            }

    return {"data": sorted(grouped.values(), key=lambda d: d["worker_id"])}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_heartbeat(session: Session) -> tuple[str | None, datetime | None]:
    """Pull ``_heartbeat.{at, worker}`` out of ``session.metadata``.

    The ``WorkerHeartbeat`` (postgres-store adapter) writes::

        meta._heartbeat = {"at": "<iso>", "worker": "<id>"}

    SQLite/in-memory stores have no such key, so we return ``(None, None)``.
    """
    meta: dict[str, Any] = dict(session.metadata or {})
    raw = meta.get("_heartbeat")
    if not isinstance(raw, dict):
        return None, None
    worker = raw.get("worker")
    at_raw = raw.get("at")
    at_dt: datetime | None = None
    if isinstance(at_raw, str):
        try:
            at_dt = datetime.fromisoformat(at_raw)
            if at_dt.tzinfo is None:
                at_dt = at_dt.replace(tzinfo=UTC)
        except ValueError:
            at_dt = None
    return (str(worker) if worker else None), at_dt


def _count_alive_workers(sessions: list[Session], *, now: datetime) -> int:
    """Number of distinct workers whose latest heartbeat is within timeout."""
    latest_per_worker: dict[str, datetime] = {}
    for sess in sessions:
        worker_id, hb_at = _extract_heartbeat(sess)
        if worker_id is None or hb_at is None:
            continue
        prev = latest_per_worker.get(worker_id)
        if prev is None or hb_at > prev:
            latest_per_worker[worker_id] = hb_at
    alive = 0
    for hb_at in latest_per_worker.values():
        if (now - hb_at) < timedelta(seconds=HEARTBEAT_TIMEOUT_S):
            alive += 1
    # No heartbeats at all? Count running sessions as a single local worker.
    if not latest_per_worker and any(s.status in ("running", "rescheduling") for s in sessions):
        alive = 1
    return alive


__all__ = ["router"]
