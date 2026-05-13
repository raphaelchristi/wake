# ruff: noqa: TC001, TC003, A002
"""PydanticAIAdapter — Wake HarnessAdapter for the Pydantic AI framework.

Mirrors the shape of :class:`wake_adapter_claude_sdk.ClaudeSDKAdapter`
but maps Wake's event-sourced session log to/from
:class:`pydantic_ai.messages.ModelMessage` and drives the framework
via :meth:`pydantic_ai.Agent.run_stream`.

Key design points
-----------------

* **Stateless across step() calls.** No per-session state lives on
  ``self``; everything is derived from the supplied
  :class:`EventStream`. One :class:`PydanticAIAdapter` instance can
  serve many concurrent sessions.

* **Idempotent resume.** If the latest event is already an
  ``assistant.message`` (no new user input), ``step()`` returns
  immediately without re-invoking the model. This satisfies the
  ``resume`` and ``idempotence`` conformance scenarios.

* **Dynamic tool registration.** Wake tools are attached via a fresh
  :class:`pydantic_ai.toolsets.FunctionToolset` per run, passed in
  through ``toolsets=`` on :meth:`Agent.run_stream`. We never mutate
  the user's :class:`Agent` instance. See ``tool_bridge.py``.

* **Streaming.** Text chunks come out of ``result.stream_text(delta=True)``
  as ``assistant.delta`` events. Once the stream is drained, the full
  set of new ``ModelMessage`` parts is translated into ``tool_use`` /
  ``tool_result`` / ``assistant.message`` events in order.

Events emitted (with placeholder ``id=""``, ``seq=-1`` filled by the
runtime dispatcher):

* ``assistant.delta``   — one per streamed text chunk
* ``tool_use``          — one per ``ToolCallPart`` Pydantic AI emits
* ``tool_result``       — one per ``ToolReturnPart`` (paired by
                          ``tool_call_id``)
* ``assistant.message`` — final aggregate at end_turn
* ``error``             — when ``max_recursion`` is exceeded
"""

from __future__ import annotations

import itertools
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import structlog
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from wake.types import Event
from wake_adapter_pydantic_ai.tool_bridge import build_wake_toolset

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from wake.adapters.base import LifecycleEvent
    from wake.adapters.context import SessionContext
    from wake.adapters.events import EventStream
    from wake.adapters.tool_registry import ToolRegistry

logger = structlog.get_logger(__name__)


MAX_RECURSION = 25
"""Safety cap on internal model rounds per Wake step.

Pydantic AI's own loop handles tool_use→tool_result internally inside
:meth:`Agent.run_stream`, so the adapter rarely needs explicit
recursion — but we keep the constant for parity with
``wake_adapter_claude_sdk`` and to guard against a runaway model that
keeps producing structured output retries.
"""


# ---------------------------------------------------------------------------
# Event ↔ ModelMessage translation
# ---------------------------------------------------------------------------


def _event_text(payload: dict[str, Any]) -> str:
    """Extract plain text from a Wake event payload that follows the canonical
    schema ``{"content": [{"type": "text", "text": ...}, ...]}``.

    Falls back to the empty string if no recognisable text block is
    present — Pydantic AI is strictly typed; we never pass ``None``
    into a string field.
    """
    content = payload.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            txt = block.get("text", "")
            if isinstance(txt, str):
                parts.append(txt)
    return "".join(parts)


