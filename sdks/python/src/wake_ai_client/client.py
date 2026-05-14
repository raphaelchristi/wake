"""``WakeClient`` — single entry point for the Wake Python SDK.

The client is async-first because the Wake API streams events over SSE and
async I/O is the natural shape for that. Construct it with a base URL +
credentials + tenant scope, then access ``client.sessions`` / ``client.agents``
sub-resources.

Auth + tenancy headers
----------------------

Every request carries:

* ``X-Wake-API-Key``       — the API key (or ``$WAKE_API_KEY`` fallback)
* ``X-Wake-Organization-Id`` — the organization scope
* ``X-Wake-Workspace-Id``    — the workspace scope
* ``X-Wake-User-Id``         — optional, required only when RBAC is on

Retries
-------

Idempotent verbs (GET, DELETE) and 429/5xx responses are retried with
exponential backoff. ``Retry-After`` is honored when present. POST/PATCH
default to *no retry* — set ``retries=N`` per call to override.
"""

from __future__ import annotations

import os
from types import TracebackType
from typing import TYPE_CHECKING, Any

import httpx

from wake_ai_client.agents import AgentsResource
from wake_ai_client.exceptions import (
    WakeAPIError,
    WakeAuthError,
    WakeNotFoundError,
    WakeRateLimitError,
    WakeServerError,
    WakeTransportError,
)
from wake_ai_client.sessions import SessionsResource

if TYPE_CHECKING:
    from collections.abc import Mapping

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 0.25
DEFAULT_BACKOFF_CAP = 8.0

# Headers (kept in sync with src/wake/api/dependencies.py)
HEADER_API_KEY = "X-Wake-API-Key"
HEADER_ORG_ID = "X-Wake-Organization-Id"
HEADER_WS_ID = "X-Wake-Workspace-Id"
HEADER_USER_ID = "X-Wake-User-Id"

ENV_API_KEY = "WAKE_API_KEY"


