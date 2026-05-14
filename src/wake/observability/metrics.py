"""Prometheus instrument registry for Wake business metrics.

Two metric families coexist in a Wake API process:

1. **HTTP metrics** — owned by ``prometheus-fastapi-instrumentator``.
   It mounts ``GET /metrics`` and ships ``http_request_duration_seconds`` +
   ``http_requests_total`` out-of-box. We do NOT redefine those here.

2. **Wake business metrics** — defined in this module. Counters /
   histograms / gauges that capture session-level, event-level, and
   worker-level behaviour. They use the **global** Prometheus
   ``CollectorRegistry`` (``prometheus_client.REGISTRY``) so the
   instrumentator's ``/metrics`` endpoint serializes them in the same
   exposition response.

Cardinality discipline:

* ``workspace`` label is OPT-IN via ``WAKE_METRICS_WORKSPACE_LABEL=true``.
  In single-tenant or low-tenant deployments it is invaluable; in a SaaS
  with 1000+ workspaces it blows up Prometheus TSDB cardinality. Default
  off keeps prod safe; operators flip it on per-environment if needed.

* ``type`` label uses the canonical Wake ``EventType`` enum (8 fixed
  values) — cardinality is bounded.

* ``status`` label uses ``SessionStatus`` terminal states only
  (``terminated`` / ``interrupted`` / ``failed``).

* ``code`` label on ``wake_errors_total`` uses a short stable string
  classification — *not* free-form exception messages.

Side-effect-free import: the metrics objects are created lazily inside
``get_metrics()`` so importing this module from typechecking contexts
(``TYPE_CHECKING`` branches) is cheap. The first runtime call to
``get_metrics()`` registers the collectors and memoises the result.
"""

from __future__ import annotations

import contextlib
import os
import threading
from dataclasses import dataclass

from prometheus_client import REGISTRY, CollectorRegistry, Counter, Gauge, Histogram

#: Env var that enables the high-cardinality ``workspace`` label.
WAKE_METRICS_WORKSPACE_LABEL_ENV = "WAKE_METRICS_WORKSPACE_LABEL"

#: Step duration histogram bucket boundaries (seconds). Tuned for
#: LLM-driven steps which are typically 0.1-30s; we include sub-second
#: buckets so non-LLM steps (tool calls, lifecycle) are still resolved.
_STEP_DURATION_BUCKETS = (
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    25.0,
    60.0,
    120.0,
)

#: Per-event cost histogram buckets (USD). Most LLM calls land in the
#: sub-cent range; the high-end captures heavy reasoning models.
_COST_USD_BUCKETS = (
    0.0001,
    0.001,
    0.01,
    0.05,
    0.10,
    0.50,
    1.0,
    5.0,
    10.0,
)

#: Events-per-session histogram buckets. A "hello world" session has
#: ~5 events; long agentic runs hit thousands.
_EVENTS_PER_SESSION_BUCKETS = (
    1,
    5,
    10,
    50,
    100,
    500,
    1_000,
    5_000,
    10_000,
)


def workspace_label_enabled() -> bool:
    """Return True iff the ``workspace`` label is opt-in for this process.

    Reads ``WAKE_METRICS_WORKSPACE_LABEL`` at call time so tests can flip
    via ``monkeypatch.setenv`` without restarting the process.
    """
    raw = os.environ.get(WAKE_METRICS_WORKSPACE_LABEL_ENV, "").strip().lower()
    return raw in ("1", "true", "yes", "on")


@dataclass
class WakeMetrics:
    """Container with all Wake-specific Prometheus instruments.

    Use :func:`get_metrics` to obtain the process-wide singleton; the
    constructor is exposed only for tests that want a private
    ``CollectorRegistry`` (avoids cross-test bleed).
    """

    sessions_total: Counter
    events_total: Counter
    errors_total: Counter
    step_duration_seconds: Histogram
    cost_usd: Histogram
    event_count_per_session: Histogram
    worker_queue_depth: Gauge
    workers_active: Gauge

    #: Whether the ``workspace`` label was active when the metrics were
    #: created. Cached because Prometheus instruments are immutable once
    #: registered — flipping the env var mid-process is a no-op.
    workspace_label_enabled: bool

    # ------------------------------------------------------------------
    # Convenience emitters (callers don't reach into instruments)
    # ------------------------------------------------------------------

    def observe_session_terminal(
        self, *, status: str, event_count: int | None = None
    ) -> None:
        """Record one terminal transition + optional event-count distribution."""
        self.sessions_total.labels(status=status).inc()
        if event_count is not None and event_count >= 0:
            self.event_count_per_session.observe(event_count)

    def observe_event_appended(self, *, event_type: str, workspace: str | None) -> None:
        """Record one event-append.

        Caller passes ``workspace`` always; the metric only labels with it
        when ``workspace_label_enabled`` is True (otherwise the label is
        constant ``"_aggregated"``).
        """
        ws_label = (workspace or "_unknown") if self.workspace_label_enabled else "_aggregated"
        self.events_total.labels(type=event_type, workspace=ws_label).inc()

    def observe_error(self, *, code: str) -> None:
        """Record one business-level error."""
        self.errors_total.labels(code=code).inc()

    def observe_step_duration(self, *, seconds: float) -> None:
        """Record one adapter-step duration."""
        if seconds < 0:
            return
        self.step_duration_seconds.observe(seconds)

    def observe_cost(self, *, usd: float) -> None:
        """Record one event-level cost in USD."""
        if usd < 0:
            return
        self.cost_usd.observe(usd)

    def set_queue_depth(self, *, depth: int) -> None:
        """Set the dispatcher pending-queue gauge."""
        self.worker_queue_depth.set(max(0, depth))

    def set_workers_active(self, *, count: int) -> None:
        """Set the active-workers gauge."""
        self.workers_active.set(max(0, count))