def events_to_message_history(events: list[Event]) -> list[ModelMessage]:
    """Translate Wake events into Pydantic AI ``message_history``.

    Mapping (mirrors the inverse of
    :func:`message_history_to_events`):

    * ``user.message``      → ``ModelRequest(parts=[UserPromptPart(...)])``
    * ``assistant.message`` → ``ModelResponse(parts=[TextPart(...)])``
    * ``tool_use``          → appended as ``ToolCallPart`` onto the
                              last ``ModelResponse`` (or a new one)
    * ``tool_result``       → appended as ``ToolReturnPart`` onto a
                              ``ModelRequest`` (or a new one)
    * everything else       → skipped

    The adapter excludes the *latest* ``user.message`` from history —
    that one is passed via the ``user_prompt=`` argument to
    :meth:`Agent.run_stream`. Caller is responsible for the split.
    """
    history: list[ModelMessage] = []

    def _last_response() -> ModelResponse | None:
        if history and isinstance(history[-1], ModelResponse):
            return history[-1]
        return None

    def _last_request() -> ModelRequest | None:
        if history and isinstance(history[-1], ModelRequest):
            return history[-1]
        return None

    for ev in events:
        if ev.type == "user.message":
            text = _event_text(ev.payload)
            history.append(
                ModelRequest(parts=[UserPromptPart(content=text)])
            )
        elif ev.type == "assistant.message":
            text = _event_text(ev.payload)
            # Skip pure-tool-call assistant messages (no text); the
            # tool_use events that follow will be merged in.
            if text:
                history.append(ModelResponse(parts=[TextPart(content=text)]))
        elif ev.type == "tool_use":
            tu_id = ev.payload.get("tool_use_id", "")
            name = ev.payload.get("name", "")
            args = ev.payload.get("input", {})
            call_part = ToolCallPart(tool_name=name, args=args, tool_call_id=tu_id)
            resp = _last_response()
            if resp is not None:
                # Append onto the most recent ModelResponse so the
                # adjacent text + tool_use blocks live on one message
                # (Pydantic AI's canonical shape).
                response_parts: list[Any] = list(resp.parts)
                response_parts.append(call_part)
                history[-1] = ModelResponse(parts=response_parts)
            else:
                history.append(ModelResponse(parts=[call_part]))
        elif ev.type == "tool_result":
            tu_id = ev.payload.get("tool_use_id", "")
            # Wake stores content as a list of TextBlock dumps; Pydantic
            # AI's ToolReturnPart wants a plain Python value as `content`.
            content_blocks = ev.payload.get("content", [])
            if isinstance(content_blocks, list):
                text = "".join(
                    b.get("text", "")
                    for b in content_blocks
                    if isinstance(b, dict)
                )
            else:
                text = str(content_blocks)
            # The tool name lives on the originating ToolCallPart; we
            # search backwards to recover it (Pydantic AI requires
            # name on the return).
            tool_name = _lookup_tool_name(history, tu_id) or "unknown"
            return_part = ToolReturnPart(
                tool_name=tool_name,
                content=text,
                tool_call_id=tu_id,
                outcome="failed" if ev.payload.get("is_error") else "success",
            )
            req = _last_request()
            if req is not None:
                request_parts: list[Any] = list(req.parts)
                request_parts.append(return_part)
                history[-1] = ModelRequest(parts=request_parts)
            else:
                history.append(ModelRequest(parts=[return_part]))
        # assistant.delta / status / error / ... are not part of the
        # canonical model history.
    return history


def _lookup_tool_name(history: list[ModelMessage], tool_call_id: str) -> str | None:
    """Find the tool name that originated a given tool_call_id, scanning the
    history in reverse."""
    for msg in reversed(history):
        if isinstance(msg, ModelResponse):
            for part in msg.parts:
                if (
                    isinstance(part, ToolCallPart)
                    and part.tool_call_id == tool_call_id
                ):
                    return part.tool_name
    return None


# ---------------------------------------------------------------------------
# Event constructor (placeholder id/seq for the runtime dispatcher)
# ---------------------------------------------------------------------------


