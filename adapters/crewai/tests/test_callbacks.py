"""Unit tests for :mod:`wake_adapter_crewai.callbacks`.

The callbacks accept CrewAI's per-step output and per-task output
objects and translate them into Wake :class:`Event` instances pushed
through an emitter. We test each branch with a minimal stand-in for the
CrewAI types (a dataclass-like dummy whose class name matches).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from wake_adapter_crewai.callbacks import make_step_callback, make_task_callback

if TYPE_CHECKING:
    from wake.types import Event


@dataclass
class AgentAction:  # mirrors crewai.agents.parser.AgentAction
    thought: str
    tool: str
    tool_input: str
    text: str
    result: str | None = None


@dataclass
class AgentFinish:  # mirrors crewai.agents.parser.AgentFinish
    thought: str
    output: Any
    text: str


@dataclass
class ToolResult:  # mirrors crewai's ToolResult sent to step_callback
    result: str
    result_as_answer: bool = False


@dataclass
class TaskOutput:
    raw: str
    agent: str = "tester"


def _collect() -> tuple[list[Event], Any]:
    """Build an emitter that appends events into a list. Returns (list, emit)."""
    bucket: list[Event] = []

    def emit(ev: Event) -> None:
        bucket.append(ev)

    return bucket, emit


def test_step_callback_emits_thinking_for_agent_action() -> None:
    bucket, emit = _collect()
    cb = make_step_callback("sess1", emit)
    cb(AgentAction(thought="I will think.", tool="echo", tool_input="{}", text="raw"))
    assert len(bucket) == 1
    ev = bucket[0]
    assert ev.type == "assistant.thinking"
    assert ev.session_id == "sess1"
    assert ev.payload["text"] == "I will think."
    assert ev.payload["phase"] == "action"


def test_step_callback_emits_thinking_for_agent_finish() -> None:
    bucket, emit = _collect()
    cb = make_step_callback("sess1", emit, agent_role="writer")
    cb(AgentFinish(thought="Wrapping up.", output="done", text="raw"))
    assert len(bucket) == 1
    ev = bucket[0]
    assert ev.payload["phase"] == "finish"
    assert ev.payload["agent"] == "writer"
    assert ev.payload["text"] == "Wrapping up."


def test_step_callback_skips_empty_thought() -> None:
    """No event emitted if the agent step lacks a thought."""
    bucket, emit = _collect()
    cb = make_step_callback("sess1", emit)
    cb(AgentAction(thought="", tool="x", tool_input="{}", text=""))
    assert bucket == []


def test_step_callback_ignores_tool_result() -> None:
    """ToolResult step events are no-ops — tool_bridge already emitted both pairs."""
    bucket, emit = _collect()
    cb = make_step_callback("sess1", emit)
    cb(ToolResult(result="echo: hi"))
    assert bucket == []


def test_step_callback_ignores_unknown_types() -> None:
    bucket, emit = _collect()
    cb = make_step_callback("sess1", emit)
    cb({"some": "dict"})
    cb("a string")
    cb(None)
    assert bucket == []


def test_task_callback_emits_thinking_with_phase_task() -> None:
    bucket, emit = _collect()
    cb = make_task_callback("sess1", emit)
    cb(TaskOutput(raw="task output text", agent="researcher"))
    assert len(bucket) == 1
    ev = bucket[0]
    assert ev.type == "assistant.thinking"
    assert ev.payload["phase"] == "task"
    assert ev.payload["agent"] == "researcher"
    assert ev.payload["text"] == "task output text"


def test_task_callback_handles_missing_raw() -> None:
    """If a task output exposes neither ``raw`` nor ``output``, skip silently."""
    bucket, emit = _collect()
    cb = make_task_callback("sess1", emit)

    @dataclass
    class Headless:
        pass

    cb(Headless())
    assert bucket == []


def test_session_id_propagated_to_events() -> None:
    bucket, emit = _collect()
    cb = make_step_callback("sess-abc", emit)
    cb(AgentAction(thought="t", tool="x", tool_input="{}", text="r"))
    assert all(ev.session_id == "sess-abc" for ev in bucket)
