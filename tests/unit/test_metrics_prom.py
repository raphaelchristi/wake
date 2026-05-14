"""Tests for the Prometheus exposition + business metrics.

Phase 7 / Tier 1 gap #8 acceptance:

* ``GET /metrics`` returns Prom text exposition.
* Wake business counters / histograms / gauges all show up.
* Workspace label OPT-IN via ``WAKE_METRICS_WORKSPACE_LABEL=true``.
* HTTP requests through the app populate ``http_*`` series.
* ``/metrics`` itself is excluded from instrumentation (no recursion).
* The Wake counters survive multiple ``create_app()`` calls in the same
  process — Prom collectors are *process-lifetime* and survive
  recreation.

Tests use the public :func:`get_metrics` API and the FastAPI
``TestClient`` to keep coverage end-to-end-ish (we mount the same way
production does).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry

from wake.api.app import create_app
from wake.observability.metrics import (
    WAKE_METRICS_WORKSPACE_LABEL_ENV,
    get_metrics,
    workspace_label_enabled,
)

# ---------------------------------------------------------------------------
# Workspace label opt-in
# ---------------------------------------------------------------------------


def test_workspace_label_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without env, the workspace label is OFF (cardinality safe default)."""
    monkeypatch.delenv(WAKE_METRICS_WORKSPACE_LABEL_ENV, raising=False)
    assert workspace_label_enabled() is False


@pytest.mark.parametrize("truthy", ["true", "True", "1", "yes", "on"])
def test_workspace_label_enabled_via_env(
    monkeypatch: pytest.MonkeyPatch, truthy: str
) -> None:
    """Common truthy spellings opt the workspace label in."""
    monkeypatch.setenv(WAKE_METRICS_WORKSPACE_LABEL_ENV, truthy)
    assert workspace_label_enabled() is True


def test_metrics_observe_event_with_workspace_label_off() -> None:
    """When the label is OFF, the workspace dimension collapses to a
    constant string so cardinality stays bounded."""
    metrics = get_metrics(registry=CollectorRegistry(), force_new=True)
    assert metrics.workspace_label_enabled is False  # default
    metrics.observe_event_appended(event_type="user.message", workspace="ws_a")
    metrics.observe_event_appended(event_type="user.message", workspace="ws_b")
    # Both ended up under the same series — _aggregated.
    series = metrics.events_total.labels(type="user.message", workspace="_aggregated")
    assert series._value.get() == 2.0  # noqa: SLF001


