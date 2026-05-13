"""Per-scenario unit tests using minimal mock adapters.

For each scenario, we run it against:

- A "passing" adapter that does the minimum to satisfy the scenario.
- A "failing" adapter that intentionally violates the scenario's
  contract, ensuring the scenario actually catches the failure.

These tests are what prevent regressions in the scenarios themselves.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest
from ulid import ULID

from wake.adapters import (
    EventStream,
    LifecycleEvent,
    SessionContext,
    ToolRegistry,
)
from wake.types import Event, EventType
from wake_test_conformance import run_scenario
from wake_test_conformance.result import ConformanceReport, ScenarioResult
from wake_test_conformance.runner import run_conformance


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ev(session_id: str, type: EventType, payload: dict[str, Any]) -> Event:
    return Event(
        id=str(ULID()),
        session_id=session_id,
        seq=0,
        type=type,
        payload=payload,
        parent_id=None,
        metadata=None,
        created_at=_now(),
    )


# ----------------------------------------------------------------------
# Mock adapters
# ----------------------------------------------------------------------


class _BaseAdapter:
    name = "mock"
    version = "0.0.0"
    compatibility = "wake-harness-adapter@^0.1"

    async def on_lifecycle(
        self, ctx: SessionContext, event: LifecycleEvent
    ) -> None:
        return None


class SilentAdapter(_BaseAdapter):
    """Emits nothing — fails most scenarios."""

    name = "silent"

    async def step(  # type: ignore[misc]
        self,
        ctx: SessionContext,
        events: EventStream,
        tools: ToolRegistry,
    ) -> AsyncIterator[Event]:
        if False:  # pragma: no cover — keep async-generator typing
            yield  # type: ignore[unreachable]


class MinimalOkAdapter(_BaseAdapter):
    """Emits a single assistant.message containing 'ok'. Passes basic_step."""

    name = "minimal-ok"

    async def step(  # type: ignore[misc]
        self,
        ctx: SessionContext,
        events: EventStream,
        tools: ToolRegistry,
    ) -> AsyncIterator[Event]:
        # Resume guard: if log already has an assistant.message, do nothing.
        for ev in await events.all():
            if ev.type == "assistant.message":
                return
        yield _ev(
            ctx.session_id,
            "assistant.message",
            {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"},
        )


class ToolEchoAdapter(_BaseAdapter):
    """Calls every registered tool once, then emits a final message."""

    name = "tool-echo"

    async def step(  # type: ignore[misc]
        self,
        ctx: SessionContext,
        events: EventStream,
        tools: ToolRegistry,
    ) -> AsyncIterator[Event]:
        # Resume guard.
        all_events = await events.all()
        if any(e.type == "assistant.message" for e in all_events):
            return
        for desc in tools.list():
            tool_use_id = f"toolu_{uuid4().hex[:16]}"
            yield _ev(
                ctx.session_id,
                "tool_use",
                {"tool_use_id": tool_use_id, "name": desc.name, "input": {}},
            )
            res = await tools.execute(desc.name, {}, tool_use_id=tool_use_id)
            yield _ev(
                ctx.session_id,
                "tool_result",
                {
                    "tool_use_id": tool_use_id,
                    "content": [b.model_dump() for b in res.content],
                    "is_error": res.is_error,
                },
            )
        yield _ev(
            ctx.session_id,
            "assistant.message",
            {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"},
        )


class CrashingToolAdapter(_BaseAdapter):
    """Raises in step() — used to verify scenarios trap exceptions."""

    name = "crashing"

    async def step(  # type: ignore[misc]
        self,
        ctx: SessionContext,
        events: EventStream,
        tools: ToolRegistry,
    ) -> AsyncIterator[Event]:
        if False:  # pragma: no cover
            yield  # type: ignore[unreachable]
        raise RuntimeError("intentional crash")


class DirectToolCallAdapter(_BaseAdapter):
    """Emits tool_use but never calls tools.execute() — violates the contract."""

    name = "direct-tool"

    async def step(  # type: ignore[misc]
        self,
        ctx: SessionContext,
        events: EventStream,
        tools: ToolRegistry,
    ) -> AsyncIterator[Event]:
        all_events = await events.all()
        if any(e.type == "assistant.message" for e in all_events):
            return
        yield _ev(
            ctx.session_id,
            "tool_use",
            {"tool_use_id": "toolu_x", "name": "echo", "input": {}},
        )
        # Note: no tools.execute() call.
        yield _ev(
            ctx.session_id,
            "assistant.message",
            {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"},
        )


class DuplicateToolIdAdapter(_BaseAdapter):
    """Emits the SAME tool_use_id on every step() — violates idempotence."""

    name = "duplicate-tool-id"

    async def step(  # type: ignore[misc]
        self,
        ctx: SessionContext,
        events: EventStream,
        tools: ToolRegistry,
    ) -> AsyncIterator[Event]:
        yield _ev(
            ctx.session_id,
            "tool_use",
            {"tool_use_id": "toolu_FIXED", "name": "echo", "input": {}},
        )
        try:
            res = await tools.execute("echo", {}, tool_use_id="toolu_FIXED")
            yield _ev(
                ctx.session_id,
                "tool_result",
                {
                    "tool_use_id": "toolu_FIXED",
                    "content": [b.model_dump() for b in res.content],
                    "is_error": res.is_error,
                },
            )
        except KeyError:
            pass
        yield _ev(
            ctx.session_id,
            "assistant.message",
            {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"},
        )


class HangingAdapter(_BaseAdapter):
    """Yields one event, then awaits forever — used for cancellation tests."""

    name = "hanging"

    async def step(  # type: ignore[misc]
        self,
        ctx: SessionContext,
        events: EventStream,
        tools: ToolRegistry,
    ) -> AsyncIterator[Event]:
        yield _ev(
            ctx.session_id,
            "assistant.delta",
            {"index": 0, "delta": {"type": "text_delta", "text": "hi"}},
        )
        await asyncio.sleep(10.0)
        yield _ev(  # pragma: no cover
            ctx.session_id,
            "assistant.message",
            {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"},
        )


class BrokenLifecycleAdapter(_BaseAdapter):
    """on_lifecycle raises — used to check the lifecycle scenario fails it."""

    name = "broken-lifecycle"

    async def step(  # type: ignore[misc]
        self,
        ctx: SessionContext,
        events: EventStream,
        tools: ToolRegistry,
    ) -> AsyncIterator[Event]:
        if False:  # pragma: no cover
            yield  # type: ignore[unreachable]

    async def on_lifecycle(
        self, ctx: SessionContext, event: LifecycleEvent
    ) -> None:
        raise RuntimeError(f"refusing lifecycle event {event}")


# ----------------------------------------------------------------------
# Per-scenario tests
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_basic_step_fails_for_silent_adapter() -> None:
    result = await run_scenario(SilentAdapter(), "basic_step")
    assert not result.passed
    assert "no events" in result.message.lower()


@pytest.mark.asyncio
async def test_basic_step_passes_for_minimal_ok() -> None:
    result = await run_scenario(MinimalOkAdapter(), "basic_step")
    assert result.passed, result.message


@pytest.mark.asyncio
async def test_tool_use_fails_for_silent_adapter() -> None:
    result = await run_scenario(SilentAdapter(), "tool_use")
    assert not result.passed
    assert "tool_use" in result.message


@pytest.mark.asyncio
async def test_tool_use_passes_for_tool_echo() -> None:
    result = await run_scenario(ToolEchoAdapter(), "tool_use")
    assert result.passed, result.message


@pytest.mark.asyncio
async def test_tool_use_fails_for_direct_tool_call() -> None:
    """Adapter must route through tools.execute()."""
    result = await run_scenario(DirectToolCallAdapter(), "tool_use")
    assert not result.passed
    assert "tools.execute" in result.message


@pytest.mark.asyncio
async def test_streaming_warns_for_non_streaming_adapter() -> None:
    result = await run_scenario(MinimalOkAdapter(), "streaming")
    assert result.passed, result.message
    assert any("delta" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_streaming_fails_when_no_message() -> None:
    result = await run_scenario(SilentAdapter(), "streaming")
    assert not result.passed


@pytest.mark.asyncio
async def test_cancellation_short_step_does_not_panic() -> None:
    result = await run_scenario(MinimalOkAdapter(), "cancellation")
    # Adapter likely completes before cancellation fires; passes with a warning.
    assert result.passed, result.message


@pytest.mark.asyncio
async def test_cancellation_hanging_adapter_passes() -> None:
    result = await run_scenario(HangingAdapter(), "cancellation")
    assert result.passed, result.message


@pytest.mark.asyncio
async def test_resume_terminates_for_minimal_ok() -> None:
    result = await run_scenario(MinimalOkAdapter(), "resume")
    assert result.passed, result.message


@pytest.mark.asyncio
async def test_parallel_tools_fails_when_no_tools_called() -> None:
    result = await run_scenario(SilentAdapter(), "parallel_tools")
    assert not result.passed


@pytest.mark.asyncio
async def test_parallel_tools_passes_for_tool_echo() -> None:
    result = await run_scenario(ToolEchoAdapter(), "parallel_tools")
    assert result.passed, result.message


@pytest.mark.asyncio
async def test_error_handling_passes_when_tool_skipped() -> None:
    """If adapter never invokes the failing tool, the scenario still passes,
    but emits a warning that the is_error path wasn't exercised."""
    result = await run_scenario(MinimalOkAdapter(), "error_handling")
    assert result.passed
    assert any("failing_tool" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_error_handling_passes_when_tool_invoked() -> None:
    result = await run_scenario(ToolEchoAdapter(), "error_handling")
    assert result.passed, result.message


@pytest.mark.asyncio
async def test_pause_turn_warns_when_not_supported() -> None:
    result = await run_scenario(MinimalOkAdapter(), "pause_turn")
    assert result.passed
    assert result.warnings, "expected a warning when pause_turn is missing"


@pytest.mark.asyncio
async def test_lifecycle_fails_for_broken_adapter() -> None:
    result = await run_scenario(BrokenLifecycleAdapter(), "lifecycle")
    assert not result.passed
    assert "RuntimeError" in result.message


@pytest.mark.asyncio
async def test_lifecycle_passes_for_minimal_ok() -> None:
    result = await run_scenario(MinimalOkAdapter(), "lifecycle")
    assert result.passed, result.message


class ChattyResumeAdapter(_BaseAdapter):
    """Always emits the same assistant.message text — violates resume contract."""

    name = "chatty-resume"

    async def step(  # type: ignore[misc]
        self,
        ctx: SessionContext,
        events: EventStream,
        tools: ToolRegistry,
    ) -> AsyncIterator[Event]:
        yield _ev(
            ctx.session_id,
            "assistant.message",
            {"content": [{"type": "text", "text": "ok same"}], "stop_reason": "end_turn"},
        )


class ChattyResumeWithToolAdapter(_BaseAdapter):
    """Re-emits the SAME tool_use_id on every step — fails resume."""

    name = "chatty-tool-resume"

    async def step(  # type: ignore[misc]
        self,
        ctx: SessionContext,
        events: EventStream,
        tools: ToolRegistry,
    ) -> AsyncIterator[Event]:
        yield _ev(
            ctx.session_id,
            "tool_use",
            {"tool_use_id": "toolu_RESUME", "name": "anything", "input": {}},
        )
        yield _ev(
            ctx.session_id,
            "assistant.message",
            {"content": [{"type": "text", "text": "different text each time"}], "stop_reason": "end_turn"},
        )


@pytest.mark.asyncio
async def test_resume_fails_for_duplicate_text() -> None:
    """An adapter that repeats the same message text fails the resume check."""
    result = await run_scenario(ChattyResumeAdapter(), "resume")
    assert not result.passed
    assert "identical" in result.message.lower()


@pytest.mark.asyncio
async def test_resume_fails_for_duplicate_tool_use_id() -> None:
    """An adapter that reuses tool_use_ids across step() fails the resume check."""
    result = await run_scenario(ChattyResumeWithToolAdapter(), "resume")
    assert not result.passed
    assert "tool_use_id" in result.message


@pytest.mark.asyncio
async def test_resume_fails_when_first_step_empty() -> None:
    """If adapter emits nothing on the first step, resume fails immediately."""
    result = await run_scenario(SilentAdapter(), "resume")
    assert not result.passed
    assert "first step" in result.message.lower()


@pytest.mark.asyncio
async def test_idempotence_fails_for_duplicate_id() -> None:
    result = await run_scenario(DuplicateToolIdAdapter(), "idempotence")
    assert not result.passed
    assert "tool_use_id" in result.message


@pytest.mark.asyncio
async def test_idempotence_passes_for_tool_echo() -> None:
    result = await run_scenario(ToolEchoAdapter(), "idempotence")
    assert result.passed, result.message


# ----------------------------------------------------------------------
# Report-level tests
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crashing_adapter_yields_failures_not_exceptions() -> None:
    """Even a totally broken adapter must produce a structured report."""
    report = await run_conformance(CrashingToolAdapter())
    assert isinstance(report, ConformanceReport)
    assert not report.passed
    # Most scenarios should fail; none should raise to the caller.
    assert report.failed_count > 0


@pytest.mark.asyncio
async def test_report_summary_includes_results() -> None:
    report = await run_conformance(MinimalOkAdapter())
    text = report.summary()
    assert "minimal-ok" in text
    assert "basic_step" in text
    assert "lifecycle" in text


def test_scenario_result_str() -> None:
    r = ScenarioResult(name="x", passed=True, message="hi", duration_ms=1.0)
    s = str(r)
    assert "PASS" in s and "x" in s

    r2 = ScenarioResult(
        name="y", passed=False, message="boom", duration_ms=2.0, warnings=["w"]
    )
    s2 = str(r2)
    assert "FAIL" in s2 and "warnings: 1" in s2
