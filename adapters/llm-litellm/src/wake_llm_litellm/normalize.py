"""Provider-response → ``NormalizedMessage`` translation.

LiteLLM always returns an OpenAI-shaped response (``choices[0].message``)
**but** when the provider is Anthropic it preserves the original
``tool_use`` content blocks under ``message.content`` as a list, and
when the provider is Ollama the tool calls land in
``message.tool_calls`` but sometimes the function arguments are
strings rather than parsed dicts.

This module collapses all of that into a single ``NormalizedMessage``
shape that the Wake substrate consumes verbatim.

We also expose ``to_wake_events`` which converts a normalized message
into the (placeholder-id, placeholder-seq) Event list the runtime
appends to the log — same convention as ``adapters/claude-sdk``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from wake.types import Event

from wake_llm_litellm.base import (
    NormalizedMessage,
    NormalizedToolCall,
    StopReason,
)


def _coerce_input(raw: Any) -> dict[str, Any]:
    """Tool-call ``input`` can arrive as a dict (Anthropic), a JSON
    string (OpenAI) or already-parsed dict (Ollama with chat template).
    Normalize to dict."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return {"_raw": raw}
        if isinstance(parsed, dict):
            return parsed
        return {"_raw": parsed}
    return {}


def _map_finish_reason(reason: str | None) -> StopReason:
    """Translate provider stop reason → Wake canonical.

    OpenAI uses ``stop`` / ``tool_calls`` / ``length``; Anthropic uses
    ``end_turn`` / ``tool_use`` / ``max_tokens``; Ollama copies whatever
    LiteLLM normalised it to.
    """
    if not reason:
        return "end_turn"
    mapping: dict[str, StopReason] = {
        "stop": "end_turn",
        "end_turn": "end_turn",
        "tool_calls": "tool_use",
        "tool_use": "tool_use",
        "length": "max_tokens",
        "max_tokens": "max_tokens",
        "stop_sequence": "stop_sequence",
    }
    return mapping.get(reason, "end_turn")


def _normalize_usage(usage: Any) -> dict[str, Any]:
    """Translate LiteLLM usage to Anthropic-style keys.

    LiteLLM exposes both shapes via ``usage`` (OpenAI naming
    ``prompt_tokens`` / ``completion_tokens``); the Wake event schema
    uses Anthropic names (``input_tokens`` / ``output_tokens``).
    """
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        data = usage.model_dump()
    elif hasattr(usage, "dict"):
        data = usage.dict()
    elif isinstance(usage, dict):
        data = dict(usage)
    else:
        return {}

    out: dict[str, Any] = {}
    out["input_tokens"] = int(
        data.get("prompt_tokens") or data.get("input_tokens") or 0
    )
    out["output_tokens"] = int(
        data.get("completion_tokens") or data.get("output_tokens") or 0
    )
    if "cache_creation_input_tokens" in data:
        out["cache_creation_input_tokens"] = data["cache_creation_input_tokens"]
    if "cache_read_input_tokens" in data:
        out["cache_read_input_tokens"] = data["cache_read_input_tokens"]
    return out


# ---------------------------------------------------------------------------
# Provider-specific extractors
# ---------------------------------------------------------------------------


def _extract_anthropic(message: Any) -> tuple[str, list[NormalizedToolCall]]:
    """Anthropic provider via LiteLLM keeps ``content`` as a list of
    blocks. text blocks and tool_use blocks both live in there."""
    content = getattr(message, "content", None) or (
        message.get("content") if isinstance(message, dict) else None
    )
    text_parts: list[str] = []
    calls: list[NormalizedToolCall] = []

    if isinstance(content, list):
        for block in content:
            btype = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
            if btype == "text":
                t = block.get("text") if isinstance(block, dict) else getattr(block, "text", "")
                text_parts.append(str(t))
            elif btype == "tool_use":
                bid = (
                    block.get("id")
                    if isinstance(block, dict)
                    else getattr(block, "id", "")
                )
                bname = (
                    block.get("name")
                    if isinstance(block, dict)
                    else getattr(block, "name", "")
                )
                binput = (
                    block.get("input")
                    if isinstance(block, dict)
                    else getattr(block, "input", {})
                )
                calls.append(
                    NormalizedToolCall(
                        id=str(bid or ""),
                        name=str(bname or ""),
                        input=_coerce_input(binput),
                    )
                )
    elif isinstance(content, str):
        text_parts.append(content)

    return "".join(text_parts), calls


def _extract_openai_style(message: Any) -> tuple[str, list[NormalizedToolCall]]:
    """OpenAI/Ollama-style response: ``message.content`` is a string and
    ``message.tool_calls`` is a separate array of function calls."""
    if isinstance(message, dict):
        content = message.get("content", "") or ""
        tc_list = message.get("tool_calls") or []
    else:
        content = getattr(message, "content", "") or ""
        tc_list = getattr(message, "tool_calls", None) or []

    calls: list[NormalizedToolCall] = []
    for tc in tc_list:
        if isinstance(tc, dict):
            tid = tc.get("id", "")
            fn = tc.get("function", {})
            name = fn.get("name", "")
            arguments = fn.get("arguments", "{}")
        else:
            tid = getattr(tc, "id", "")
            fn = getattr(tc, "function", None)
            name = getattr(fn, "name", "") if fn is not None else ""
            arguments = getattr(fn, "arguments", "{}") if fn is not None else "{}"
        calls.append(
            NormalizedToolCall(
                id=str(tid or ""),
                name=str(name or ""),
                input=_coerce_input(arguments),
            )
        )
    return str(content), calls