def test_metrics_observe_event_with_workspace_label_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the label is ON, distinct workspaces become distinct series."""
    monkeypatch.setenv(WAKE_METRICS_WORKSPACE_LABEL_ENV, "true")
    metrics = get_metrics(registry=CollectorRegistry(), force_new=True)
    assert metrics.workspace_label_enabled is True
    metrics.observe_event_appended(event_type="user.message", workspace="ws_a")
    metrics.observe_event_appended(event_type="user.message", workspace="ws_a")
    metrics.observe_event_appended(event_type="user.message", workspace="ws_b")
    a = metrics.events_total.labels(type="user.message", workspace="ws_a")
    b = metrics.events_total.labels(type="user.message", workspace="ws_b")
    assert a._value.get() == 2.0  # noqa: SLF001
    assert b._value.get() == 1.0  # noqa: SLF001


# ---------------------------------------------------------------------------
# Singleton + force_new isolation
# ---------------------------------------------------------------------------


def test_get_metrics_returns_singleton() -> None:
    """Two calls without ``force_new`` return the same WakeMetrics object."""
    a = get_metrics()
    b = get_metrics()
    assert a is b


def test_get_metrics_force_new_isolates() -> None:
    """force_new=True returns a fresh instance against a private registry."""
    a = get_metrics()
    b = get_metrics(registry=CollectorRegistry(), force_new=True)
    assert a is not b


# ---------------------------------------------------------------------------
# Counters / histograms / gauges shape
# ---------------------------------------------------------------------------


def test_session_terminal_observation_records_event_count() -> None:
    metrics = get_metrics(registry=CollectorRegistry(), force_new=True)
    metrics.observe_session_terminal(status="terminated", event_count=42)
    metrics.observe_session_terminal(status="failed")  # no event count
    metrics.observe_session_terminal(status="terminated", event_count=-1)  # ignored

    # 2 increments on status=terminated, 1 on status=failed
    terminated = metrics.sessions_total.labels(status="terminated")
    failed = metrics.sessions_total.labels(status="failed")
    assert terminated._value.get() == 2.0  # noqa: SLF001
    assert failed._value.get() == 1.0  # noqa: SLF001


def test_error_and_cost_observations_round_trip() -> None:
    metrics = get_metrics(registry=CollectorRegistry(), force_new=True)
    metrics.observe_error(code="dispatcher_step_failed")
    metrics.observe_error(code="dispatcher_step_failed")
    metrics.observe_error(code="oauth_state_invalid")
    metrics.observe_cost(usd=0.0025)
    metrics.observe_cost(usd=0.42)
    metrics.observe_cost(usd=-1.0)  # ignored

    assert (
        metrics.errors_total.labels(code="dispatcher_step_failed")._value.get()  # noqa: SLF001
        == 2.0
    )
    assert (
        metrics.errors_total.labels(code="oauth_state_invalid")._value.get()  # noqa: SLF001
        == 1.0
    )
    # cost_usd: 2 observations recorded (negative was filtered).
    samples = list(metrics.cost_usd.collect()[0].samples)
    count_sample = next(s for s in samples if s.name == "wake_cost_usd_count")
    assert count_sample.value == 2.0


def test_gauges_track_queue_and_workers() -> None:
    metrics = get_metrics(registry=CollectorRegistry(), force_new=True)
    metrics.set_queue_depth(depth=7)
    metrics.set_workers_active(count=3)
    assert metrics.worker_queue_depth._value.get() == 7.0  # noqa: SLF001
    assert metrics.workers_active._value.get() == 3.0  # noqa: SLF001
    # Negative values clamp to zero (defensive — gauges should never go
    # below zero in this domain).
    metrics.set_queue_depth(depth=-5)
    metrics.set_workers_active(count=-2)
    assert metrics.worker_queue_depth._value.get() == 0.0  # noqa: SLF001
    assert metrics.workers_active._value.get() == 0.0  # noqa: SLF001


def test_step_duration_clamped_for_negative_inputs() -> None:
    metrics = get_metrics(registry=CollectorRegistry(), force_new=True)
    metrics.observe_step_duration(seconds=0.5)
    metrics.observe_step_duration(seconds=-0.1)  # ignored
    samples = list(metrics.step_duration_seconds.collect()[0].samples)
    count_sample = next(
        s for s in samples if s.name == "wake_step_duration_seconds_count"
    )
    assert count_sample.value == 1.0


# ---------------------------------------------------------------------------
# /metrics endpoint integration
# ---------------------------------------------------------------------------


def test_metrics_endpoint_returns_prom_text() -> None:
    """``GET /metrics`` returns Prometheus text exposition with the
    Wake-specific series declared even before any session ran."""
    app = create_app()
    client = TestClient(app)
    response = client.get("/metrics")
    assert response.status_code == 200, response.text
    # Prom text content type — version may vary across prom_client releases.
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    for needle in (
        "# HELP wake_sessions_total",
        "# TYPE wake_sessions_total counter",
        "# HELP wake_events_total",
        "# HELP wake_errors_total",
        "# HELP wake_step_duration_seconds",
        "# TYPE wake_step_duration_seconds histogram",
        "# HELP wake_cost_usd",
        "# HELP wake_event_count_per_session",
        "# HELP wake_worker_queue_depth",
        "# HELP wake_workers_active",
    ):
        assert needle in body, f"missing {needle!r} in /metrics output"


def test_metrics_endpoint_not_authenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    """``/metrics`` ignores the API key check (Prom convention)."""
    # Even with auth required + no key, the endpoint must respond 200.
    monkeypatch.setenv("WAKE_AUTH_REQUIRED", "true")
    monkeypatch.delenv("WAKE_API_KEY", raising=False)
    app = create_app()
    client = TestClient(app)
    response = client.get("/metrics")  # no header
    assert response.status_code == 200


def test_http_request_instrumentation_emits_series() -> None:
    """A request to any instrumented route increments the HTTP latency
    histogram exposed at /metrics."""
    app = create_app()
    client = TestClient(app)
    # Fire a request the instrumentator covers (/v1/agents → 501).
    client.get("/v1/agents")
    # Now scrape /metrics; verify the HTTP request counter shows up.
    body = client.get("/metrics").text
    assert "http_request_duration_seconds" in body
    assert "http_requests_total" in body


def test_metrics_endpoint_does_not_self_instrument() -> None:
    """Scraping ``/metrics`` MUST NOT add to its own series counts.

    Otherwise every scrape inflates ``http_requests_total`` and skews
    SLO ratios. We assert by comparing the counter value across two
    consecutive scrapes — the increment should reflect only the
    intervening non-/metrics request, not the scrapes themselves.
    """
    app = create_app()
    client = TestClient(app)
    # Issue a non-metrics request to seed the counter.
    client.get("/health")
    body_a = client.get("/metrics").text
    body_b = client.get("/metrics").text
    # Pull the http_requests_total samples summed over labels for
    # handler!=/metrics. We do a coarse string check: total occurrences
    # of '/metrics' as a handler label should remain stable.
    a_metric_lines = [
        ln for ln in body_a.splitlines() if "handler=\"/metrics\"" in ln
    ]
    b_metric_lines = [
        ln for ln in body_b.splitlines() if "handler=\"/metrics\"" in ln
    ]
    assert a_metric_lines == [], "/metrics handler should be excluded"
    assert b_metric_lines == [], "/metrics handler should remain excluded"


# ---------------------------------------------------------------------------
# Bucket sanity
# ---------------------------------------------------------------------------


def test_step_duration_histogram_has_useful_buckets() -> None:
    """Histogram buckets cover both sub-second tool calls and long
    LLM steps (up to 120s)."""
    metrics = get_metrics(registry=CollectorRegistry(), force_new=True)
    samples = list(metrics.step_duration_seconds.collect()[0].samples)
    bucket_le = sorted(
        float(s.labels["le"])
        for s in samples
        if s.name == "wake_step_duration_seconds_bucket"
        and s.labels.get("le") not in (None, "+Inf")
    )
    assert bucket_le[0] <= 0.05
    assert bucket_le[-1] >= 60.0
