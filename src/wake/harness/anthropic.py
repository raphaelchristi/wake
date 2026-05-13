# ruff: noqa: TC001
"""Anthropic SDK harness.

Phase 1 hardcodes the loop against `anthropic.AsyncAnthropic`. Phase 2 lifts
this onto a generic HarnessAdapter ABI.

Flow:
1. Load events from the event store.
2. Build `messages` for the Messages API (see `events_to_messages`).
3. Stream the response from Anthropic.
4. Buffer text deltas and tool_use blocks.
5. On message_stop:
   - if stop_reason == "end_turn": emit assistant.message and return.
   - if stop_reason == "tool_use": execute every tool_use, emit tool_use +
     tool_result events, then recurse.
"""

from __future__ import annotations

from typing import Any

import structlog

from wake.core.event_log import EventLog
from wake.sandbox.base import SandboxAdapter
from wake.tools.registry import ToolRegistry
from wake.types import AgentConfig, Event, SandboxHandle, Session

logger = structlog.get_logger(__name__)

MAX_RECURSION = 25  # safety cap on tool-use rounds per user turn


def events_to_messages(events: list[Event]) -> list[dict[str, Any]]:
    """Translate Wake events into Anthropic Messages API `messages` array.

    See SPEC-EVENT-SCHEMA.md for the canonical mapping.

    Rules:
    - `user.message`            → role=user message
    - `assistant.message`       → role=assistant message
    - `tool_use`                → append to the last assistant content
    - `tool_result`             → role=user message containing a tool_result block
    - `assistant.delta`         → skipped (final message is the aggregate)
    - everything else           → skipped (status, provision, error, etc.)
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
                # Re-pack: assistant content may be string or list
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
            # The Messages API expects consecutive tool_results in one user message.
            if messages and messages[-1]["role"] == "user":
                content = messages[-1]["content"]
                if isinstance(content, list):
                    content.append(tr_block)
                else:
                    messages[-1]["content"] = [tr_block]
            else:
                messages.append({"role": "user", "content": [tr_block]})
    return messages


class AnthropicHarness:
    """Hardcoded Anthropic harness loop.

    The harness is stateless: it only reads from the event log and emits new
    events. Multiple workers may run different sessions concurrently.
    """

    def __init__(
        self,
        event_log: EventLog,
        tool_registry: ToolRegistry,
        sandbox: SandboxAdapter | None = None,
        client: Any | None = None,
        *,
        max_tokens: int = 4096,
        max_recursion: int = MAX_RECURSION,
    ) -> None:
        self._events = event_log
        self._tools = tool_registry
        self._sandbox = sandbox
        self._max_tokens = max_tokens
        self._max_recursion = max_recursion

        if client is None:
            from anthropic import AsyncAnthropic

            self._client: Any = AsyncAnthropic()
        else:
            self._client = client

    async def run_step(
        self,
        session: Session,
        agent: AgentConfig,
        sandbox_handle: SandboxHandle | None = None,
        _depth: int = 0,
    ) -> None:
        """Run one or more LLM rounds until the model emits end_turn.

        Recurses on tool_use until end_turn or until `max_recursion` is hit.
        """
        if _depth >= self._max_recursion:
            await self._events.append(
                session.id,
                "error",
                {
                    "error_type": "max_recursion",
                    "message": f"reached {self._max_recursion} tool-use rounds",
                },
            )
            return

        events = await self._events.get(session.id)
        messages = events_to_messages(events)

        tools = self._tools.anthropic_tools()
        kwargs: dict[str, Any] = {
            "model": agent.model.id,
            "messages": messages,
            "max_tokens": self._max_tokens,
        }
        if agent.system:
            kwargs["system"] = agent.system
        if tools:
            kwargs["tools"] = tools

        logger.info(
            "harness_step",
            session_id=session.id,
            depth=_depth,
            n_messages=len(messages),
            n_tools=len(tools),
        )

        text_parts: dict[int, list[str]] = {}
        tool_uses: dict[int, dict[str, Any]] = {}
        # accumulate json deltas per tool_use index
        tool_input_buffers: dict[int, list[str]] = {}
        stop_reason: str | None = None
        usage: dict[str, Any] = {}

        async with self._client.messages.stream(**kwargs) as stream:
            async for event in stream:
                etype = getattr(event, "type", None)

                if etype == "content_block_start":
                    block = getattr(event, "content_block", None)
                    idx = getattr(event, "index", 0)
                    if block is not None and getattr(block, "type", None) == "tool_use":
                        tool_uses[idx] = {
                            "id": block.id,
                            "name": block.name,
                            "input": {},
                        }
                        tool_input_buffers[idx] = []
                    elif block is not None and getattr(block, "type", None) == "text":
                        text_parts.setdefault(idx, [])

                elif etype == "content_block_delta":
                    idx = getattr(event, "index", 0)
                    delta = getattr(event, "delta", None)
                    dtype = getattr(delta, "type", None) if delta is not None else None
                    if dtype == "text_delta":
                        chunk = getattr(delta, "text", "")
                        text_parts.setdefault(idx, []).append(chunk)
                        await self._events.append(
                            session.id,
                            "assistant.delta",
                            {"index": idx, "delta": {"type": "text_delta", "text": chunk}},
                        )
                    elif dtype == "input_json_delta":
                        partial = getattr(delta, "partial_json", "")
                        tool_input_buffers.setdefault(idx, []).append(partial)

                elif etype == "content_block_stop":
                    idx = getattr(event, "index", 0)
                    if idx in tool_uses and idx in tool_input_buffers:
                        joined = "".join(tool_input_buffers[idx])
                        if joined:
                            import json

                            try:
                                tool_uses[idx]["input"] = json.loads(joined)
                            except json.JSONDecodeError:
                                tool_uses[idx]["input"] = {"_raw": joined}

                elif etype == "message_delta":
                    delta = getattr(event, "delta", None)
                    if delta is not None:
                        sr = getattr(delta, "stop_reason", None)
                        if sr:
                            stop_reason = sr
                    u = getattr(event, "usage", None)
                    if u is not None:
                        usage.update(getattr(u, "model_dump", lambda: {})() or {})

                elif etype == "message_stop":
                    pass

        # Build the final assistant content list (text + tool_use blocks, in order)
        # The Anthropic SDK assigns indexes monotonically; we re-order by index.
        all_indexes = sorted(set(text_parts.keys()) | set(tool_uses.keys()))
        content: list[dict[str, Any]] = []
        for i in all_indexes:
            if i in tool_uses:
                tu = tool_uses[i]
                content.append(
                    {"type": "tool_use", "id": tu["id"], "name": tu["name"], "input": tu["input"]}
                )
            elif i in text_parts:
                text = "".join(text_parts[i])
                if text:
                    content.append({"type": "text", "text": text})

        # Emit assistant.message with the aggregate
        await self._events.append(
            session.id,
            "assistant.message",
            {
                "content": content,
                "stop_reason": stop_reason or "end_turn",
                "usage": usage,
            },
        )

        # Emit one tool_use event per buffered tool_use, then execute and emit results
        if tool_uses and stop_reason == "tool_use":
            for i in sorted(tool_uses.keys()):
                tu = tool_uses[i]
                tu_event = await self._events.append(
                    session.id,
                    "tool_use",
                    {"tool_use_id": tu["id"], "name": tu["name"], "input": tu["input"]},
                )
                result = await self._tools.execute(
                    tu["name"], tu["input"], sandbox_handle=sandbox_handle
                )
                await self._events.append(
                    session.id,
                    "tool_result",
                    {
                        "tool_use_id": tu["id"],
                        "content": [b.model_dump() for b in result.content],
                        "is_error": result.is_error,
                        **({"error_code": result.error_code} if result.error_code else {}),
                    },
                    parent_id=tu_event.id,
                )

            # Recurse for the next LLM round
            await self.run_step(session, agent, sandbox_handle=sandbox_handle, _depth=_depth + 1)