# ---------------------------------------------------------------------------
# Factory + process-wide singleton
# ---------------------------------------------------------------------------


_LOCK = threading.Lock()
_SINGLETON: WakeMetrics | None = None


def _build_metrics(
    *,
    registry: CollectorRegistry,
    workspace_label: bool,
) -> WakeMetrics:
    """Construct the metric instruments against ``registry``."""

    sessions_total = Counter(
        "wake_sessions_total",
        "Number of Wake session terminal transitions.",
        labelnames=("status",),
        registry=registry,
    )
    events_labels = ("type", "workspace")
    events_total = Counter(
        "wake_events_total",
        "Number of events appended to the Wake event log.",
        labelnames=events_labels,
        registry=registry,
    )
    errors_total = Counter(
        "wake_errors_total",
        "Number of Wake business-level errors classified by short stable code.",
        labelnames=("code",),
        registry=registry,
    )
    step_duration_seconds = Histogram(
        "wake_step_duration_seconds",
        "Latency of a single dispatcher adapter step in seconds.",
        buckets=_STEP_DURATION_BUCKETS,
        registry=registry,
    )
    cost_usd = Histogram(
        "wake_cost_usd",
        "Distribution of per-event cost in USD (event.metadata.cost_usd).",
        buckets=_COST_USD_BUCKETS,
        registry=registry,
    )
    event_count_per_session = Histogram(
        "wake_event_count_per_session",
        "Distribution of event count per terminated session.",
        buckets=_EVENTS_PER_SESSION_BUCKETS,
        registry=registry,
    )
    worker_queue_depth = Gauge(
        "wake_worker_queue_depth",
        "Current depth of the dispatcher's pending-session queue.",
        registry=registry,
    )
    workers_active = Gauge(
        "wake_workers_active",
        "Number of worker replicas currently processing at least one session.",
        registry=registry,
    )

    return WakeMetrics(
        sessions_total=sessions_total,
        events_total=events_total,
        errors_total=errors_total,
        step_duration_seconds=step_duration_seconds,
        cost_usd=cost_usd,
        event_count_per_session=event_count_per_session,
        worker_queue_depth=worker_queue_depth,
        workers_active=workers_active,
        workspace_label_enabled=workspace_label,
    )


def get_metrics(
    *,
    registry: CollectorRegistry | None = None,
    force_new: bool = False,
) -> WakeMetrics:
    """Return the process-wide :class:`WakeMetrics` singleton.

    The first call registers collectors against ``registry`` (defaults to
    the Prometheus global ``REGISTRY``) and memoises the result. Subsequent
    calls return the same instance regardless of arguments — Prometheus
    instruments cannot be redefined, so any other value would be a no-op
    or an error.

    Tests pass ``registry=CollectorRegistry()`` + ``force_new=True`` to
    obtain an isolated instance. The singleton is *not* updated in that
    case; production code keeps using the global one.
    """
    global _SINGLETON

    workspace_label = workspace_label_enabled()

    if force_new:
        target = registry or CollectorRegistry()
        return _build_metrics(registry=target, workspace_label=workspace_label)

    with _LOCK:
        if _SINGLETON is None:
            _SINGLETON = _build_metrics(
                registry=registry or REGISTRY,
                workspace_label=workspace_label,
            )
        return _SINGLETON


def reset_singleton_for_tests() -> None:
    """Drop the cached singleton + unregister from the global REGISTRY.

    Tests that mutate ``WAKE_METRICS_WORKSPACE_LABEL`` mid-suite call
    this between tests so the next ``get_metrics()`` re-reads the env.

    Note: in production this function is **never** called — Prometheus
    instruments are by design process-lifetime objects.
    """
    global _SINGLETON
    with _LOCK:
        if _SINGLETON is not None:
            # Best-effort unregister from the global collector. We swallow
            # KeyError because the test may already have torn down the
            # default registry through other means.
            for collector in (
                _SINGLETON.sessions_total,
                _SINGLETON.events_total,
                _SINGLETON.errors_total,
                _SINGLETON.step_duration_seconds,
                _SINGLETON.cost_usd,
                _SINGLETON.event_count_per_session,
                _SINGLETON.worker_queue_depth,
                _SINGLETON.workers_active,
            ):
                with contextlib.suppress(KeyError, ValueError):
                    REGISTRY.unregister(collector)
            _SINGLETON = None


__all__ = [
    "WAKE_METRICS_WORKSPACE_LABEL_ENV",
    "WakeMetrics",
    "get_metrics",
    "reset_singleton_for_tests",
    "workspace_label_enabled",
]
