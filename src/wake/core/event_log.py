"""High-level event log API.

Wraps the underlying ``EventStore`` with convenience helpers used by the
harness and API layers. The store remains the source of truth — this is
just sugar:

- ``append`` validates the event type and forwards
- ``user_message``, ``assistant_message``, ``tool_use``, ``tool_result``,
  ``status``, ``error`` helpers build well-formed payloads
- ``iter_since`` is a convenience over ``EventStore.subscribe``
"""

# Runtime types are needed by pydantic-style code paths.
# ruff: noqa: A002, TC001, TC003

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import structlog

from wake.store.base import EventStore
from wake.tenancy import DEFAULT_ORGANIZATION_ID, DEFAULT_WORKSPACE_ID
from wake.types import (
    Event,
    EventType,
    SessionStatus,
    TextBlock,
    ToolResult,
)

log = structlog.get_logger(__name__)


class EventLog:
    """Domain facade over ``EventStore``."""

    def __init__(self, store: EventStore) -> None:
        self._store = store

    # ------------------------------------------------------------------ raw

    async def append(
        self,
        session_id: str,
        event_type: EventType,
        payload: dict[str, Any],
        *,
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
        idempotency_key: str | None = None,
    ) -> Event:
        """Append an event, optionally honouring ``idempotency_key``.

        When ``idempotency_key`` is None this is a regular append.
        When set, the store will deduplicate against any prior event
        carrying the same ``(workspace_id, session_id, idempotency_key)``
        tuple and return the existing row instead of inserting a new
        one. See ``EventStore.append`` for the full contract.

        The key is mirrored into ``metadata["idempotency_key"]`` for
        observability — clients can inspect the persisted event to
        recover the dedupe key without going through a side channel.
        """
        # When the caller passes a key, ensure metadata mirrors it so
        # the persisted row carries the dedupe signal in plain sight.
        if idempotency_key is not None:
            meta = dict(metadata or {})
            meta.setdefault("idempotency_key", idempotency_key)
            metadata = meta
        return await self._store.append(
            session_id=session_id,
            event_type=event_type,
            payload=payload,
            parent_id=parent_id,
            metadata=metadata,
            organization_id=organization_id,
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
        )

    async def get(
        self,
        session_id: str,
        since: int = 0,
        *,
        workspace_id: str | None = None,
    ) -> list[Event]:
        return await self._store.get(session_id, since=since, workspace_id=workspace_id)

    async def get_one(self, event_id: str, *, workspace_id: str | None = None) -> Event | None:
        return await self._store.get_one(event_id, workspace_id=workspace_id)

    async def count(self, session_id: str, *, workspace_id: str | None = None) -> int:
        return await self._store.count(session_id, workspace_id=workspace_id)

    async def subscribe(
        self, session_id: str, since: int = 0, *, workspace_id: str | None = None
    ) -> AsyncIterator[Event]:
        # EventStore.subscribe returns AsyncIterator directly (not a
        # coroutine to be awaited).
        return await self._store.subscribe(session_id, since=since, workspace_id=workspace_id)

    # ------------------------------------------------------------------ helpers

    async def user_message(
        self,
        session_id: str,
        text: str,
        *,
        metadata: dict[str, Any] | None = None,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> Event:
        return await self.append(
            session_id,
            "user.message",
            {"content": [TextBlock(text=text).model_dump()]},
            metadata=metadata,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )

    async def assistant_message(
        self,
        session_id: str,
        text: str,
        *,
        stop_reason: str = "end_turn",
        usage: dict[str, int] | None = None,
        metadata: dict[str, Any] | None = None,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> Event:
        payload: dict[str, Any] = {
            "content": [TextBlock(text=text).model_dump()],
            "stop_reason": stop_reason,
        }
        if usage is not None:
            payload["usage"] = usage
        return await self.append(
            session_id,
            "assistant.message",
            payload,
            metadata=metadata,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )

    async def tool_use(
        self,
        session_id: str,
        tool_use_id: str,
        name: str,
        input: dict[str, Any],
        *,
        metadata: dict[str, Any] | None = None,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> Event:
        return await self.append(
            session_id,
            "tool_use",
            {"tool_use_id": tool_use_id, "name": name, "input": input},
            metadata=metadata,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )

    async def tool_result(
        self,
        session_id: str,
        tool_use_id: str,
        result: ToolResult,
        *,
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> Event:
        payload: dict[str, Any] = {
            "tool_use_id": tool_use_id,
            "content": [b.model_dump() for b in result.content],
            "is_error": result.is_error,
        }
        if result.error_code is not None:
            payload["error_code"] = result.error_code
        return await self.append(
            session_id,
            "tool_result",
            payload,
            parent_id=parent_id,
            metadata=metadata,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )

    async def status(
        self,
        session_id: str,
        from_: SessionStatus,
        to: SessionStatus,
        *,
        reason: str | None = None,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> Event:
        payload: dict[str, Any] = {"from": from_, "to": to}
        if reason is not None:
            payload["reason"] = reason
        return await self.append(
            session_id,
            "status",
            payload,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )

    async def error(
        self,
        session_id: str,
        error_type: str,
        message: str,
        *,
        trace: str | None = None,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> Event:
        payload: dict[str, Any] = {"error_type": error_type, "message": message}
        if trace is not None:
            payload["trace"] = trace
        return await self.append(
            session_id,
            "error",
            payload,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )

    # ------------------------------------------------------------------ projection

    @staticmethod
    def events_to_messages(events: list[Event]) -> list[dict[str, Any]]:
        """Project an event log into Anthropic Messages API ``messages`` list.

        Mirrors the algorithm in ``docs/SPEC-EVENT-SCHEMA.md``. Conservative:
        handles user.message, assistant.message, tool_use, tool_result. Drops
        deltas/thinking/status/error (those don't go in messages).
        """
        messages: list[dict[str, Any]] = []
        for ev in events:
            if ev.type == "user.message":
                messages.append({"role": "user", "content": ev.payload["content"]})
            elif ev.type == "assistant.message":
                messages.append({"role": "assistant", "content": ev.payload["content"]})
            elif ev.type == "tool_use":
                if not messages or messages[-1]["role"] != "assistant":
                    messages.append({"role": "assistant", "content": []})
                messages[-1]["content"].append(
                    {
                        "type": "tool_use",
                        "id": ev.payload["tool_use_id"],
                        "name": ev.payload["name"],
                        "input": ev.payload["input"],
                    }
                )
            elif ev.type == "tool_result":
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": ev.payload["tool_use_id"],
                                "content": ev.payload["content"],
                                "is_error": ev.payload.get("is_error", False),
                            }
                        ],
                    }
                )
        return messages
