# ruff: noqa: TC001, TC003, A002
"""ClaudeSDKAdapter — reference HarnessAdapter implementation.

Mirrors the Phase 1 ``wake.harness.anthropic.AnthropicHarness`` logic but
recast onto the HarnessAdapter ABI:

- ``step()`` is an async generator that **yields** canonical Wake events;
  the runtime assigns ``seq``/``id`` and persists them before they become
  visible on the supplied ``EventStream``.
- Tools are invoked exclusively through ``tools.execute(name, input,
  tool_use_id=...)``; the adapter never reaches into a registry directly.
- ``on_lifecycle()`` is a no-op — the adapter is stateless across
  step()s.

Events emitted (placeholder fields ``id=""``, ``seq=-1`` to be filled by the
dispatcher):

* ``assistant.delta``   — one per ``text_delta`` chunk
* ``assistant.message`` — aggregate of the final content blocks + stop_reason
* ``tool_use``          — one per ``tool_use`` block before execution
* ``tool_result``       — one per executed tool (parent_id may be filled
  by the dispatcher when it's not yet known to the adapter)
* ``error``             — when ``max_recursion`` is exceeded
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from wake.types import Event

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

    from wake.adapters.base import LifecycleEvent
    from wake.adapters.context import SessionContext
    from wake.adapters.events import EventStream
    from wake.adapters.tool_registry import ToolRegistry

logger = structlog.get_logger(__name__)


MAX_RECURSION = 25
"""Safety cap on tool-use rounds per user turn.

