"""Exception hierarchy for the Wake client.

All exceptions raised by ``wake_ai_client`` inherit from :class:`WakeClientError`,
so callers can wrap the entire surface with a single ``except`` clause.
"""

from __future__ import annotations

from typing import Any


class WakeClientError(Exception):
    """Base class for every Wake client error."""


class WakeTransportError(WakeClientError):
    """A low-level transport problem (DNS, TLS, connection reset, timeout).

    Raised before any HTTP response is received. Use this to distinguish
    network flakes from API rejections.
    """


class WakeAPIError(WakeClientError):
    """An HTTP error returned by the Wake API.

    Attributes
    ----------
    status_code:
        The HTTP status code returned by the server.
    body:
        Parsed JSON response body, when present, else the raw string.
    detail:
        Short message extracted from ``body['detail']`` when available.
    """

    status_code: int
    body: Any
    detail: str | None

    def __init__(self, status_code: int, body: Any, detail: str | None = None) -> None:
        self.status_code = status_code
        self.body = body
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail or body}")


class WakeAuthError(WakeAPIError):
    """401/403 — missing or invalid credentials, or forbidden by RBAC."""


class WakeNotFoundError(WakeAPIError):
    """404 — the requested resource does not exist in this workspace."""


class WakeRateLimitError(WakeAPIError):
    """429 — rate-limit exceeded. Inspect :attr:`retry_after` for backoff hints."""

    retry_after: float | None

    def __init__(
        self,
        status_code: int,
        body: Any,
        detail: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(status_code, body, detail)
        self.retry_after = retry_after


class WakeServerError(WakeAPIError):
    """5xx — the server failed to satisfy the request. Eligible for retry."""