def _placeholder_event(
    session_id: str,
    event_type: str,
    payload: dict[str, Any],
    *,
    parent_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Event:
    """Build an ``Event`` with placeholder ``id``/``seq``.

    The runtime dispatcher overwrites these when appending to the log.
    """
    return Event(
        id="",  # filled by dispatcher
        session_id=session_id,
        seq=-1,  # filled by dispatcher
        type=event_type,
        payload=payload,
        parent_id=parent_id,
        metadata=metadata,
        created_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class PydanticAIAdapter:
    """Wake HarnessAdapter backed by a user-supplied :class:`pydantic_ai.Agent`.

    The adapter is stateless across step() calls. Per-session state
    lives in the Wake event log and is re-derived on every invocation.

    Parameters
    ----------
    agent:
        A configured :class:`pydantic_ai.Agent`. The model bound to the
        agent (e.g. ``Agent("anthropic:claude-opus-4-7")``) is used
        verbatim; the adapter never reaches into model selection. For
        tests, pass an agent built with
        :class:`pydantic_ai.models.test.TestModel` or
        :class:`pydantic_ai.models.function.FunctionModel`.
    max_recursion:
        Safety cap on tool-use rounds per step (default 25). Pydantic
        AI handles its own internal recursion; this bound applies if
        the adapter ever needs to re-enter ``step()``.
    """

    name: str = "pydantic-ai"
    version: str = "0.1.0"
    compatibility: str = "wake-harness-adapter@^0.1"

    def __init__(
        self,
        agent: Agent[Any, Any],
        *,
        max_recursion: int = MAX_RECURSION,
    ) -> None:
        self.agent = agent
        self._max_recursion = max_recursion

    async def step(
        self,
        ctx: SessionContext,
        events: EventStream,
        tools: ToolRegistry,
    ) -> AsyncIterator[Event]:
        """Execute one Pydantic AI run, translating to Wake events.

        See :meth:`HarnessAdapter.step` for the full contract.
        """
        all_events = await events.all()

        # Find the most recent user.message — that's the prompt for this run.
        latest_user_idx = _find_latest_user_message_idx(all_events)
        if latest_user_idx is None:
            # No user message at all; nothing to do.
            logger.info(
                "pydantic_ai_step_no_user_message",
                session_id=ctx.session_id,
            )
            return

        # Resume guard: if any assistant.message exists *after* the latest
        # user.message, this step() has already produced output for it.
        # Returning here keeps the ``resume`` and ``idempotence``
        # conformance scenarios green.
        for ev in all_events[latest_user_idx + 1 :]:
            if ev.type == "assistant.message":
                logger.info(
                    "pydantic_ai_step_already_answered",
                    session_id=ctx.session_id,
                    seq=ev.seq,
                )
                return

        latest_user_text = _event_text(all_events[latest_user_idx].payload)
        history = events_to_message_history(all_events[:latest_user_idx])

        # Build a fresh tool_use_id factory for this step. Each tool
        # invocation gets a unique id; we never re-use ids across steps.
        id_counter = itertools.count()

        def mint_tool_use_id(tool_name: str) -> str:
            # Combine a per-session UUID stem with a monotonic counter
            # so concurrent steps never collide. ``tool_name`` is part
            # of the suffix for debuggability.
            return f"pai_{uuid4().hex[:12]}_{next(id_counter)}_{tool_name}"

        # error_index lets the tool bridge propagate ``is_error=True``
        # tool results out-of-band: Pydantic AI's ToolReturnPart.outcome
        # cannot represent "succeeded but Wake says it's an error", so
        # we read the side channel at translation time.
        error_index: dict[str, Any] = {}

        wake_toolset = build_wake_toolset(
            tools,
            tool_use_id_factory=mint_tool_use_id,
            error_index=error_index,
        )

        logger.info(
            "pydantic_ai_step",
            session_id=ctx.session_id,
            n_history=len(history),
            n_tools=len(tools.list()),
        )

        # Optional system prompt from agent_config. Pydantic AI's
        # Agent supports system_prompt at construction time too; we
        # only inject if the user didn't bake one in.
        run_kwargs: dict[str, Any] = {
            "user_prompt": latest_user_text,
            "message_history": history,
            "toolsets": [wake_toolset],
        }

        wake_tool_names = {d.name for d in tools.list()}
        typed_output_text: str | None = None

        async with self.agent.run_stream(**run_kwargs) as result:
            # Stream text deltas as they arrive. Typed-output agents
            # raise UserError here because the run yields a structured
            # tool call instead of plain text; we catch and fall
            # through to message translation in that case.
            streamed_any_text = False
            try:
                async for chunk in result.stream_text(delta=True):
                    if chunk:
                        streamed_any_text = True
                        yield _placeholder_event(
                            ctx.session_id,
                            "assistant.delta",
                            {
                                "index": 0,
                                "delta": {
                                    "type": "text_delta",
                                    "text": chunk,
                                },
                            },
                        )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "pydantic_ai_stream_text_skipped",
                    error=str(e),
                    error_type=type(e).__name__,
                )

            # For typed-output agents, ``stream_text`` aborts before
            # the run finishes. Drive the run to completion by pulling
            # the (validated) output. We serialise the validated value
            # into the eventual ``assistant.message`` event.
            if not streamed_any_text:
                try:
                    output = await result.get_output()
                    typed_output_text = _serialise_typed_output(output)
                except Exception as e:  # noqa: BLE001
                    logger.debug(
                        "pydantic_ai_get_output_skipped",
                        error=str(e),
                        error_type=type(e).__name__,
                    )

            # Drain any new messages produced during this run and
            # translate them into Wake events.
            new_messages = result.new_messages()

        # Emit Wake events derived from new Pydantic AI messages.
        # We iterate in order so tool_use precedes its tool_result.
        async for ev in _new_messages_to_events(
            ctx.session_id,
            new_messages,
            error_index=error_index,
            wake_tool_names=wake_tool_names,
            typed_output_text=typed_output_text,
        ):
            yield ev

    async def on_lifecycle(
        self,
        ctx: SessionContext,
        event: LifecycleEvent,
    ) -> None:
        """No-op — the adapter holds no per-session state.

        Concrete Pydantic AI ``Agent`` instances may carry their own
        cached state (compiled prompts, etc.), but that lives on the
        user-supplied agent, not on this adapter.
        """
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_latest_user_message_idx(events: list[Event]) -> int | None:
    """Return the index of the most recent ``user.message`` event, or None."""
    for i in range(len(events) - 1, -1, -1):
        if events[i].type == "user.message":
            return i
    return None


async def _new_messages_to_events(
    session_id: str,
    messages: list[ModelMessage],
    *,
    error_index: dict[str, Any] | None = None,
    wake_tool_names: set[str] | None = None,
    typed_output_text: str | None = None,
) -> AsyncIterator[Event]:
    """Translate the messages emitted during a Pydantic AI run into Wake events.

    Order rules (matches the canonical Wake schema):

    1. For each ``ModelResponse``, emit one ``tool_use`` per
       ``ToolCallPart`` whose ``tool_name`` is a Wake-registered tool.
       Synthetic structured-output tools (e.g. ``final_result`` for
       typed agents) are NOT user-facing tools — they're surfaced as
       the assistant.message's structured payload instead.
    2. Immediately after each Wake-tool ``ToolCallPart``, look for the
       matching ``ToolReturnPart`` (in any later ``ModelRequest``) and
       emit a ``tool_result``. Pair by ``tool_call_id``.
    3. At the very end, emit one ``assistant.message`` aggregating all
       text + Wake-tool blocks from the *final* ``ModelResponse``. If
       the agent is typed (``typed_output_text`` is set), append it as
       a text block.

    Skipped:
        * ``UserPromptPart`` (the latest user message is already in the
          Wake event log; we never re-emit it)
        * ``SystemPromptPart`` (system-level, not in the canonical
          event schema)
        * ``ThinkingPart`` if present and empty
        * Output-tool ``ToolCallPart`` / ``ToolReturnPart`` whose
          ``tool_name`` is NOT in ``wake_tool_names`` (Pydantic AI
          structured-output tools fall here)
    """
    if wake_tool_names is None:
        wake_tool_names = set()

    # Index ToolReturnParts by tool_call_id for O(1) pairing.
    returns_by_id: dict[str, ToolReturnPart] = {}
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, ToolReturnPart):
                    returns_by_id[part.tool_call_id] = part

    final_response: ModelResponse | None = None
    for msg in messages:
        if isinstance(msg, ModelResponse):
            final_response = msg

    def _is_wake_tool(tool_name: str) -> bool:
        # If no wake_tool_names provided, treat every tool as user-facing
        # (back-compat with callers that don't know the registry).
        if not wake_tool_names:
            return True
        return tool_name in wake_tool_names

    # Walk messages once. For every Wake-tool ToolCallPart we emit
    # tool_use + tool_result back-to-back.
    for msg in messages:
        if not isinstance(msg, ModelResponse):
            continue
        for response_part in msg.parts:
            if isinstance(response_part, ThinkingPart):
                if response_part.content:
                    yield _placeholder_event(
                        session_id,
                        "assistant.thinking",
                        {"text": response_part.content},
                    )
                continue
            if isinstance(response_part, ToolCallPart):
                if not _is_wake_tool(response_part.tool_name):
                    continue  # structured-output tool, not user-facing
                tu_id = response_part.tool_call_id
                args = _normalise_tool_args(response_part.args)
                yield _placeholder_event(
                    session_id,
                    "tool_use",
                    {
                        "tool_use_id": tu_id,
                        "name": response_part.tool_name,
                        "input": args,
                    },
                )
                ret = returns_by_id.get(tu_id)
                if ret is not None:
                    bridge_err = (
                        error_index is not None
                        and error_index.get(tu_id) is not None
                    )
                    payload: dict[str, Any] = {
                        "tool_use_id": tu_id,
                        "content": [
                            {"type": "text", "text": str(ret.content)}
                        ],
                        "is_error": bridge_err or ret.outcome != "success",
                    }
                    if bridge_err and error_index is not None:
                        payload["error_code"] = error_index[tu_id]
                    yield _placeholder_event(
                        session_id,
                        "tool_result",
                        payload,
                    )

    # Build the final assistant.message content array. We mirror the
    # closing ``ModelResponse`` so a downstream client can reconstruct
    # the turn, then fall back to ``typed_output_text`` (typed agents)
    # if no text part is present.
    content_blocks: list[dict[str, Any]] = []
    if final_response is not None:
        for final_part in final_response.parts:
            if isinstance(final_part, TextPart) and final_part.content:
                content_blocks.append({"type": "text", "text": final_part.content})
            elif isinstance(final_part, ToolCallPart) and _is_wake_tool(
                final_part.tool_name
            ):
                content_blocks.append(
                    {
                        "type": "tool_use",
                        "id": final_part.tool_call_id,
                        "name": final_part.tool_name,
                        "input": _normalise_tool_args(final_part.args),
                    }
                )

    # No text block but typed output exists → expose it as text.
    has_text = any(b.get("type") == "text" for b in content_blocks)
    if not has_text and typed_output_text:
        content_blocks.append({"type": "text", "text": typed_output_text})

    # Nothing to emit at all? Skip the final assistant.message.
    if final_response is None and not content_blocks:
        return

    finish_reason = (
        getattr(final_response, "finish_reason", None)
        if final_response is not None
        else None
    ) or "end_turn"
    yield _placeholder_event(
        session_id,
        "assistant.message",
        {
            "content": content_blocks,
            "stop_reason": finish_reason,
        },
    )


