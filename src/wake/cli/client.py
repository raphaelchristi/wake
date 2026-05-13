"""HTTP client for the Wake API server.

The CLI is intentionally thin: every command translates to a single
HTTP call (or a long-lived SSE stream) against a running Wake server.
Foundation/runtime slices are NEVER imported here — they reach us only
via the wire format documented in ``phases/PHASE-1-CONTRACT.md``.

Design notes
------------

* All blocking IO uses ``httpx`` — sync inside command callbacks (Typer
  doesn't play well with async by default), async inside the streaming
  helpers (which need cooperative concurrency to interleave SSE reads
  with a render loop).
* We do NOT eagerly parse responses into ``wake.types`` Pydantic
  models. The API contract is JSON-over-HTTP and the CLI only needs
  best-effort field access — being permissive keeps the CLI usable
  even while the server's schemas evolve.
* Errors are surfaced as :class:`WakeAPIError`, a plain ``RuntimeError``
  subclass carrying ``status_code`` so command handlers can format
  consistent messages.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

import httpx

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterable

DEFAULT_SERVER = "http://localhost:8080"
"""Fallback Wake server URL when ``WAKE_SERVER`` is unset."""

DEFAULT_TIMEOUT = 30.0
"""Default HTTP timeout, in seconds, for non-streaming requests."""


class WakeAPIError(RuntimeError):
    """Raised when the Wake server returns a non-2xx status.

    Attributes
    ----------
    status_code:
        HTTP status code returned by the server.
    body:
        Raw response body (may be JSON or plain text).
    """

    def __init__(self, status_code: int, body: str, message: str | None = None) -> None:
        self.status_code = status_code
        self.body = body
        detail = message or _summarise_error(status_code, body)
        super().__init__(detail)


def _summarise_error(status_code: int, body: str) -> str:
    """Format a one-line error summary suitable for terminal output."""
    body = body.strip()
    if not body:
        return f"HTTP {status_code}"
    # Try to surface FastAPI-style {"detail": "..."} cleanly.
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return f"HTTP {status_code}: {body[:200]}"
    if isinstance(parsed, dict):
        detail = parsed.get("detail") or parsed.get("error") or parsed.get("message")
        if detail is not None:
            return f"HTTP {status_code}: {detail}"
    return f"HTTP {status_code}: {body[:200]}"


def resolve_server(override: str | None = None) -> str:
    """Resolve the Wake server URL.

    Priority: explicit argument > ``WAKE_SERVER`` env var > default.
    """
    if override:
        return override.rstrip("/")
    env = os.environ.get("WAKE_SERVER")
    if env:
        return env.rstrip("/")
    return DEFAULT_SERVER


class WakeClient:
    """Synchronous client for the Wake REST API.

    Use as a context manager to ensure connections are released::

        with WakeClient() as client:
            agent = client.create_agent(name="hello", model="claude-opus-4-7")
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = resolve_server(base_url)
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={"User-Agent": "wake-cli/0.0.1"},
        )

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> WakeClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        response = self._client.request(method, path, json=json_body, params=params)
        if response.status_code >= 400:
            raise WakeAPIError(response.status_code, response.text)
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except json.JSONDecodeError:
            return response.text

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        """Hit ``GET /health`` (or ``/``) to check the server is alive.

        Returns the parsed JSON body if available; otherwise an empty
        dict. Raises :class:`WakeAPIError` if the server responds with
        a non-2xx status.
        """
        for path in ("/health", "/"):
            try:
                result = self._request("GET", path)
            except WakeAPIError as exc:
                if exc.status_code == 404:
                    continue
                raise
            return result if isinstance(result, dict) else {"status": "ok"}
        return {"status": "ok"}

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------

    def create_agent(
        self,
        *,
        name: str,
        model: str,
        system: str | None = None,
        tools: Iterable[str] | None = None,
        description: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "name": name,
            "model": {"id": model},
        }
        if system is not None:
            body["system"] = system
        if tools is not None:
            body["tools"] = [{"type": t} for t in tools]
        if description is not None:
            body["description"] = description
        if metadata:
            body["metadata"] = metadata
        return self._request("POST", "/v1/agents", json_body=body) or {}

    def list_agents(self) -> list[dict[str, Any]]:
        result = self._request("GET", "/v1/agents")
        return _coerce_list(result)

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/agents/{agent_id}") or {}

    def archive_agent(self, agent_id: str) -> dict[str, Any]:
        return self._request("POST", f"/v1/agents/{agent_id}/archive") or {}

    # ------------------------------------------------------------------
    # Environments
    # ------------------------------------------------------------------

    def create_environment(
        self,
        *,
        name: str,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"name": name, "config": config or {}}
        return self._request("POST", "/v1/environments", json_body=body) or {}

    def list_environments(self) -> list[dict[str, Any]]:
        return _coerce_list(self._request("GET", "/v1/environments"))

    def get_environment(self, env_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/environments/{env_id}") or {}

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def create_session(
        self,
        *,
        agent_id: str,
        environment_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"agent_id": agent_id}
        if environment_id is not None:
            body["environment_id"] = environment_id
        if metadata:
            body["metadata"] = metadata
        return self._request("POST", "/v1/sessions", json_body=body) or {}

    def list_sessions(self) -> list[dict[str, Any]]:
        return _coerce_list(self._request("GET", "/v1/sessions"))

    def get_session(self, session_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/sessions/{session_id}") or {}

    def send_event(
        self,
        session_id: str,
        *,
        event_type: str = "user.message",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "type": event_type,
            "payload": payload or {},
        }
        return (
            self._request("POST", f"/v1/sessions/{session_id}/events", json_body=body)
            or {}
        )

    def send_message(self, session_id: str, text: str) -> dict[str, Any]:
        """Convenience: send a ``user.message`` with a single text block."""
        payload = {"content": [{"type": "text", "text": text}]}
        return self.send_event(session_id, event_type="user.message", payload=payload)

    def list_events(
        self,
        session_id: str,
        *,
        since: int | None = None,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if since is not None:
            params["since"] = since
        if event_type is not None:
            params["type"] = event_type
        return _coerce_list(
            self._request("GET", f"/v1/sessions/{session_id}/events", params=params)
        )

    def interrupt_session(self, session_id: str) -> dict[str, Any]:
        return self._request("POST", f"/v1/sessions/{session_id}/interrupt") or {}

    # ------------------------------------------------------------------
    # SSE streaming (async — caller drives an event loop)
    # ------------------------------------------------------------------

    def stream_url(self, session_id: str) -> str:
        return urljoin(self.base_url + "/", f"v1/sessions/{session_id}/stream")


async def stream_events(
    base_url: str,
    session_id: str,
    *,
    last_event_id: str | None = None,
    timeout: float | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Async generator yielding decoded events from a session's SSE stream.

    Each yielded value is a dict with at least:

    * ``id`` — SSE event ID (mirrors the underlying event's ULID).
    * ``event`` — SSE event type (we map to Wake's ``EventType``).
    * ``data`` — parsed JSON payload (may be ``None`` if the data
      block wasn't valid JSON).

    The generator exits cleanly when the server closes the stream or on
    a CancelledError from the caller.
    """
    url = urljoin(base_url.rstrip("/") + "/", f"v1/sessions/{session_id}/stream")
    headers = {"Accept": "text/event-stream"}
    if last_event_id:
        headers["Last-Event-ID"] = last_event_id
    async with (
        httpx.AsyncClient(timeout=timeout) as client,
        client.stream("GET", url, headers=headers) as response,
    ):
            if response.status_code >= 400:
                body = await response.aread()
                raise WakeAPIError(response.status_code, body.decode("utf-8", "replace"))
            event_id: str | None = None
            event_name: str | None = None
            data_lines: list[str] = []
            async for raw_line in response.aiter_lines():
                # SSE framing: blank line dispatches the current event.
                if raw_line == "":
                    if data_lines:
                        data_str = "\n".join(data_lines)
                        try:
                            parsed: Any = json.loads(data_str)
                        except json.JSONDecodeError:
                            parsed = data_str
                        yield {
                            "id": event_id,
                            "event": event_name,
                            "data": parsed,
                        }
                    event_id = None
                    event_name = None
                    data_lines = []
                    continue
                if raw_line.startswith(":"):
                    # Comment / keepalive; ignore.
                    continue
                field, _, value = raw_line.partition(":")
                if value.startswith(" "):
                    value = value[1:]
                if field == "id":
                    event_id = value
                elif field == "event":
                    event_name = value
                elif field == "data":
                    data_lines.append(value)
                # other fields (retry, etc.) ignored for Phase 1.


def _coerce_list(payload: Any) -> list[dict[str, Any]]:
    """Normalise list-style responses.

    The runtime slice may return either a bare JSON array or a wrapped
    ``{"data": [...]}`` object (a common REST convention, and the shape
    used by the Anthropic Managed Agents API we mirror). We accept both
    so the CLI keeps working as the contract is finalised.
    """
    if payload is None:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        data = payload.get("data") or payload.get("items") or payload.get("results")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    return []


__all__ = [
    "DEFAULT_SERVER",
    "WakeAPIError",
    "WakeClient",
    "resolve_server",
    "stream_events",
]
