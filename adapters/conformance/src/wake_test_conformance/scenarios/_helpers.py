"""Shared helpers for conformance scenarios."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from wake.types import Event, TextBlock, ToolResult

from wake_test_conformance.result import ScenarioResult


def text_from(event: Event) -> str:
    """Extract concatenated text from an assistant.message-like event.

    Returns "" if the payload has no recognizable text content.
    """
    content = event.payload.get("content") if event.payload else None
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            txt = block.get("text", "")
            if isinstance(txt, str):
                parts.append(txt)
        elif isinstance(block, TextBlock):
            parts.append(block.text)
    return "".join(parts)


async def timed(coro: Awaitable[Any]) -> tuple[Any, float]:
    """Await ``coro`` and return (result, duration_ms)."""
    start = time.perf_counter()
    result = await coro
    duration_ms = (time.perf_counter() - start) * 1000.0
    return result, duration_ms


async def run_with_timing(
    name: str,
    body: Callable[[], Awaitable[ScenarioResult]],
) -> ScenarioResult:
    """Execute a scenario body, attaching duration and trapping exceptions.

    Scenario bodies should NOT compute their own duration_ms — this
    wrapper does it. They may, however, set ``warnings``.
    """
    start = time.perf_counter()
    try:
        result = await body()
    except Exception as e:  # noqa: BLE001 — surface as a failure
        duration_ms = (time.perf_counter() - start) * 1000.0
        return ScenarioResult(
            name=name,
            passed=False,
            message=f"scenario raised {type(e).__name__}: {e}",
            duration_ms=duration_ms,
        )
    duration_ms = (time.perf_counter() - start) * 1000.0
    return result.model_copy(update={"duration_ms": duration_ms})


def echo_tool_result(input_data: dict[str, Any]) -> ToolResult:
    """Default fake tool body: echo the input as text."""
    return ToolResult(
        content=[TextBlock(text=str(input_data))],
        is_error=False,
    )