class WakeClient:
    """Async-first client for the Wake AI API.

    Parameters
    ----------
    base_url:
        Wake API root, e.g. ``"https://wake.example.com"``. The client
        normalizes trailing slashes.
    api_key:
        API key for ``X-Wake-API-Key``. Falls back to ``$WAKE_API_KEY``
        when omitted; pass ``None`` explicitly to disable the header
        (useful when running against a dev server with no auth).
    organization_id:
        Tenant organization, sent as ``X-Wake-Organization-Id``.
        Defaults to ``"default"``.
    workspace_id:
        Workspace scope, sent as ``X-Wake-Workspace-Id``. Defaults to
        ``"default"``.
    user_id:
        Optional principal identity for ``X-Wake-User-Id``. Required
        only when the server runs with RBAC enabled.
    timeout:
        Per-request timeout. Accepts seconds (float) or an
        ``httpx.Timeout`` for fine-grained control.
    max_retries:
        Maximum retries for retriable verbs/status codes.
    transport:
        Optional ``httpx`` transport. Tests inject ``httpx.MockTransport``
        through this parameter.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = ...,  # type: ignore[assignment]
        organization_id: str = "default",
        workspace_id: str = "default",
        user_id: str | None = None,
        timeout: float | httpx.Timeout = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        transport: httpx.AsyncBaseTransport | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        self._base_url = base_url.rstrip("/")
        # api_key sentinel: `...` means "fall back to env"; `None` means
        # "explicitly disable". Anything else is used as-is.
        if api_key is ...:
            api_key = os.environ.get(ENV_API_KEY) or None
        self._api_key = api_key
        self._organization_id = organization_id
        self._workspace_id = workspace_id
        self._user_id = user_id
        self._timeout = (
            timeout if isinstance(timeout, httpx.Timeout) else httpx.Timeout(timeout)
        )
        self._max_retries = max(0, int(max_retries))

        if http_client is not None:
            self._http = http_client
            self._owns_http = False
        else:
            self._http = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                transport=transport,
                headers=self._default_headers(),
            )
            self._owns_http = True

        self.sessions = SessionsResource(self)
        self.agents = AgentsResource(self)

    # -- Accessors -----------------------------------------------------------

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def organization_id(self) -> str:
        return self._organization_id

    @property
    def workspace_id(self) -> str:
        return self._workspace_id

    @property
    def http(self) -> httpx.AsyncClient:
        return self._http

    # -- Lifecycle -----------------------------------------------------------

    async def __aenter__(self) -> WakeClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    # -- Headers -------------------------------------------------------------

    def _default_headers(self) -> dict[str, str]:
        h: dict[str, str] = {
            HEADER_ORG_ID: self._organization_id,
            HEADER_WS_ID: self._workspace_id,
            "Accept": "application/json",
            "User-Agent": "wake-ai-client-python/0.1.0",
        }
        if self._api_key:
            h[HEADER_API_KEY] = self._api_key
        if self._user_id:
            h[HEADER_USER_ID] = self._user_id
        return h

    def stream_headers(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        """Headers used for SSE streams.

        Streams need ``Accept: text/event-stream`` instead of JSON.
        """
        h = self._default_headers()
        h["Accept"] = "text/event-stream"
        if extra:
            h.update(extra)
        return h

    # -- Core request helper -------------------------------------------------

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        retries: int | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        """Send a JSON request and return the parsed body.

        Retries honor ``Retry-After`` when present on 429 responses.
        """
        max_retries = self._max_retries if retries is None else max(0, int(retries))
        # Mutating verbs default to no retry unless the caller opts in,
        # because most are not idempotent. GET/DELETE/HEAD retry by default.
        if retries is None and method.upper() in {"POST", "PATCH", "PUT"}:
            max_retries = 0

        headers: dict[str, str] = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if json is not None:
            headers["Content-Type"] = "application/json"

        attempt = 0
        last_exc: BaseException | None = None
        while True:
            try:
                response = await self._http.request(
                    method,
                    path,
                    params=_clean_params(params),
                    json=json,
                    headers=headers or None,
                )
            except httpx.TransportError as exc:
                last_exc = exc
                if attempt >= max_retries:
                    raise WakeTransportError(str(exc)) from exc
                await _sleep_backoff(attempt)
                attempt += 1
                continue

            if response.status_code < 400:
                if response.status_code == 204 or not response.content:
                    return None
                try:
                    return response.json()
                except ValueError:
                    return response.text

            # Error path — translate + maybe retry
            retriable = response.status_code == 429 or 500 <= response.status_code < 600
            if retriable and attempt < max_retries:
                retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                await _sleep_backoff(attempt, hint=retry_after)
                attempt += 1
                last_exc = None
                continue
            raise self._error_for_response(response)

    def _error_for_response(self, response: httpx.Response) -> WakeAPIError:
        try:
            body: Any = response.json()
        except ValueError:
            body = response.text
        detail: str | None = None
        if isinstance(body, dict) and "detail" in body:
            detail = str(body["detail"])
        status = response.status_code
        if status in (401, 403):
            return WakeAuthError(status, body, detail)
        if status == 404:
            return WakeNotFoundError(status, body, detail)
        if status == 429:
            return WakeRateLimitError(
                status,
                body,
                detail,
                retry_after=_parse_retry_after(response.headers.get("Retry-After")),
            )
        if 500 <= status < 600:
            return WakeServerError(status, body, detail)
        return WakeAPIError(status, body, detail)


def _clean_params(params: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if params is None:
        return None
    out: dict[str, Any] = {}
    for k, v in params.items():
        if v is None or v == "":
            continue
        out[k] = v
    return out or None


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        # HTTP-date Retry-After is rare for APIs; skip parsing.
        return None


async def _sleep_backoff(attempt: int, *, hint: float | None = None) -> None:
    """Exponential backoff with a Retry-After override."""
    import asyncio

    if hint is not None:
        await asyncio.sleep(min(hint, DEFAULT_BACKOFF_CAP))
        return
    delay = min(DEFAULT_BACKOFF_BASE * (2**attempt), DEFAULT_BACKOFF_CAP)
    await asyncio.sleep(delay)
