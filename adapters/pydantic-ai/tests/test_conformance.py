"""Run the Wake conformance suite against the Pydantic AI adapter.

Pydantic AI is the most strictly-typed framework in the Wake adapter
family, so the conformance score should be the highest of the three
Phase 3 adapters. The acceptance criterion is **≥8/10 scenarios
passing**.

The test uses :class:`pydantic_ai.models.function.FunctionModel` with a
scenario-aware stream function that produces:

* a plain ``"ok"`` text answer for basic prompts,
* a long streamed text for ``streaming`` / ``cancellation`` prompts,
* tool calls when tools are registered (single, parallel, or failing),
* no surprise behaviour that would trip up resume / idempotence.

No real LLM is invoked.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelRequest,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from wake_adapter_pydantic_ai import PydanticAIAdapter
from wake_test_conformance import run_conformance


def _latest_user_text(messages: list[Any]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart):
                    content = part.content
                    return content if isinstance(content, str) else str(content)
    return ""


def _has_tool_returns(messages: list[Any]) -> bool:
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, ToolReturnPart):
                    return True
    return False


async def _scenario_stream(messages: list[Any], info: AgentInfo):  # type: ignore[no-untyped-def]
    """Stream function that adapts its output to the prompt + tools.

    Decision tree:

    1. If the message history already contains ``ToolReturnPart``s, the
       run is in its post-tool round → emit a final text answer.
    2. Else, inspect the user prompt:
       * ``"use both tool_a and tool_b"`` → parallel tool calls
       * ``"use failing_tool"`` → call ``failing_tool``
       * ``"use echo"`` (any phrasing) → call ``echo`` once
       * ``"stream a long response"`` → emit multiple text chunks
       * anything else → emit ``"ok"``
    """
    user_text = _latest_user_text(messages).lower()
    function_tools = {t.name for t in info.function_tools}

    # Post-tool round → just answer.
    if _has_tool_returns(messages):
        yield "done — ok"
        return

    # Parallel tools
    if "tool_a" in function_tools and "tool_b" in function_tools and "both" in user_text:
        yield {
            0: DeltaToolCall(
                name="tool_a", json_args='{"x": 1}', tool_call_id="call_a"
            ),
            1: DeltaToolCall(
                name="tool_b", json_args='{"y": 2}', tool_call_id="call_b"
            ),
        }
        return

    # Failing tool
    if "failing_tool" in function_tools and "failing" in user_text:
        yield {
            0: DeltaToolCall(
                name="failing_tool",
                json_args="{}",
                tool_call_id="call_fail",
            ),
        }
        return

    # Single echo tool
    if "echo" in function_tools and "echo" in user_text:
        yield {
            0: DeltaToolCall(
                name="echo",
                json_args=json.dumps({"text": "hello"}),
                tool_call_id="call_echo",
            ),
        }
        return

    # Streaming
    if "stream" in user_text or "long response" in user_text:
        for chunk in ["Streaming ", "a ", "longer ", "response ", "ok."]:
            yield chunk
        return

    # Default: short ok.
    yield "ok"


def _build_adapter() -> PydanticAIAdapter:
    agent: Agent[None, str] = Agent(
        FunctionModel(stream_function=_scenario_stream),
        # Plain text output — let the adapter's basic text path run.
    )
    return PydanticAIAdapter(agent)


# ---------------------------------------------------------------------------
# Conformance entry point
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conformance_at_least_eight_of_ten() -> None:
    """Pydantic AI is the most strictly-typed of the three Phase 3
    adapters; per the contract it should score the highest. We require
    at least 8/10 scenarios passing."""
    adapter = _build_adapter()
    report = await run_conformance(adapter)
    print()
    print(report.summary())
    assert report.passed_count >= 8, (
        f"Pydantic AI adapter scored {report.passed_count}/{report.total}:\n"
        f"{report.summary()}"
    )


@pytest.mark.asyncio
async def test_conformance_basic_scenarios_pass() -> None:
    """Sanity check: the fundamental scenarios MUST pass."""
    adapter = _build_adapter()
    report = await run_conformance(
        adapter,
        scenarios=["basic_step", "tool_use", "lifecycle"],
    )
    failures = [r.name for r in report.results if not r.passed]
    assert not failures, (
        f"core scenarios failed: {failures}\n{report.summary()}"
    )
