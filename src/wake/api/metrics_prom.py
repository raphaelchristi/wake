"""Prometheus exposition mounting for the Wake API.

Wires ``prometheus-fastapi-instrumentator`` onto a FastAPI app and exposes
``GET /metrics`` returning the standard Prom text exposition format.

The endpoint is intentionally **unauthenticated** because:

* Prometheus scrapers don't speak ``X-Wake-API-Key``.
* The endpoint should be firewalled at the network level (e.g. only
  allow ingress from the kube-prometheus-stack namespace via NetworkPolicy)
  not via app-layer auth.

The HTTP metrics emitted by the instrumentator coexist with the
business metrics defined in :mod:`wake.observability.metrics` — both
serialize to the same ``/metrics`` response because they share the
process-global Prometheus ``REGISTRY``.

Path-grouping:

* ``/v1/sessions/abc123/events`` becomes ``/v1/sessions/{session_id}/events``
  via the standard ``handler`` group-from-route mechanism — so cardinality
  stays bounded.
* ``/metrics`` itself is excluded from the histogram (otherwise scraping
  the endpoint pollutes the metric it serves).
* ``/health``, ``/docs``, ``/redoc``, ``/openapi.json`` excluded for
  identical reasons.

Re-entrancy: ``create_app()`` can be called multiple times in the same
Python process (tests, ``--factory`` mode). Prometheus ``Counter`` /
``Histogram`` / ``Gauge`` objects are *singletons* against the global
``REGISTRY`` and raise ``ValueError`` on duplicate registration. We
therefore build the HTTP metric callables **once** at module level and
reuse the same callables on every call to :func:`install_prometheus`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_fastapi_instrumentator.metrics import (
    latency,
    request_size,
    requests,
    response_size,
)

from wake.observability.metrics import get_metrics

if TYPE_CHECKING:
    from fastapi import FastAPI


#: Paths excluded from instrumentation (no observation of the metric
#: endpoint itself; no instrumentation of low-value health probes).
_EXCLUDED_PATHS = (
    "/metrics",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
)

#: Namespace + subsystem used for the HTTP metric battery. Module level
#: so it stays in sync between first-call construction and subsequent
#: re-uses below.
_NS = "http"


#: Type of the closures produced by ``prometheus-fastapi-instrumentator``
#: factory functions. They consume one ``Info`` object per request and
#: emit metric observations. We type them via ``Any`` because the
#: upstream library returns ``Callable[[Info], None] | None`` which
#: requires a non-trivial cast through optional unwrapping.
_HttpMetricCallable = "Callable[..., Any]"


def _build_http_metric_callables() -> list[Any]:
    """Construct the HTTP metric closures **once** per process.

    Each ``latency()`` / ``requests()`` / ``request_size()`` /
    ``response_size()`` call creates a ``Histogram`` or ``Counter``
    against the global ``REGISTRY``. Calling them twice raises. We
    therefore memoise the resulting closures (which carry the
    already-registered collector objects) and hand the same list to
    every ``install_prometheus`` call.
    """
    return [
        latency(metric_namespace=_NS, metric_subsystem="request"),
        requests(metric_namespace=_NS, metric_subsystem="request"),
        request_size(metric_namespace=_NS, metric_subsystem="request"),
        response_size(metric_namespace=_NS, metric_subsystem="response"),
    ]


_HTTP_METRIC_CALLABLES: list[Any] | None = None


def install_prometheus(
    app: FastAPI,
    *,
    endpoint_path: str = "/metrics",
    expose_endpoint: bool = True,
) -> Instrumentator:
    """Mount Prometheus instrumentation + ``/metrics`` endpoint on ``app``.

    Returns the configured ``Instrumentator`` for tests that want to
    inspect or further customise.

    Parameters
    ----------
    app:
        FastAPI app to instrument. Routes added **after** this call are
        also covered because the instrumentator hooks via middleware.
    endpoint_path:
        Path served. Defaults to ``/metrics`` (Prom convention).
    expose_endpoint:
        If False, the instrumentator records but does not expose
        ``/metrics``. Useful when serving Prom from a different
        sidecar.
    """
    global _HTTP_METRIC_CALLABLES

    # Force creation of the Wake business metrics so they show up in
    # the first scrape even before any session/event happens. The
    # exposition handler reads from the global REGISTRY, which our
    # collectors join during construction.
    get_metrics()

    # ``should_instrument_requests_inprogress`` registers a separate
    # ``http_requests_inprogress`` Gauge against the global registry on
    # every ``Instrumentator(...)`` construction. To stay re-entrant we
    # keep it off; the latency histogram + status counters already
    # capture the SLO surface most operators need.
    instrumentator = Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=False,
        should_respect_env_var=False,
        should_instrument_requests_inprogress=False,
        excluded_handlers=list(_EXCLUDED_PATHS),
    )

    if _HTTP_METRIC_CALLABLES is None:
        _HTTP_METRIC_CALLABLES = _build_http_metric_callables()

    for callable_ in _HTTP_METRIC_CALLABLES:
        instrumentator.add(callable_)

    instrumentator.instrument(app)

    if expose_endpoint:
        instrumentator.expose(
            app,
            endpoint=endpoint_path,
            include_in_schema=False,
            should_gzip=True,
            tags=["observability"],
        )

    return instrumentator


__all__ = ["install_prometheus"]
