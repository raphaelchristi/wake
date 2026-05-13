# ruff: noqa: TC001, TC003
"""CrewAI callback hooks that translate to Wake events.

CrewAI calls ``step_callback`` after each agent step (one of
:class:`AgentAction`, :class:`AgentFinish`, or :class:`ToolResult`) and
``task_callback`` after each task (:class:`TaskOutput`). Both run on the
worker thread that executes the crew — they are synchronous.

This module exposes two factory functions, ``make_step_callback`` and
``make_task_callback``, that build closures around an ``emit`` function
supplied by the adapter. The adapter's ``emit`` pushes :class:`Event`
instances onto an :class:`asyncio.Queue` that ``step()`` drains.

We keep the mapping permissive: any attribute we don't recognize is
ignored rather than raising. CrewAI internals shift between minor
versions; we trade a little fragility for a lot of resilience.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ulid import ULID

from wake.types import Event

EventEmitter = Callable[[Event], None]
"""Callable that pushes an Event onto the adapter's queue (sync)."""


def _make_event(
    session_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> Event:
    """Build a fully-formed Event with a fresh ULID id and ``seq=-1``.

    ``seq`` is reassigned by the runtime on persistence. Unlike the
    Claude SDK adapter which uses ``id=""``, we mint a real ULID here
    because callback events get queued from a worker thread and the
    runtime may persist them in arbitrary order; a stable id makes
    correlations easier in tests and logs.
    """
    return Event(
        id=str(ULID()),
        session_id=session_id,
        seq=-1,
        type=event_type,
        payload=payload,
        created_at=datetime.now(UTC),
    )


def _attr(obj: Any, *names: str) -> Any:
    """Return the first attribute found on ``obj`` (else None)."""
    for name in names:
        if hasattr(obj, name):
            val = getattr(obj, name)
            if val is not None:
                return val
    return None


def make_step_callback(
    session_id: str,
    emit: EventEmitter,
    *,
    agent_role: str | None = None,
) -> Callable[[Any], None]:
    """Build a CrewAI ``step_callback`` that emits Wake events.

    Mapping:

    - :class:`AgentAction` -> ``assistant.thinking`` (with the agent's
      thought text). The actual ``tool_use`` event is emitted by the
      tool wrapper, NOT here — the wrapper has the canonical
      ``tool_use_id``, which the callback does not.
    - :class:`AgentFinish` -> ``assistant.thinking`` (final reasoning
      preamble); the consolidated ``assistant.message`` is emitted
      later from the task callback / final result.
    - :class:`ToolResult` -> nothing. The tool wrapper already emitted
      the canonical ``tool_result`` event with the correlating
      ``tool_use_id``; emitting a second one here would duplicate.
    - anything else -> ignored.

    ``agent_role``, when supplied, is attached to event payloads for
    multi-agent traceability.
    """

    def callback(step_output: Any) -> None:
        cls_name = type(step_output).__name__
        role = agent_role or _attr(step_output, "agent_role", "role") or "agent"

        if cls_name == "AgentAction":
            thought = _attr(step_output, "thought", "text") or ""
            if thought:
                emit(
                    _make_event(
                        session_id,
                        "assistant.thinking",
                        {
                            "agent": role,
                            "text": str(thought),
                            "phase": "action",
                        },
                    )
                )

        elif cls_name == "AgentFinish":
            thought = _attr(step_output, "thought") or ""
            if thought:
                emit(
                    _make_event(
                        session_id,
                        "assistant.thinking",
                        {
                            "agent": role,
                            "text": str(thought),
                            "phase": "finish",
                        },
                    )
                )

        # ToolResult: intentionally a no-op — the tool_bridge already
        # emitted the canonical ``tool_use``+``tool_result`` pair.

    return callback


def make_task_callback(
    session_id: str,
    emit: EventEmitter,
) -> Callable[[Any], None]:
    """Build a CrewAI ``task_callback`` that emits per-task progress.

    Emits an ``assistant.thinking`` carrying the task's raw output with
    ``phase="task"``. The final ``assistant.message`` is emitted by the
    adapter itself once the crew finishes — emitting it here would race
    with the kickoff_async completion in multi-task crews.
    """

    def callback(task_output: Any) -> None:
        raw = _attr(task_output, "raw", "output")
        if raw is None:
            return
        agent = _attr(task_output, "agent") or "agent"
        emit(
            _make_event(
                session_id,
                "assistant.thinking",
                {
                    "agent": str(agent),
                    "text": str(raw),
                    "phase": "task",
                },
            )
        )

    return callback
