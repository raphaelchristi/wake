"""Self-test: an inline echo adapter that satisfies all 10 scenarios.

The echo adapter is a deterministic, dependency-free HarnessAdapter
designed to exercise every code path the conformance suite checks.

If `test_self.py` fails, the runner itself is broken — fix the scenarios
or runner before blaming an adapter under test.
"""

from __future__ import annotations

import asyncio
import re
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
from wake_test_conformance import (
    ConformanceReport,
    ScenarioResult,
    run_conformance,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_event(
    *,
    session_id: str,
    type: EventType,
    payload: dict[str, Any],
    parent_id: str | None = None,
) -> Event:
    return Event(
        id=str(ULID()),
        session_id=session_id,
        seq=0,  # runtime would assign; harness re-numbers on persist
        type=type,
        payload=payload,
        parent_id=parent_id,
        metadata=None,
        created_at=_now(),
    )


class EchoAdapter:
    """Reference adapter that intentionally satisfies every conformance scenario.

    Behavior summary:

    - Reads the latest `user.message`.
    - If it asks for a tool (text contains "use <tool>"), emits matching
      `tool_use` events, calls `tools.execute()`, emits `tool_result`,
      then emits a final `assistant.message`.
    - Otherwise streams 2 `assistant.delta` chunks then a final
      `assistant.message` echoing the user text (downcased, with "ok"
      appended so basic_step's text check passes regardless of input).
    - Treats the same `user.message` event id seen on a prior step as
      "already handled" — second step is a no-op (resume / idempotence).
    - Honors a "PLEASE_PAUSE" marker by emitting `pause_turn`.
    """

    name = "echo"
    version = "0.0.1"
    compatibility = "wake-harness-adapter@^0.1"

    def __init__(self) -> None:
        # Track the user message ids this adapter has already responded to,
        # keyed by session_id. Production adapters reconstruct this from
        # the event log; we keep it as a session-scoped memo for simplicity.
        self._handled: dict[str, set[str]] = {}

    async def step(  # type: ignore[misc]
        self,
        ctx: SessionContext,
        events: EventStream,
        tools: ToolRegistry,
    ) -> AsyncIterator[Event]:
        # Implemented as an async generator (uses `yield`), so callers do
        # `async for ev in adapter.step(...)`. Protocol annotation matches.
        latest_user = await events.latest("user.message")
        if latest_user is None:
            return

        seen = self._handled.setdefault(ctx.session_id, set())
        # Resume / idempotence: if we've already handled this user message,
        # detect it by checking whether the log already contains an
        # assistant.message AFTER the latest user.message.
        all_events = await events.all()
        if _user_already_answered(all_events, latest_user):
            return
        seen.add(latest_user.id)

        text = _user_text(latest_user)

        # pause_turn marker
        if "PLEASE_PAUSE" in text:
            yield _make_event(
                session_id=ctx.session_id,
                type="pause_turn",
                payload={"reason": "user_hint", "can_continue": True},
            )
            yield _make_event(
                session_id=ctx.session_id,
                type="assistant.message",
                payload={
                    "content": [{"type": "text", "text": "paused ok"}],
                    "stop_reason": "pause_turn",
                },
            )
            return

        # Tool routing
        requested = _requested_tools(text, tools)
        if requested:
            for tool_name in requested:
                tool_use_id = f"toolu_{uuid4().hex[:16]}"
                yield _make_event(
                    session_id=ctx.session_id,
                    type="tool_use",
                    payload={
                        "tool_use_id": tool_use_id,
                        "name": tool_name,
                        "input": {"text": text, "input": text},
                    },
                )
                result = await tools.execute(
                    tool_name, {"text": text}, tool_use_id=tool_use_id
                )
                yield _make_event(
                    session_id=ctx.session_id,
                    type="tool_result",
                    payload={
                        "tool_use_id": tool_use_id,
                        "content": [b.model_dump() for b in result.content],
                        "is_error": result.is_error,
                    },
                )
            yield _make_event(
                session_id=ctx.session_id,
                type="assistant.message",
                payload={
                    "content": [
                        {"type": "text", "text": f"tools done ok ({len(requested)})"}
                    ],
                    "stop_reason": "end_turn",
                },
            )
            return

        # Default: stream two deltas, then a final message containing 'ok'.
        for chunk in ("ok ", "done"):
            yield _make_event(
                session_id=ctx.session_id,
                type="assistant.delta",
                payload={"index": 0, "delta": {"type": "text_delta", "text": chunk}},
            )
            # Give the event loop a tick — important for cancellation scenario.
            await asyncio.sleep(0.01)
        yield _make_event(
            session_id=ctx.session_id,
            type="assistant.message",
            payload={
                "content": [{"type": "text", "text": "ok done"}],
                "stop_reason": "end_turn",
            },
        )

    async def on_lifecycle(
        self, ctx: SessionContext, event: LifecycleEvent
    ) -> None:
        if event == "terminated":
            self._handled.pop(ctx.session_id, None)
        return None


def _user_text(event: Event) -> str:
    content = event.payload.get("content") if event.payload else None
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return " ".join(parts)


def _user_already_answered(events: list[Event], user_msg: Event) -> bool:
    """True if any assistant.message / pause_turn appears after user_msg in the log."""
    seen_user = False
    for ev in events:
        if ev.id == user_msg.id:
            seen_user = True
            continue
        if seen_user and ev.type in {"assistant.message", "pause_turn"}:
            return True
    return False


_TOOL_PATTERN = re.compile(r"\b(?:use|call|invoke)\s+([a-zA-Z_][\w]*)", re.IGNORECASE)


def _requested_tools(text: str, tools: ToolRegistry) -> list[str]:
    """Map "use X" or "use both X and Y" patterns to known tool names."""
    available = {t.name for t in tools.list()}
    if not available:
        return []
    out: list[str] = []
    seen: set[str] = set()
    # Find "use X" matches
    for m in _TOOL_PATTERN.finditer(text):
        candidate = m.group(1)
        if candidate in available and candidate not in seen:
            out.append(candidate)
            seen.add(candidate)
    # Also pick up bare tool names anywhere in the text (covers
    # "use both tool_a and tool_b" without re-matching).
    for tool_name in available:
        if tool_name in text and tool_name not in seen:
            out.append(tool_name)
            seen.add(tool_name)
    return out


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_echo_adapter_passes_full_suite() -> None:
    """The reference echo adapter must pass every scenario.

    This guards the runner itself: failure here means the runner has a
    bug, not the adapter.
    """
    adapter = EchoAdapter()
    report = await run_conformance(adapter)
    assert isinstance(report, ConformanceReport)
    assert report.passed, "\n" + report.summary()
    assert report.total == 10, f"expected 10 scenarios, got {report.total}"
    assert report.failed_count == 0


@pytest.mark.asyncio
async def test_echo_adapter_reports_individual_scenarios() -> None:
    """Each scenario reports a ScenarioResult with timing."""
    adapter = EchoAdapter()
    report = await run_conformance(adapter)
    for r in report.results:
        assert isinstance(r, ScenarioResult)
        assert r.passed, f"scenario {r.name} failed: {r.message}"
        assert r.duration_ms >= 0.0


@pytest.mark.asyncio
async def test_can_run_subset() -> None:
    """The runner supports a subset selection."""
    adapter = EchoAdapter()
    report = await run_conformance(adapter, scenarios=["basic_step", "lifecycle"])
    assert report.total == 2
    assert {r.name for r in report.results} == {"basic_step", "lifecycle"}


@pytest.mark.asyncio
async def test_unknown_scenario_raises() -> None:
    adapter = EchoAdapter()
    with pytest.raises(ValueError):
        await run_conformance(adapter, scenarios=["bogus_scenario"])