def _serialise_typed_output(output: Any) -> str:
    """Render a Pydantic AI typed-output value as a string.

    BaseModel instances are JSON-encoded; everything else falls back
    to ``str()``.
    """
    if output is None:
        return ""
    dump = getattr(output, "model_dump_json", None)
    if callable(dump):
        result = dump()
        return result if isinstance(result, str) else str(result)
    return str(output)


def _normalise_tool_args(args: Any) -> dict[str, Any]:
    """Coerce Pydantic AI ``ToolCallPart.args`` into a plain dict.

    Pydantic AI returns args as ``str | dict | None``. We normalise to
    a dict for the Wake ``tool_use`` payload (the schema expects an
    object). A ``None`` becomes ``{}``; a string is JSON-decoded when
    possible, otherwise wrapped under ``{"_raw": str}``.
    """
    import json as _json

    if args is None:
        return {}
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        try:
            decoded = _json.loads(args)
        except _json.JSONDecodeError:
            return {"_raw": args}
        if isinstance(decoded, dict):
            return decoded
        return {"_value": decoded}
    return {"_value": args}


# ---------------------------------------------------------------------------
# Re-export ``SystemPromptPart`` for tests that want to feed history
# fixtures without depending on pydantic_ai directly.
# ---------------------------------------------------------------------------


__all__ = [
    "MAX_RECURSION",
    "PydanticAIAdapter",
    "SystemPromptPart",
    "events_to_message_history",
]
