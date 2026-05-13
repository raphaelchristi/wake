"""Unit tests for the pure metrics aggregation helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from wake.api.metrics_aggregation import (
    SessionAggregate,
    aggregate_by_session,
    build_summary,
    parse_window,
    percentile,
)
from wake.types import Event


def _ev(
    session_id: str,
    seq: int,
    event_type: str,
    *,
    created_at: datetime,
    payload: dict | None = None,
    metadata: dict | None = None,
) -> Event:
    return Event(
        id=f"ev_{session_id}_{seq:04d}",
        session_id=session_id,
        seq=seq,
        type=event_type,  # type: ignore[arg-type]
        payload=payload or {},
        metadata=metadata,
        created_at=created_at,
    )


# ---------------------------------------------------------------------------
# parse_window
# ---------------------------------------------------------------------------


def test_parse_window_known_values() -> None:
    assert parse_window("1h") == timedelta(hours=1)
    assert parse_window("24h") == timedelta(hours=24)
    assert parse_window("7d") == timedelta(days=7)
    assert parse_window("30d") == timedelta(days=30)


def test_parse_window_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown window"):
        parse_window("9h")


# ---------------------------------------------------------------------------
# percentile
# ---------------------------------------------------------------------------


def test_percentile_empty_is_zero() -> None:
    assert percentile([], 50) == 0.0
    assert percentile([], 95) == 0.0


def test_percentile_single_value() -> None:
    assert percentile([42.0], 50) == 42.0
    assert percentile([42.0], 99) == 42.0


def test_percentile_quartiles() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile(values, 0) == 1.0
    assert percentile(values, 50) == 3.0
    assert percentile(values, 100) == 5.0


def test_percentile_interpolates() -> None:
    # p95 over [0..9] = 9*0.95 = 8.55 → between values[8]=8 and values[9]=9
    values = list(range(10))
    assert percentile([float(v) for v in values], 95) == pytest.approx(8.55, rel=0.01)


# ---------------------------------------------------------------------------
# aggregate_by_session
# ---------------------------------------------------------------------------


def test_aggregate_empty() -> None:
    assert aggregate_by_session([]) == {}


def test_aggregate_user_then_assistant_yields_latency() -> None:
    now = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
    events = [
        _ev("s1", 0, "user.message", created_at=now),
        _ev(
            "s1",
            1,
            "assistant.message",
            created_at=now + timedelta(milliseconds=750),
            payload={"cost_usd": 0.012},
        ),
    ]
    agg = aggregate_by_session(events)
    assert "s1" in agg
    assert agg["s1"].latency_ms == pytest.approx(750.0, rel=1e-3)
    assert agg["s1"].cost_usd == pytest.approx(0.012)
    assert agg["s1"].errors == 0
    assert agg["s1"].event_count == 2


def test_aggregate_counts_errors() -> None:
    now = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
    events = [
        _ev("s1", 0, "user.message", created_at=now),
        _ev("s1", 1, "error", created_at=now + timedelta(seconds=1)),
        _ev("s1", 2, "error", created_at=now + timedelta(seconds=2)),
    ]
    agg = aggregate_by_session(events)
    assert agg["s1"].errors == 2
    assert agg["s1"].latency_ms is None


def test_aggregate_cost_in_metadata_and_payload() -> None:
    now = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
    events = [
        _ev("s1", 0, "user.message", created_at=now),
        _ev(
            "s1",
            1,
            "assistant.message",
            created_at=now + timedelta(milliseconds=100),
            metadata={"cost_usd": 0.05},
        ),
        _ev("s1", 2, "tool_result", created_at=now + timedelta(seconds=1), payload={"cost_usd": 0.01}),
    ]
    agg = aggregate_by_session(events)
    assert agg["s1"].cost_usd == pytest.approx(0.06)


def test_aggregate_latency_is_last_turn() -> None:
    now = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
    events = [
        _ev("s1", 0, "user.message", created_at=now),
        _ev("s1", 1, "assistant.message", created_at=now + timedelta(milliseconds=100)),
        _ev("s1", 2, "user.message", created_at=now + timedelta(seconds=2)),
        _ev("s1", 3, "assistant.message", created_at=now + timedelta(seconds=2, milliseconds=400)),
    ]
    agg = aggregate_by_session(events)
    # Last turn: 400ms (not the first 100ms).
    assert agg["s1"].latency_ms == pytest.approx(400.0, rel=1e-3)


def test_aggregate_invalid_cost_is_ignored() -> None:
    now = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
    events = [
        _ev("s1", 0, "user.message", created_at=now),
        _ev(
            "s1",
            1,
            "assistant.message",
            created_at=now + timedelta(milliseconds=10),
            payload={"cost_usd": "garbage"},
        ),
    ]
    agg = aggregate_by_session(events)
    assert agg["s1"].cost_usd == 0.0


# ---------------------------------------------------------------------------
# build_summary
# ---------------------------------------------------------------------------


def _two_session_fixture(start: datetime) -> list[Event]:
    return [
        _ev("s1", 0, "user.message", created_at=start),
        _ev(
            "s1",
            1,
            "assistant.message",
            created_at=start + timedelta(milliseconds=500),
            payload={"cost_usd": 0.02},
        ),
        _ev("s2", 0, "user.message", created_at=start + timedelta(minutes=5)),
        _ev(
            "s2",
            1,
            "assistant.message",
            created_at=start + timedelta(minutes=5, seconds=1),
            payload={"cost_usd": 0.05},
        ),
        _ev("s2", 2, "error", created_at=start + timedelta(minutes=5, seconds=2)),
    ]


def test_build_summary_basic_counts() -> None:
    now = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
    events = _two_session_fixture(start=now - timedelta(minutes=10))
    summary = build_summary(events, window=timedelta(hours=1), now=now)

    assert summary["throughput"]["sessions"] == 2
    assert summary["cost"]["total_usd"] == pytest.approx(0.07)
    assert summary["errors"]["count"] == 1
    assert summary["errors"]["sessions_affected"] == 1
    assert summary["errors"]["rate"] == pytest.approx(0.5)
    assert summary["latency"]["samples"] == 2
    assert summary["latency"]["p50_ms"] > 0


def test_build_summary_zero_events_is_zero_division_safe() -> None:
    now = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
    summary = build_summary([], window=timedelta(hours=1), now=now)
    assert summary["throughput"]["sessions"] == 0
    assert summary["throughput"]["per_hour"] == 0.0
    assert summary["cost"]["total_usd"] == 0.0
    assert summary["latency"]["p95_ms"] == 0.0
    assert summary["errors"]["rate"] == 0.0


def test_build_summary_window_metadata() -> None:
    now = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
    summary = build_summary([], window=timedelta(days=7), now=now)
    assert summary["window"]["code"] == "7d"
    assert summary["window"]["end"] == now.isoformat()


def test_build_summary_series_buckets_present() -> None:
    now = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
    events = _two_session_fixture(start=now - timedelta(minutes=10))
    summary = build_summary(events, window=timedelta(hours=1), now=now)
    # 1h window → 60 second buckets → ~60 points.
    assert len(summary["series"]["latency"]) >= 50
    # Each entry has the expected shape.
    sample = summary["series"]["latency"][0]
    assert set(sample.keys()) == {"t", "p50", "p95", "p99"}


def test_build_summary_workers_alive_passthrough() -> None:
    now = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
    summary = build_summary(
        [],
        window=timedelta(hours=1),
        now=now,
        workers_alive=4,
        queue_depth=2,
    )
    assert summary["workers_alive"] == 4
    assert summary["queue_depth"] == 2


def test_build_summary_throughput_per_hour() -> None:
    now = datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)
    # 2 sessions in a 1h window → exactly 2 sessions/hour.
    events = _two_session_fixture(start=now - timedelta(minutes=10))
    summary = build_summary(events, window=timedelta(hours=1), now=now)
    assert summary["throughput"]["per_hour"] == pytest.approx(2.0, rel=1e-3)


# ---------------------------------------------------------------------------
# SessionAggregate
# ---------------------------------------------------------------------------


def test_session_aggregate_defaults() -> None:
    agg = SessionAggregate(session_id="x")
    assert agg.cost_usd == 0.0
    assert agg.errors == 0
    assert agg.latency_ms is None
    assert agg.event_count == 0
