"""Pure aggregation functions for the metrics surface.

The dashboard ``/metrics`` page calls ``GET /metrics/summary?window=24h``.
The route handler in ``wake.api.routes.metrics`` fetches the raw event
log slice from the store, then hands the events to the pure functions
defined here. Keeping the math in this module makes it trivially
unit-testable without booting a FastAPI app — see
``tests/unit/test_metrics_aggregation.py``.

All public helpers accept ``events: Sequence[Event]`` (events emitted by
``wake.core.event_log.EventLog``) and return plain dicts / dataclass-y
values that are FastAPI-encodable.

Latency is computed per session as wall-clock between the first
``user.message`` and the matching ``assistant.message`` (last one in the
turn). Cost is summed from ``metadata.cost_usd`` on any event that
carries it (LiteLLM callback writes it on ``assistant.message`` events).
Error rate is ``errors / sessions``.

NOTE: this module is pure — no I/O, no time.time(). Everything derives
from the events you pass in. The route handler is responsible for
windowing.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from wake.types import Event


# ---------------------------------------------------------------------------
# Window parsing
# ---------------------------------------------------------------------------


_WINDOW_TO_SECONDS: dict[str, int] = {
    "1h": 3600,
    "24h": 86_400,
    "7d": 7 * 86_400,
    "30d": 30 * 86_400,
}


def parse_window(window: str) -> timedelta:
    """Convert a UI window code (``1h`` / ``24h`` / ``7d`` / ``30d``) into a delta.

    Unknown values raise ``ValueError`` — callers should surface a 400.
    """
    if window not in _WINDOW_TO_SECONDS:
        raise ValueError(
            f"unknown window {window!r}; expected one of {sorted(_WINDOW_TO_SECONDS)}"
        )
    return timedelta(seconds=_WINDOW_TO_SECONDS[window])


# ---------------------------------------------------------------------------
# Percentiles (no numpy dep)
# ---------------------------------------------------------------------------


def percentile(values: Sequence[float], pct: float) -> float:
    """Return the ``pct``-th percentile (linear interpolation).

    Returns 0.0 if ``values`` is empty. ``pct`` is in [0, 100].
    """
    if not values:
        return 0.0
    if pct <= 0:
        return float(min(values))
    if pct >= 100:
        return float(max(values))
    ordered = sorted(values)
    k = (len(ordered) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    frac = k - lo
    return float(ordered[lo] + (ordered[hi] - ordered[lo]) * frac)


# ---------------------------------------------------------------------------
# Bucketing for time series
# ---------------------------------------------------------------------------


def _bucket_seconds_for_window(window: timedelta) -> int:
    """Pick a bucket size that yields ~30-60 points across the window."""
    total = window.total_seconds()
    if total <= 3600:           # 1h → 1 min buckets (60 points)
        return 60
    if total <= 86_400:         # 24h → 30 min buckets (48 points)
        return 30 * 60
    if total <= 7 * 86_400:     # 7d → 4h buckets (42 points)
        return 4 * 3600
    return 24 * 3600            # 30d → 1d buckets (30 points)


def _floor_to_bucket(t: datetime, bucket_seconds: int) -> datetime:
    epoch = int(t.timestamp())
    return datetime.fromtimestamp(epoch - (epoch % bucket_seconds), tz=timezone.utc)


# ---------------------------------------------------------------------------
# Per-session reductions
# ---------------------------------------------------------------------------


@dataclass
class SessionAggregate:
    """Per-session reduction of an event stream.

    Keeps just the bits the metrics dashboard needs: turn latency, cost,
    error count, start time.
    """

    session_id: str
    started_at: datetime | None = None
    latency_ms: float | None = None
    cost_usd: float = 0.0
    errors: int = 0
    event_count: int = 0


def _coerce_cost(payload_or_meta: dict[str, Any] | None) -> float:
    if not payload_or_meta:
        return 0.0
    raw = payload_or_meta.get("cost_usd")
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def aggregate_by_session(events: Iterable[Event]) -> dict[str, SessionAggregate]:
    """Reduce a flat event stream into one ``SessionAggregate`` per session."""
    out: dict[str, SessionAggregate] = {}
    first_user_at: dict[str, datetime] = {}

    for ev in events:
        agg = out.setdefault(ev.session_id, SessionAggregate(session_id=ev.session_id))
        agg.event_count += 1
        if agg.started_at is None or ev.created_at < agg.started_at:
            agg.started_at = ev.created_at

        if ev.type == "user.message":
            # Latest user turn — track for next assistant message.
            first_user_at[ev.session_id] = ev.created_at
        elif ev.type == "assistant.message":
            started = first_user_at.get(ev.session_id)
            if started is not None:
                delta_ms = (ev.created_at - started).total_seconds() * 1000.0
                # If we already have a latency, take the **last** turn —
                # the dashboard's expectation is "time to last reply".
                agg.latency_ms = max(0.0, delta_ms)
            # Cost can live on payload or metadata depending on adapter.
            agg.cost_usd += _coerce_cost(ev.payload)
            agg.cost_usd += _coerce_cost(ev.metadata)
        elif ev.type == "error":
            agg.errors += 1
        elif ev.type == "tool_result":
            # Some LiteLLM adapters tag cost here.
            agg.cost_usd += _coerce_cost(ev.payload)

    return out


# ---------------------------------------------------------------------------
# Public summary builder
# ---------------------------------------------------------------------------


def build_summary(
    events: Sequence[Event],
    *,
    window: timedelta,
    now: datetime | None = None,
    workers_alive: int = 0,
    queue_depth: int = 0,
) -> dict[str, Any]:
    """Aggregate ``events`` into the JSON the ``/metrics/summary`` endpoint returns.

    ``events`` should already be windowed by the caller (the route reads
    from the store with a ``since=`` cutoff). We do **not** re-filter
    here, but we *do* respect ``now`` for the time-series bucketing so
    the chart's x-axis is stable.

    Returns a JSON-friendly dict with keys: ``window``, ``latency``,
    ``cost``, ``throughput``, ``errors``, ``workers_alive``,
    ``queue_depth``, ``sessions`` (count), ``series``.
    """
    current = now or datetime.now(timezone.utc)
    window_start = current - window

    per_session = aggregate_by_session(events)
    latencies_ms = [
        agg.latency_ms for agg in per_session.values() if agg.latency_ms is not None
    ]
    costs = [agg.cost_usd for agg in per_session.values()]
    cost_total = sum(costs)
    error_count = sum(agg.errors for agg in per_session.values())
    session_count = len(per_session)

    # Sessions/hour over the window. Avoid /0 on tiny windows.
    window_hours = max(window.total_seconds() / 3600.0, 1 / 3600.0)
    throughput_per_hour = session_count / window_hours

    # Error rate as fraction of sessions that emitted ≥1 error event.
    sessions_with_error = sum(1 for agg in per_session.values() if agg.errors > 0)
    error_rate = (sessions_with_error / session_count) if session_count else 0.0

    # ----- Time series buckets -------------------------------------------------
    bucket_s = _bucket_seconds_for_window(window)
    latency_buckets: dict[datetime, list[float]] = defaultdict(list)
    cost_buckets: dict[datetime, float] = defaultdict(float)
    throughput_buckets: dict[datetime, int] = defaultdict(int)
    error_buckets: dict[datetime, int] = defaultdict(int)

    for ev in events:
        if ev.created_at < window_start:
            continue
        bucket = _floor_to_bucket(ev.created_at, bucket_s)
        if ev.type == "assistant.message":
            sess = per_session.get(ev.session_id)
            if sess and sess.latency_ms is not None:
                latency_buckets[bucket].append(sess.latency_ms)
            cost_buckets[bucket] += _coerce_cost(ev.payload) + _coerce_cost(ev.metadata)
        elif ev.type == "user.message":
            throughput_buckets[bucket] += 1
        elif ev.type == "error":
            error_buckets[bucket] += 1

    bucket_axis: list[datetime] = []
    cursor = _floor_to_bucket(window_start, bucket_s)
    while cursor <= current:
        bucket_axis.append(cursor)
        cursor = cursor + timedelta(seconds=bucket_s)

    series_latency = [
        {
            "t": t.isoformat(),
            "p50": percentile(latency_buckets.get(t, []), 50),
            "p95": percentile(latency_buckets.get(t, []), 95),
            "p99": percentile(latency_buckets.get(t, []), 99),
        }
        for t in bucket_axis
    ]
    series_cost = [
        {"t": t.isoformat(), "cost_usd": cost_buckets.get(t, 0.0)} for t in bucket_axis
    ]
    series_throughput = [
        {"t": t.isoformat(), "sessions": throughput_buckets.get(t, 0)}
        for t in bucket_axis
    ]
    series_errors = [
        {"t": t.isoformat(), "errors": error_buckets.get(t, 0)} for t in bucket_axis
    ]

    return {
        "window": {
            "code": _window_code(window),
            "start": window_start.isoformat(),
            "end": current.isoformat(),
            "bucket_seconds": bucket_s,
        },
        "latency": {
            "p50_ms": percentile(latencies_ms, 50),
            "p95_ms": percentile(latencies_ms, 95),
            "p99_ms": percentile(latencies_ms, 99),
            "samples": len(latencies_ms),
        },
        "cost": {
            "total_usd": cost_total,
            "avg_per_session_usd": (cost_total / session_count) if session_count else 0.0,
            "max_session_usd": max(costs) if costs else 0.0,
            "samples": len(costs),
        },
        "throughput": {
            "sessions": session_count,
            "per_hour": throughput_per_hour,
        },
        "errors": {
            "count": error_count,
            "rate": error_rate,
            "sessions_affected": sessions_with_error,
        },
        "workers_alive": workers_alive,
        "queue_depth": queue_depth,
        "series": {
            "latency": series_latency,
            "cost": series_cost,
            "throughput": series_throughput,
            "errors": series_errors,
        },
    }


def _window_code(window: timedelta) -> str:
    secs = int(window.total_seconds())
    for code, seconds in _WINDOW_TO_SECONDS.items():
        if seconds == secs:
            return code
    return f"{secs}s"


__all__ = [
    "SessionAggregate",
    "aggregate_by_session",
    "build_summary",
    "parse_window",
    "percentile",
]
