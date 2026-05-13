"""Shared response fixtures.

Each helper builds a LiteLLM-shaped completion response for a specific
provider. We use plain dict / SimpleNamespace so tests don't depend on
the real LiteLLM ``ModelResponse`` class (which moves between releases).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


def anthropic_response(
    text: str = "",
    tool_calls: list[dict[str, Any]] | None = None,
    *,
    cost_usd: float | None = None,
    finish_reason: str | None = None,
) -> SimpleNamespace:
    """Build an Anthropic-via-LiteLLM response.

    Anthropic preserves its native ``content`` blocks list under
    ``message.content``.
    """
    blocks: list[dict[str, Any]] = []
    if text:
        blocks.append({"type": "text", "text": text})
    for tc in tool_calls or []:
        blocks.append({"type": "tool_use", **tc})

    resp = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=blocks),
                finish_reason=finish_reason or ("tool_use" if tool_calls else "end_turn"),
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=120,
            completion_tokens=64,
            model_dump=lambda: {
                "prompt_tokens": 120,
                "completion_tokens": 64,
                "cache_read_input_tokens": 80,
            },
        ),
    )
    resp.response_cost = cost_usd
    resp._wake_provider_hint = "anthropic"
    return resp


def openai_response(
    text: str = "",
    tool_calls: list[dict[str, Any]] | None = None,
    *,
    cost_usd: float | None = None,
    finish_reason: str | None = None,
) -> SimpleNamespace:
    """Build an OpenAI-shaped response.

    OpenAI keeps text in ``message.content`` (string) and tool calls
    in a parallel array with string-serialised arguments.
    """
    tc_list: list[dict[str, Any]] = []
    for i, tc in enumerate(tool_calls or []):
        import json as _json

        tc_list.append(
            {
                "id": tc.get("id", f"call_{i}"),
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": _json.dumps(tc.get("input", {})),
                },
            }
        )

    resp = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=text or None, tool_calls=tc_list or None),
                finish_reason=finish_reason or ("tool_calls" if tool_calls else "stop"),
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=200,
            completion_tokens=50,
            model_dump=lambda: {"prompt_tokens": 200, "completion_tokens": 50},
        ),
    )
    resp.response_cost = cost_usd
    resp._wake_provider_hint = "openai"
    return resp


def ollama_response(
    text: str = "",
    tool_calls: list[dict[str, Any]] | None = None,
    *,
    finish_reason: str | None = None,
) -> SimpleNamespace:
    """Build an Ollama-via-LiteLLM response.

    Ollama follows the OpenAI shape but **sometimes** ships arguments as
    a parsed dict instead of a JSON string. We model that variation.
    """
    tc_list: list[dict[str, Any]] = []
    for i, tc in enumerate(tool_calls or []):
        tc_list.append(
            {
                "id": tc.get("id", f"call_{i}"),
                "type": "function",
                "function": {
                    "name": tc["name"],
                    # Ollama-style: parsed dict, not stringified.
                    "arguments": tc.get("input", {}),
                },
            }
        )

    resp = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=text or None, tool_calls=tc_list or None),
                finish_reason=finish_reason or ("tool_calls" if tool_calls else "stop"),
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=80,
            completion_tokens=30,
            model_dump=lambda: {"prompt_tokens": 80, "completion_tokens": 30},
        ),
    )
    # Ollama (local) does not report cost.
    resp.response_cost = None
    resp._wake_provider_hint = "ollama"
    return resp