The Anthropic loop can in principle bounce between ``tool_use`` and
``tool_result`` indefinitely. We bound it to keep a misbehaving model
from running away.
"""


def events_to_messages(events: list[Event]) -> list[dict[str, Any]]:
    """Translate Wake events into the Anthropic Messages API ``messages`` array.

    See ``docs/SPEC-EVENT-SCHEMA.md`` for the canonical mapping. Behaviour
    is identical to the Phase 1 helper of the same name (we keep the
    function so other callers can keep importing it).

    Rules:
        - ``user.message``      → role=user message
        - ``assistant.message`` → role=assistant message
        - ``tool_use``          → block appended onto the last assistant
                                  message (or a new one)
        - ``tool_result``       → role=user message containing a
                                  ``tool_result`` block
        - everything else       → skipped
    """
    messages: list[dict[str, Any]] = []
    for ev in events:
        if ev.type == "user.message":
            messages.append(
                {"role": "user", "content": ev.payload.get("content", [])}
            )
        elif ev.type == "assistant.message":
            messages.append(
                {"role": "assistant", "content": ev.payload.get("content", [])}
            )
        elif ev.type == "tool_use":
            block = {
                "type": "tool_use",
                "id": ev.payload["tool_use_id"],
                "name": ev.payload["name"],
                "input": ev.payload.get("input", {}),
            }
            if messages and messages[-1]["role"] == "assistant":
                content = messages[-1]["content"]
                if isinstance(content, str):
                    content = [{"type": "text", "text": content}] if content else []
                content.append(block)
                messages[-1]["content"] = content
            else:
                messages.append({"role": "assistant", "content": [block]})
        elif ev.type == "tool_result":
            tr_block = {
                "type": "tool_result",
                "tool_use_id": ev.payload["tool_use_id"],
                "content": ev.payload.get("content", []),
                "is_error": ev.payload.get("is_error", False),
            }
            if messages and messages[-1]["role"] == "user":
                content = messages[-1]["content"]
                if isinstance(content, list):
                    content.append(tr_block)
                else:
                    messages[-1]["content"] = [tr_block]
            else:
                messages.append({"role": "user", "content": [tr_block]})
    return messages


def _placeholder_event(
    session_id: str,
    event_type: str,
    payload: dict[str, Any],
    *,
    parent_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Event:
    """Build an ``Event`` with placeholder ``id``/``seq`` for the dispatcher.

    The dispatcher overwrites these when it appends to the event log.
    We still construct a real ``Event`` so the adapter's contract
    (``AsyncIterator[Event]``) is satisfied and tests can introspect
    payloads directly.
    """
    return Event(
        id="",  # filled by dispatcher
        session_id=session_id,
        seq=-1,  # filled by dispatcher
        type=event_type,  # type: ignore[arg-type]
        payload=payload,
        parent_id=parent_id,
        metadata=metadata,
        created_at=datetime.now(UTC),
    )


class ClaudeSDKAdapter:
    """Wake HarnessAdapter backed by the Anthropic Claude SDK.

    The adapter is stateless: every ``step()`` derives its state from the
    supplied ``EventStream`` and emits new events. A single instance can
    serve many concurrent sessions because the per-session state lives
    in the runtime, not on ``self``.
    """

    name: str = "claude-sdk"
    version: str = "0.1.0"
    compatibility: str = "wake-harness-adapter@^0.1"

    def __init__(
        self,
        client: AsyncAnthropic | None = None,
        *,
        max_tokens: int = 4096,
        max_recursion: int = MAX_RECURSION,
    ) -> None:
        if client is None:
            from anthropic import AsyncAnthropic

            self._client: Any = AsyncAnthropic()
        else:
            self._client = client
        self._max_tokens = max_tokens
        self._max_recursion = max_recursion

    async def step(
        self,
        ctx: SessionContext,
        events: EventStream,
        tools: ToolRegistry,
    ) -> AsyncIterator[Event]:
        """Execute one or more LLM rounds until ``end_turn`` or recursion cap.

        See ``HarnessAdapter.step`` for runtime/adapter guarantees.
        """
        async for ev in self._step_recursive(ctx, events, tools, depth=0):
            yield ev

    async def on_lifecycle(
        self,
        ctx: SessionContext,
        event: LifecycleEvent,
    ) -> None:
        """No-op for Claude SDK — adapter holds no per-session state."""
        return None

    # ------------------------------------------------------------------ internals

    async def _step_recursive(
        self,
        ctx: SessionContext,
        events: EventStream,
        tools: ToolRegistry,
        *,
        depth: int,
    ) -> AsyncIterator[Event]:
        """Run a single Messages API round, then recurse on tool_use.

        Recursion is implemented as a Python generator chain — each
        recursive level yields its events upstream through the parent
        ``async for``. The runtime persists each event before the next
        recursion level reads from ``events`` again.
        """
        if depth >= self._max_recursion:
            yield _placeholder_event(
                ctx.session_id,
                "error",
                {
                    "error_type": "max_recursion",
                    "message": f"reached {self._max_recursion} tool-use rounds",
                },
            )
            return

        all_events = await events.all()
        messages = events_to_messages(all_events)

        tool_descriptors = tools.list()
        anthropic_tools = self._render_anthropic_tools(tool_descriptors)

        kwargs: dict[str, Any] = {
            "model": ctx.agent_config.model.id,
            "messages": messages,
            "max_tokens": self._max_tokens,
        }
        if ctx.agent_config.system:
            kwargs["system"] = ctx.agent_config.system
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools

        logger.info(
            "claude_sdk_step",
            session_id=ctx.session_id,
            depth=depth,
            n_messages=len(messages),
            n_tools=len(anthropic_tools),
        )

        text_parts: dict[int, list[str]] = {}
        tool_uses: dict[int, dict[str, Any]] = {}
        tool_input_buffers: dict[int, list[str]] = {}
        stop_reason: str | None = None
        usage: dict[str, Any] = {}

        async with self._client.messages.stream(**kwargs) as stream:
            async for chunk in stream:
                etype = getattr(chunk, "type", None)

                if etype == "content_block_start":
                    block = getattr(chunk, "content_block", None)
                    idx = getattr(chunk, "index", 0)
                    btype = getattr(block, "type", None) if block is not None else None
                    if btype == "tool_use" and block is not None:
                        tool_uses[idx] = {
                            "id": getattr(block, "id", ""),
                            "name": getattr(block, "name", ""),
                            "input": {},
                        }
                        tool_input_buffers[idx] = []
                    elif btype == "text":
                        text_parts.setdefault(idx, [])

                elif etype == "content_block_delta":
                    idx = getattr(chunk, "index", 0)
                    delta = getattr(chunk, "delta", None)
                    dtype = getattr(delta, "type", None) if delta is not None else None
                    if dtype == "text_delta":
                        text_chunk = getattr(delta, "text", "")
                        text_parts.setdefault(idx, []).append(text_chunk)
                        yield _placeholder_event(
                            ctx.session_id,
                            "assistant.delta",
                            {
                                "index": idx,
                                "delta": {"type": "text_delta", "text": text_chunk},
                            },
                        )
                    elif dtype == "input_json_delta":
                        partial = getattr(delta, "partial_json", "")
                        tool_input_buffers.setdefault(idx, []).append(partial)

                elif etype == "content_block_stop":
                    idx = getattr(chunk, "index", 0)
                    if idx in tool_uses and idx in tool_input_buffers:
                        joined = "".join(tool_input_buffers[idx])
                        if joined:
                            try:
                                tool_uses[idx]["input"] = json.loads(joined)
                            except json.JSONDecodeError:
                                tool_uses[idx]["input"] = {"_raw": joined}

                elif etype == "message_delta":
                    delta = getattr(chunk, "delta", None)
                    if delta is not None:
                        sr = getattr(delta, "stop_reason", None)
                        if sr:
                            stop_reason = sr
                    u = getattr(chunk, "usage", None)
                    if u is not None:
                        dump_fn = getattr(u, "model_dump", None)
                        dump: dict[str, Any] = (
                            dump_fn() if callable(dump_fn) else {}
                        ) or {}
                        usage.update(dump)

                elif etype == "message_stop":
                    # Stream terminator — nothing to do; we'll emit the
                    # aggregate ``assistant.message`` below.
                    pass

        # Build the final assistant content array in index order.
        all_indexes = sorted(set(text_parts.keys()) | set(tool_uses.keys()))
        content: list[dict[str, Any]] = []
        for i in all_indexes:
            if i in tool_uses:
                tu = tool_uses[i]
                content.append(
                    {
                        "type": "tool_use",
                        "id": tu["id"],
                        "name": tu["name"],
                        "input": tu["input"],
                    }
                )
            elif i in text_parts:
                text = "".join(text_parts[i])
                if text:
                    content.append({"type": "text", "text": text})

        yield _placeholder_event(
            ctx.session_id,
            "assistant.message",
            {
                "content": content,
                "stop_reason": stop_reason or "end_turn",
                "usage": usage,
            },
        )

        # Execute tool_uses, emit tool_use + tool_result, then recurse.
        if tool_uses and stop_reason == "tool_use":
            for i in sorted(tool_uses.keys()):
                tu = tool_uses[i]
                yield _placeholder_event(
                    ctx.session_id,
                    "tool_use",
                    {
                        "tool_use_id": tu["id"],
                        "name": tu["name"],
                        "input": tu["input"],
                    },
                )

                result = await tools.execute(
                    tu["name"],
                    tu["input"],
                    tool_use_id=tu["id"],
                )

                payload: dict[str, Any] = {
                    "tool_use_id": tu["id"],
                    "content": [b.model_dump() for b in result.content],
                    "is_error": result.is_error,
                }
                if result.error_code is not None:
                    payload["error_code"] = result.error_code
                yield _placeholder_event(
                    ctx.session_id,
                    "tool_result",
                    payload,
                )

            async for ev in self._step_recursive(
                ctx, events, tools, depth=depth + 1
            ):
                yield ev

    @staticmethod
    def _render_anthropic_tools(
        descriptors: list[Any],
    ) -> list[dict[str, Any]]:
        """Render tool descriptors as the ``tools`` arg to the Messages API.

        Accepts either ``wake.types.ToolDescriptor`` or any object exposing
        ``name``/``description``/``schema`` attributes — the latter keeps
        adapter tests independent of the pydantic model. Empty list means
        ``tools`` is omitted from the API request.
        """
        out: list[dict[str, Any]] = []
        for d in descriptors:
            name = getattr(d, "name", None)
            desc = getattr(d, "description", "")
            schema = getattr(d, "schema", {})
            if not name:
                continue
            out.append(
                {
                    "name": name,
                    "description": desc,
                    "input_schema": schema,
                }
            )
        return out