def _provider_of(model: str, response: Any) -> str:
    """Best-effort provider detection.

    Order of fallbacks:

    1. Caller-supplied ``response._wake_provider_hint`` (test harness).
    2. ``model`` prefix (``anthropic/…`` / ``openai/…`` / ``ollama/…``).
    3. Shape inspection of the response.
    """
    hint: str | None = getattr(response, "_wake_provider_hint", None) if response is not None else None
    if hint:
        return hint
    lowered = model.lower()
    if lowered.startswith(("anthropic/", "claude-")):
        return "anthropic"
    if lowered.startswith(("openai/", "gpt-")):
        return "openai"
    if lowered.startswith("ollama/"):
        return "ollama"
    # Fallback: peek at the first choice's content shape.
    try:
        choice = response.choices[0]
        msg = getattr(choice, "message", None) or (
            choice.get("message") if isinstance(choice, dict) else None
        )
        content = getattr(msg, "content", None) if msg is not None else None
        if isinstance(content, list):
            return "anthropic"
    except (AttributeError, IndexError, KeyError, TypeError):
        pass
    return "openai"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize_response(response: Any, *, model: str) -> NormalizedMessage:
    """Translate a LiteLLM completion response into a ``NormalizedMessage``.

    ``response`` can be a real LiteLLM ``ModelResponse``, a dict that
    mimics one (test fixtures), or a custom object exposing ``.choices``.
    """
    # Choice extraction.
    if isinstance(response, dict):
        choices = response.get("choices", [])
    else:
        choices = getattr(response, "choices", []) or []

    if not choices:
        return NormalizedMessage(text="", tool_calls=[], stop_reason="error")

    first = choices[0]
    if isinstance(first, dict):
        message = first.get("message", {})
        finish_reason = first.get("finish_reason")
    else:
        message = getattr(first, "message", None)
        finish_reason = getattr(first, "finish_reason", None)

    provider = _provider_of(model, response)
    if provider == "anthropic":
        text, calls = _extract_anthropic(message)
    else:
        text, calls = _extract_openai_style(message)

    # If the model wanted to call tools, ensure stop_reason reflects that
    # even if the provider only reported "stop".
    stop_reason = _map_finish_reason(finish_reason if isinstance(finish_reason, str) else None)
    if calls and stop_reason == "end_turn":
        stop_reason = "tool_use"

    usage = (
        response.get("usage")
        if isinstance(response, dict)
        else getattr(response, "usage", None)
    )

    cost: float | None = None
    raw_cost = (
        response.get("response_cost")
        if isinstance(response, dict)
        else getattr(response, "response_cost", None)
    )
    if isinstance(raw_cost, (int, float)):
        cost = float(raw_cost)

    return NormalizedMessage(
        text=text,
        tool_calls=list(calls),
        stop_reason=stop_reason,
        usage=_normalize_usage(usage),
        raw=response if isinstance(response, dict) else {},
        cost_usd=cost,
    )


# Backwards-compatible alias — some tests / docs use the longer name.
normalize_completion = normalize_response


def to_wake_events(
    message: NormalizedMessage, session_id: str
) -> list[Event]:
    """Convert a ``NormalizedMessage`` into placeholder Wake events.

    Same convention as ``adapters/claude-sdk``: ``id`` and ``seq`` are
    sentinels for the dispatcher to fill in.

    Emits:
    * one ``assistant.message`` carrying text + tool_use blocks
    * one ``tool_use`` event per tool the model wanted to run

    The runtime / harness adapter is responsible for actually executing
    tools and following up with ``tool_result`` events.
    """
    now = datetime.now(UTC)
    content: list[dict[str, Any]] = []
    if message.text:
        content.append({"type": "text", "text": message.text})
    for call in message.tool_calls:
        content.append(
            {
                "type": "tool_use",
                "id": call.id,
                "name": call.name,
                "input": call.input,
            }
        )

    metadata: dict[str, Any] | None = None
    if message.cost_usd is not None:
        metadata = {"cost_usd": message.cost_usd}

    out: list[Event] = [
        Event(
            id="",
            session_id=session_id,
            seq=-1,
            type="assistant.message",
            payload={
                "content": content,
                "stop_reason": message.stop_reason,
                "usage": message.usage,
            },
            metadata=metadata,
            created_at=now,
        )
    ]
    for call in message.tool_calls:
        out.append(
            Event(
                id="",
                session_id=session_id,
                seq=-1,
                type="tool_use",
                payload={
                    "tool_use_id": call.id,
                    "name": call.name,
                    "input": call.input,
                },
                created_at=now,
            )
        )
    return out


__all__ = [
    "normalize_response",
    "normalize_completion",
    "to_wake_events",
]
