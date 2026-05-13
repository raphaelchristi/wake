"""Event ↔ LangChain message mapping.

Translates between the canonical Wake event log and LangGraph's
``messages`` state.

Wake event types and how they're mapped to LangChain messages:

- ``user.message``      → ``HumanMessage``
- ``assistant.message`` → ``AIMessage`` (content + any embedded tool_calls)
- ``tool_use``          → ``tool_calls`` attached to the most recent
                          ``AIMessage`` (or a new empty ``AIMessage``)
- ``tool_result``       → ``ToolMessage`` (tool_call_id correlated to a
                          prior tool_use)

The reverse direction (LangChain ``BaseMessage`` → Wake ``Event``) skips
``HumanMessage`` because users emit those, not adapters.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from wake.types import Event

if TYPE_CHECKING:
    from collections.abc import Iterator


def _text_from_content(content: Any) -> str:
    """Extract plain text from Wake-style content (string or list of blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                txt = block.get("text", "")
                if isinstance(txt, str):
                    parts.append(txt)
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return ""


def _text_to_blocks(text: str) -> list[dict[str, Any]]:
    """Wrap a plain string in a single text block."""
    return [{"type": "text", "text": text}]


def events_to_state(
    events: list[Event],
    *,
    state_key: str = "messages",
    system: str | None = None,
) -> dict[str, list[BaseMessage]]:
    """Translate Wake events into a LangGraph state seed.

    Rules:
        - ``user.message``      → ``HumanMessage``
        - ``assistant.message`` → ``AIMessage`` with content and any
                                  embedded ``tool_use`` blocks materialised
                                  as ``tool_calls``
        - ``tool_use``          → ``tool_calls`` appended onto the trailing
                                  ``AIMessage`` (or a fresh empty one)
        - ``tool_result``       → ``ToolMessage`` correlated by
                                  ``tool_use_id``
        - everything else       → skipped

    ``system``, if provided, is prepended as a ``SystemMessage``.
    """
    messages: list[BaseMessage] = []
    if system:
        messages.append(SystemMessage(content=system))

    for ev in events:
        payload = ev.payload or {}
        if ev.type == "user.message":
            messages.append(HumanMessage(content=_text_from_content(payload.get("content"))))
        elif ev.type == "assistant.message":
            content_blocks = payload.get("content") or []
            text = _text_from_content(content_blocks)
            tool_calls: list[dict[str, Any]] = []
            if isinstance(content_blocks, list):
                for block in content_blocks:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_calls.append(
                            {
                                "name": block.get("name", ""),
                                "args": block.get("input", {}) or {},
                                "id": block.get("id", ""),
                                "type": "tool_call",
                            }
                        )
            ai_kwargs: dict[str, Any] = {"content": text}
            if tool_calls:
                ai_kwargs["tool_calls"] = tool_calls
            messages.append(AIMessage(**ai_kwargs))
        elif ev.type == "tool_use":
            tc = {
                "name": payload.get("name", ""),
                "args": payload.get("input", {}) or {},
                "id": payload.get("tool_use_id", ""),
                "type": "tool_call",
            }
            # Attach to the trailing AIMessage if one exists, else create a
            # new placeholder AIMessage to host the tool_call.
            attached = False
            for i in range(len(messages) - 1, -1, -1):
                m = messages[i]
                if isinstance(m, AIMessage):
                    existing: list[Any] = (
                        list(m.tool_calls) if m.tool_calls else []
                    )
                    existing.append(tc)
                    # AIMessage is a pydantic model; rebuild with new tool_calls
                    messages[i] = AIMessage(content=m.content, tool_calls=existing)
                    attached = True
                    break
                if isinstance(m, (HumanMessage, ToolMessage)):
                    # Stop walking — we can't attach across a turn boundary.
                    break
            if not attached:
                messages.append(AIMessage(content="", tool_calls=[tc]))
        elif ev.type == "tool_result":
            content_blocks = payload.get("content") or []
            text = _text_from_content(content_blocks)
            messages.append(
                ToolMessage(
                    content=text,
                    tool_call_id=payload.get("tool_use_id", ""),
                )
            )
        # Other event types (status, assistant.delta, error, ...) are skipped
        # — they aren't part of the model's working context.

    return {state_key: messages}


def message_to_wake_events(
    msg: BaseMessage,
    *,
    session_id: str,
) -> Iterator[Event]:
    """Yield zero or more Wake events for a LangChain message.

    Rules:
        - ``HumanMessage``  → no events (users emit user.message, not adapters)
        - ``SystemMessage`` → no events (system prompt is in agent config)
        - ``AIMessage``     → ``assistant.message`` (always) plus one
                              ``tool_use`` per ``tool_call``
        - ``ToolMessage``   → ``tool_result``

    The yielded events carry placeholder ``id=""``/``seq=-1``; the Wake
    dispatcher fills these in when persisting to the log.
    """
    if isinstance(msg, HumanMessage):
        return
    if isinstance(msg, SystemMessage):
        return

    if isinstance(msg, AIMessage):
        # Build content blocks: text first, then tool_use blocks.
        content_blocks: list[dict[str, Any]] = []
        text = _stringify_content(msg.content)
        if text:
            content_blocks.append({"type": "text", "text": text})
        for tc in msg.tool_calls or []:
            content_blocks.append(
                {
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": tc.get("name", ""),
                    "input": tc.get("args", {}) or {},
                }
            )

        # If the assistant emitted tool_calls, surface them BEFORE the
        # aggregate assistant.message so the runtime can see the
        # tool_use events in causal order. The assistant.message itself
        # carries the same blocks for re-hydration.
        for tc in msg.tool_calls or []:
            yield _placeholder_event(
                session_id,
                "tool_use",
                {
                    "tool_use_id": tc.get("id", ""),
                    "name": tc.get("name", ""),
                    "input": tc.get("args", {}) or {},
                },
            )
        yield _placeholder_event(
            session_id,
            "assistant.message",
            {
                "content": content_blocks,
                "stop_reason": "tool_use" if msg.tool_calls else "end_turn",
            },
        )
        return

    if isinstance(msg, ToolMessage):
        text = _stringify_content(msg.content)
        is_error = False
        # LangChain marks tool errors via ``status`` (v0.3+) or via the
        # ``additional_kwargs``/``response_metadata`` fields. We honour
        # ``status="error"`` when present and fall back to is_error=False.
        status = getattr(msg, "status", None)
        if status == "error":
            is_error = True
        yield _placeholder_event(
            session_id,
            "tool_result",
            {
                "tool_use_id": getattr(msg, "tool_call_id", "") or "",
                "content": _text_to_blocks(text),
                "is_error": is_error,
            },
        )
        return


def _stringify_content(content: Any) -> str:
    """LangChain message ``content`` can be str or list of blocks.

    Normalise to a single string for emission into ``assistant.message``/
    ``tool_result`` payloads.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                txt = block.get("text") or block.get("content")
                if isinstance(txt, str):
                    parts.append(txt)
        return "".join(parts)
    return ""


def _placeholder_event(
    session_id: str,
    event_type: str,
    payload: dict[str, Any],
    *,
    parent_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Event:
    """Construct an ``Event`` with placeholder id/seq for the dispatcher.

    The dispatcher overwrites ``id`` and ``seq`` when it persists the
    event into the session log.
    """
    return Event(
        id="",
        session_id=session_id,
        seq=-1,
        type=event_type,
        payload=payload,
        parent_id=parent_id,
        metadata=metadata,
        created_at=datetime.now(UTC),
    )


__all__ = [
    "events_to_state",
    "message_to_wake_events",
]
