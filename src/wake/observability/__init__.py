"""Wake observability — Prometheus metrics + structured logging helpers.

Phase 7 / Tier 1 gap #8. Exposes counters, histograms, and gauges that
quantify Wake's operational behaviour:

* ``wake_sessions_total{status}`` — counter of session terminal transitions.
* ``wake_events_total{type, workspace}`` — counter of events appended.
* ``wake_errors_total{code}`` — counter of business-level errors.
* ``wake_step_duration_seconds`` — histogram of adapter step latency.
* ``wake_cost_usd`` — histogram of per-event cost in USD.
* ``wake_event_count_per_session`` — histogram of events per terminated session.
* ``wake_worker_queue_depth`` — gauge of pending sessions in dispatcher queue.
* ``wake_workers_active`` — gauge of workers currently processing sessions.

The ``workspace`` label is **opt-in** via ``WAKE_METRICS_WORKSPACE_LABEL=true``
because high-cardinality labels (1000s of workspaces) can blow up the
time-series database in production multi-tenant deployments.

The module is import-safe: instantiation of the underlying ``Counter`` /
``Histogram`` / ``Gauge`` lives in module scope so the metrics survive
multiple ``create_app()`` calls in the same process (tests, factory mode).
"""

from __future__ import annotations

from wake.observability.metrics import (
    WAKE_METRICS_WORKSPACE_LABEL_ENV,
    WakeMetrics,
    get_metrics,
    workspace_label_enabled,
)

__all__ = [
    "WAKE_METRICS_WORKSPACE_LABEL_ENV",
    "WakeMetrics",
    "get_metrics",
    "workspace_label_enabled",
]
