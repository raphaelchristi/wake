"""SSE streaming helper built on ``httpx-sse``.

The Wake server publishes session events at ``GET /v1/sessions/{id}/stream`` as
SSE. The stream is resumable via ``Last-Event-ID`` (server replays any backlog
we missed when reconnecting).

This helper transparently reconnects on transport errors up to
``max_reconnects`` times, advancing ``Last-Event-ID`` each time so we don't
re-emit duplicates.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import httpx
from httpx_sse import aconnect_sse

from wake_ai_client.exceptions import (
    WakeAPIError,
    WakeAuthError,
    WakeNotFoundError,
    WakeRateLimitError,
    WakeServerError,
    WakeTransportError,
)
from wake_ai_client.types import Event

if TYPE_CHECKING:
    from wake_ai_client.client import WakeClient


HEARTBEAT_EVENT = "heartbeat"
DATA_EVENT = "event"
DEFAULT_MAX_RECONNECTS = 5
DEFAULT_RECONNECT_BACKOFF = 0.5
DEFAULT_RECONNECT_CAP = 10.0


async def iter_session_stream(
    client: WakeClient,
    session_id: str,
    *,
    since: int | None = None,
    last_event_id: str | None = None,
    max_reconnects: int = DEFAULT_MAX_RECONNECTS,
) -> AsyncIterator[Event]:
    """Yield :class:`Event` objects from the session SSE stream.

    Heartbeat events are filtered. ``Last-Event-ID`` is tracked between
    reconnects so resumption is exactly-once at the SSE layer (server-side
    deduplication is on ``seq`` so duplicates are still possible if the
    server replays — callers tolerate this via ``Event.seq``).
    """
    path = f"/v1/sessions/{_q(session_id)}/stream"
    last_id = last_event_id
    cursor = since
    attempts = 0

    while True:
        headers = client.stream_headers()
        if last_id is not None:
            headers["Last-Event-ID"] = last_id
        params: dict[str, int] = {}
        if cursor is not None and last_id is None:
            params["since"] = cursor

        try:
            async with aconnect_sse(
                client.http,
                "GET",
                path,
                headers=headers,
                params=params or None,
            ) as event_source:
                # Validate status via httpx.Response on the underlying client
                resp = event_source.response
                if resp.status_code >= 400:
                    raise _error_for_sse_response(resp)
                attempts = 0  # reset on a successful connection
                async for sse in event_source.aiter_sse():
                    if sse.event == HEARTBEAT_EVENT:
                        continue
                    if sse.event and sse.event != DATA_EVENT:
                        # Forward-compat: unknown event names are ignored.
                        continue
                    if not sse.data:
                        continue
                    try:
                        payload = json.loads(sse.data)
                    except json.JSONDecodeError:
                        # Bad frame — skip rather than die.
                        continue
                    event = Event.model_validate(payload)
                    if sse.id:
                        last_id = sse.id
                    cursor = event.seq + 1
                    yield event
            # Server closed the stream cleanly — exit the loop.
            return
        except WakeAPIError:
            # 4xx is a real client error; do not retry.
            raise
        except (httpx.TransportError, httpx.RemoteProtocolError) as exc:
            attempts += 1
            if attempts > max_reconnects:
                raise WakeTransportError(
                    f"SSE stream failed after {max_reconnects} reconnects: {exc}"
                ) from exc
            await _sleep_reconnect(attempts)
            continue


def _error_for_sse_response(response: httpx.Response) -> WakeAPIError:
    try:
        body = response.json()
    except ValueError:
        body = response.text
    detail = None
    if isinstance(body, dict) and "detail" in body:
        detail = str(body["detail"])
    status = response.status_code
    if status in (401, 403):
        return WakeAuthError(status, body, detail)
    if status == 404:
        return WakeNotFoundError(status, body, detail)
    if status == 429:
        retry_after_raw = response.headers.get("Retry-After")
        retry_after: float | None
        try:
            retry_after = float(retry_after_raw) if retry_after_raw else None
        except ValueError:
            retry_after = None
        return WakeRateLimitError(status, body, detail, retry_after=retry_after)
    if 500 <= status < 600:
        return WakeServerError(status, body, detail)
    return WakeAPIError(status, body, detail)


async def _sleep_reconnect(attempt: int) -> None:
    delay = min(DEFAULT_RECONNECT_BACKOFF * (2 ** (attempt - 1)), DEFAULT_RECONNECT_CAP)
    await asyncio.sleep(delay)


def _q(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


__all__ = ["iter_session_stream"]
