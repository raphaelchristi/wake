"""Session-related operations: CRUD + interrupt + events + SSE stream."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import TYPE_CHECKING, Any

from wake_ai_client.sse import iter_session_stream
from wake_ai_client.types import Event, Session

if TYPE_CHECKING:
    from datetime import datetime

    from wake_ai_client.client import WakeClient


class SessionsResource:
    """Resource bag for ``/v1/sessions/*`` routes.

    Accessed via ``client.sessions``. All methods are coroutines.
    """

    def __init__(self, client: WakeClient) -> None:
        self._client = client

    async def create(
        self,
        *,
        agent_id: str,
        environment_id: str | None = None,
        metadata: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> Session:
        """Create a session bound to an agent (latest version)."""
        body: dict[str, Any] = {"agent_id": agent_id}
        if environment_id is not None:
            body["environment_id"] = environment_id
        if metadata is not None:
            body["metadata"] = dict(metadata)
        data = await self._client.request(
            "POST",
            "/v1/sessions",
            json=body,
            idempotency_key=idempotency_key,
        )
        return Session.model_validate(data)

    async def list(
        self,
        *,
        agent: str | None = None,
        status: str | None = None,
        model: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        q: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[Session]:
        """List sessions in the current workspace.

        Supports the same filters as the underlying ``GET /v1/sessions``.
        """
        params: dict[str, Any] = {
            "agent": agent,
            "status": status,
            "model": model,
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
            "q": q,
            "page": page,
            "page_size": page_size,
        }
        data = await self._client.request("GET", "/v1/sessions", params=params)
        return [Session.model_validate(s) for s in (data or {}).get("data", [])]

    async def get(self, session_id: str) -> Session:
        data = await self._client.request(
            "GET",
            f"/v1/sessions/{_q(session_id)}",
        )
        return Session.model_validate(data)

    async def delete(self, session_id: str) -> None:
        await self._client.request("DELETE", f"/v1/sessions/{_q(session_id)}")

    async def interrupt(self, session_id: str) -> Session:
        data = await self._client.request(
            "POST",
            f"/v1/sessions/{_q(session_id)}/interrupt",
        )
        return Session.model_validate(data)

    async def archive(self, session_id: str) -> Session:
        data = await self._client.request(
            "POST",
            f"/v1/sessions/{_q(session_id)}/archive",
        )
        return Session.model_validate(data)

    # -- Events --------------------------------------------------------------

    async def append_event(
        self,
        session_id: str,
        *,
        type: str,
        payload: Mapping[str, Any] | None = None,
        parent_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Event:
        """Append a single event to the session log.

        Posting ``user.message`` kicks the dispatcher server-side, which is the
        normal way to drive a conversation from a client.
        """
        body: dict[str, Any] = {"type": type, "payload": dict(payload or {})}
        if parent_id is not None:
            body["parent_id"] = parent_id
        if metadata is not None:
            body["metadata"] = dict(metadata)
        if idempotency_key is not None:
            body["idempotency_key"] = idempotency_key
        data = await self._client.request(
            "POST",
            f"/v1/sessions/{_q(session_id)}/events",
            json=body,
            idempotency_key=idempotency_key,
        )
        return Event.model_validate(data)

    async def list_events(
        self,
        session_id: str,
        *,
        since: int = 0,
    ) -> list[Event]:
        data = await self._client.request(
            "GET",
            f"/v1/sessions/{_q(session_id)}/events",
            params={"since": since},
        )
        return [Event.model_validate(e) for e in (data or {}).get("data", [])]

    # -- SSE stream ----------------------------------------------------------

    def stream(
        self,
        session_id: str,
        *,
        since: int | None = None,
        last_event_id: str | None = None,
    ) -> AsyncIterator[Event]:
        """Stream events as they arrive via Server-Sent Events.

        Reconnects implicitly by tracking the last ``Event.seq`` seen; if the
        underlying transport drops, the iterator surfaces the failure via
        :class:`~wake_ai_client.exceptions.WakeTransportError` so callers can
        retry the loop with their own policy.

        Usage::

            async for event in client.sessions.stream(session.id):
                print(event.type)
        """
        return iter_session_stream(
            self._client,
            session_id,
            since=since,
            last_event_id=last_event_id,
        )


def _q(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")
