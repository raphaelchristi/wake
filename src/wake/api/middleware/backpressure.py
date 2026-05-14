"""Worker backpressure middleware.

Phase 7 ops-throughput (Tier 1 gap #4). The middleware reads the
dispatcher's in-process queue-depth gauge on every request and:

* Adds an ``X-Wake-Worker-Saturation`` header to *every* response —
  authenticated or not — so operators and SDK clients can read the
  current saturation without hitting a dedicated metrics endpoint.
  The value is a string in ``[0.000, 1.000+]`` rounded to 3 decimal
  places.
* When saturation crosses ``saturation_threshold`` (default 1.0 —
  fully saturated) the middleware short-circuits with HTTP 503 +
  ``Retry-After: 30``. The threshold + retry delay are tunable via
  env vars so deployments with bursty traffic can degrade earlier
  (e.g. 0.9) or wait longer.
* Routes that don't go through the dispatcher (``/health``, ``/docs``,
  ``/redoc``, ``/openapi.json``, the future ``/metrics`` endpoint)
  are exempt — they answer infrastructure probes that shouldn't be
  starved by application load.

The dispatcher is resolved from ``request.app.state.wake.dispatcher``;
when no dispatcher is wired (early bootstrap, tests, dev-mode app)
the middleware passes through unchanged.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.types import ASGIApp

logger = structlog.get_logger(__name__)


#: Env vars (tunable).
WAKE_BACKPRESSURE_THRESHOLD_ENV = "WAKE_BACKPRESSURE_THRESHOLD"
DEFAULT_BACKPRESSURE_THRESHOLD = 1.0

WAKE_BACKPRESSURE_RETRY_AFTER_ENV = "WAKE_BACKPRESSURE_RETRY_AFTER"
DEFAULT_BACKPRESSURE_RETRY_AFTER = 30

WAKE_BACKPRESSURE_DISABLED_ENV = "WAKE_BACKPRESSURE_DISABLED"

#: Header name surfaced on every response.
SATURATION_HEADER = "X-Wake-Worker-Saturation"

#: Paths that bypass the backpressure check entirely. These are the
#: infrastructure-probe and discovery endpoints that should stay
#: reachable even when the application is overloaded.
EXEMPT_PATHS: frozenset[str] = frozenset(
    {
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/metrics",
    }
)


def _resolve_threshold() -> float:
    raw = os.environ.get(WAKE_BACKPRESSURE_THRESHOLD_ENV, "").strip()
    if not raw:
        return DEFAULT_BACKPRESSURE_THRESHOLD
    try:
        v = float(raw)
    except ValueError:
        return DEFAULT_BACKPRESSURE_THRESHOLD
    return max(0.0, v)


def _resolve_retry_after() -> int:
    raw = os.environ.get(WAKE_BACKPRESSURE_RETRY_AFTER_ENV, "").strip()
    if not raw:
        return DEFAULT_BACKPRESSURE_RETRY_AFTER
    try:
        n = int(raw)
    except ValueError:
        return DEFAULT_BACKPRESSURE_RETRY_AFTER
    return max(1, n)


def is_disabled() -> bool:
    raw = os.environ.get(WAKE_BACKPRESSURE_DISABLED_ENV, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def format_saturation(value: float) -> str:
    """Format a saturation float into the header string (3 decimals)."""
    # Clamp negatives defensively; the dispatcher's in_flight counter
    # is always >= 0 but defensive rounding keeps the header stable
    # under integer math edge cases.
    clamped = max(0.0, value)
    return f"{clamped:.3f}"


class BackpressureMiddleware(BaseHTTPMiddleware):
    """Inject saturation header + 503 trigger when overloaded.

    Threshold and retry-after are resolved on **every request** so
    operators can SIGHUP/restart-less to retune without bouncing the
    pod. The cost is one ``os.environ.get`` per request — negligible
    compared to the rest of the request path.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        saturation_threshold: float | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(app)
        self._static_threshold = saturation_threshold
        self._static_retry = retry_after_seconds

    def threshold(self) -> float:
        return (
            self._static_threshold
            if self._static_threshold is not None
            else _resolve_threshold()
        )

    def retry_after(self) -> int:
        return (
            self._static_retry
            if self._static_retry is not None
            else _resolve_retry_after()
        )

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if is_disabled():
            return await call_next(request)

        path = request.scope.get("path", "")
        if path in EXEMPT_PATHS:
            return await call_next(request)

        dispatcher = self._resolve_dispatcher(request)
        saturation = 0.0
        if dispatcher is not None:
            saturation_method = getattr(dispatcher, "saturation", None)
            if callable(saturation_method):
                try:
                    saturation = float(saturation_method())
                except Exception:  # noqa: BLE001
                    saturation = 0.0

        threshold = self.threshold()
        if saturation >= threshold:
            retry = self.retry_after()
            body = {
                "detail": "worker pool saturated — retry later",
                "saturation": format_saturation(saturation),
                "retry_after": retry,
            }
            return Response(
                content=json.dumps(body),
                status_code=503,
                media_type="application/json",
                headers={
                    "Retry-After": str(retry),
                    SATURATION_HEADER: format_saturation(saturation),
                },
            )

        response = await call_next(request)
        response.headers[SATURATION_HEADER] = format_saturation(saturation)
        return response

    @staticmethod
    def _resolve_dispatcher(request: Request) -> object | None:
        state = getattr(request.app.state, "wake", None)
        if state is None:
            return None
        return getattr(state, "dispatcher", None)


__all__ = [
    "DEFAULT_BACKPRESSURE_RETRY_AFTER",
    "DEFAULT_BACKPRESSURE_THRESHOLD",
    "EXEMPT_PATHS",
    "SATURATION_HEADER",
    "WAKE_BACKPRESSURE_DISABLED_ENV",
    "WAKE_BACKPRESSURE_RETRY_AFTER_ENV",
    "WAKE_BACKPRESSURE_THRESHOLD_ENV",
    "BackpressureMiddleware",
    "format_saturation",
    "is_disabled",
]
