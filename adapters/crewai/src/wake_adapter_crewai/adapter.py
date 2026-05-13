# ruff: noqa: TC001, TC003, A002
"""CrewAIAdapter — Wake :class:`HarnessAdapter` for CrewAI ``Crew``s.

CrewAI is opinionated: it owns the agent loop, parses ReAct-style model
output, and drives tools synchronously through ``BaseTool._run``. This
adapter wraps that orchestration in the Wake ABI:

1. ``step()`` reads the latest ``user.message`` and asks the user-supplied
   ``crew_factory`` to build a :class:`Crew` for this turn.
2. Every Wake tool is replaced by a :class:`BaseTool` wrapper that funnels
   ``_run`` calls through ``tools.execute()`` and reports each call back to
   the adapter so we can emit canonical ``tool_use``/``tool_result`` events.
3. The adapter attaches a ``step_callback`` and ``task_callback`` that
   translate CrewAI's internal :class:`AgentAction`/:class:`AgentFinish`/
   :class:`TaskOutput` objects into Wake ``assistant.thinking`` events.
4. ``crew.kickoff()`` runs in a worker thread (via ``asyncio.to_thread``)
   while the adapter drains a queue of events emitted by callbacks. When
   the worker finishes, the adapter emits a single ``assistant.message``
   carrying the crew's final raw output.

The adapter is stateless across step() calls: nothing persists on ``self``
between turns. A single instance can serve many concurrent sessions
because all state lives in local variables inside ``step()``.

Design notes
============

- We use ``crew.kickoff()`` (sync, in worker thread) rather than the new
  ``kickoff_async()`` method. CrewAI's async path internally re-enters the
  sync loop in many cases and adds little for our use case, while
  asyncio.to_thread keeps the call path obvious and lets tool callbacks
  re-enter our event loop safely (the tool bridge spins a private loop
  if needed).

- The queue is :class:`asyncio.Queue` wrapped with a thread-safe pusher:
  callbacks fire on the worker thread, so we route puts through
  ``loop.call_soon_threadsafe``.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ulid import ULID

from wake.types import Event
from wake_adapter_crewai.callbacks import make_step_callback, make_task_callback
from wake_adapter_crewai.tool_bridge import build_crewai_tools

if TYPE_CHECKING:
    from crewai import Crew

    from wake.adapters.base import LifecycleEvent
    from wake.adapters.context import SessionContext
    from wake.adapters.events import EventStream
    from wake.adapters.tool_registry import ToolRegistry
    from wake.types import ToolResult


CrewFactory = Callable[[str], "Crew"]
"""User-supplied builder: ``crew_factory(user_input) -> Crew``."""


def _now() -> datetime:
    return datetime.now(UTC)


def _make_event(
    session_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> Event:
    """Construct a real :class:`Event` with a fresh ULID id; ``seq=-1``.

    The runtime reassigns ``seq`` on persistence.
    """
    return Event(
        id=str(ULID()),
        session_id=session_id,
        seq=-1,
        type=event_type,
        payload=payload,
        created_at=_now(),
    )


def _extract_text(content: Any) -> str:
    """Pull plain text out of a Wake content list (or accept a raw string).

    ``user.message.payload['content']`` is canonically a list of
    content blocks (``[{"type": "text", "text": "..."}]``). Some
    callers pass a bare string — we accept that too for ergonomics.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            if isinstance(text, str):
                parts.append(text)
        elif hasattr(block, "text"):
            text = getattr(block, "text", "")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


class CrewAIAdapter:
    """Wake HarnessAdapter that runs CrewAI :class:`Crew`s.

    Parameters
    ----------
    crew_factory:
        Callable that takes the user's latest input as a string and
        returns a fresh :class:`Crew`. Building a Crew per-turn is the
        idiomatic CrewAI pattern: the user prompt drives Task
        descriptions, and Crew construction is cheap relative to LLM
        calls.

    Example::

        def build(user_input: str) -> Crew:
            agent = Agent(role="echoer", goal=user_input, backstory="...",
                          llm=my_llm)
            task = Task(description=user_input, expected_output="...",
                        agent=agent)
            return Crew(agents=[agent], tasks=[task])

        adapter = CrewAIAdapter(build)
    """

    name: str = "crewai"
    version: str = "0.1.0"
    compatibility: str = "wake-harness-adapter@^0.1"

    def __init__(self, crew_factory: CrewFactory) -> None:
        self._crew_factory = crew_factory

    async def step(
        self,
        ctx: SessionContext,
        events: EventStream,
        tools: ToolRegistry,
    ) -> AsyncIterator[Event]:
        """Run one CrewAI turn driven by the latest ``user.message``.

        Returns silently if there is no user message to respond to or if
        the latest user message has already been answered (idempotence).
        See :class:`HarnessAdapter` for the runtime/adapter contract.
        """
        latest_user = await events.latest(type="user.message")
        if latest_user is None:
            return

        # Idempotence: if an assistant.message already follows the latest
        # user.message, we've already answered. Skip silently.
        if await self._already_answered(events, latest_user.seq):
            return

        user_input = _extract_text(latest_user.payload.get("content")) or ""

        # asyncio.Queue is task-safe but not thread-safe. Use call_soon_threadsafe
        # to bridge from the worker thread back to our loop.
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Event] = asyncio.Queue()

        def push(ev: Event) -> None:
            # Called from any thread. Stamp the session_id defensively
            # in case a callback minted an Event without one.
            if ev.session_id != ctx.session_id:
                ev = ev.model_copy(update={"session_id": ctx.session_id})
            loop.call_soon_threadsafe(queue.put_nowait, ev)

        # Bridge tools -> CrewAI BaseTool, capturing the tool_use_id at
        # the moment of invocation so we can emit the matching pair of
        # ``tool_use``/``tool_result`` events.
        def on_tool_invocation(
            tool_use_id: str,
            tool_name: str,
            input_data: dict[str, Any],
            result: ToolResult,
        ) -> None:
            push(
                _make_event(
                    ctx.session_id,
                    "tool_use",
                    {
                        "tool_use_id": tool_use_id,
                        "name": tool_name,
                        "input": input_data,
                    },
                )
            )
            payload: dict[str, Any] = {
                "tool_use_id": tool_use_id,
                "content": [b.model_dump() for b in result.content],
                "is_error": result.is_error,
            }
            if result.error_code is not None:
                payload["error_code"] = result.error_code
            push(_make_event(ctx.session_id, "tool_result", payload))

        crewai_tools = build_crewai_tools(
            tools, on_invocation=on_tool_invocation
        )

        # Build the crew. The factory owns agent/task wiring; we only
        # patch in the Wake tools and callbacks.
        crew = self._crew_factory(user_input)
        self._inject_tools(crew, crewai_tools)
        self._inject_callbacks(crew, ctx.session_id, push)

        # Run kickoff() in a worker thread so we never block the loop.
        # We capture exceptions in a box rather than letting them escape
        # to_thread directly so we can emit a Wake ``error`` event.
        result_box: dict[str, Any] = {}

        def _run_crew() -> None:
            try:
                result_box["result"] = crew.kickoff()
            except BaseException as exc:  # noqa: BLE001
                result_box["error"] = exc

        worker = asyncio.create_task(asyncio.to_thread(_run_crew))

        # Drain the queue while the worker is alive. Each iteration
        # yields any queued event then briefly waits on the worker. If
        # the worker completes, we drain remaining queued events and
        # emit the final assistant.message before returning.
        try:
            while True:
                if worker.done():
                    break
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=0.05)
                    yield ev
                except TimeoutError:
                    continue
                except asyncio.CancelledError:
                    # Propagate cancellation: cancel the worker too.
                    worker.cancel()
                    raise
        except asyncio.CancelledError:
            # On cancellation we still wait for the worker to settle so
            # CrewAI gets a chance to release its resources. We
            # deliberately do NOT yield anything afterwards.
            with contextlib.suppress(Exception):
                await asyncio.wait_for(worker, timeout=2.0)
            raise

        # Drain any events the worker emitted just before finishing.
        while not queue.empty():
            try:
                yield queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Bubble up any worker exception as a Wake ``error`` event
        # rather than crashing the adapter (matches error_handling
        # conformance scenario expectations).
        if "error" in result_box:
            exc = result_box["error"]
            yield _make_event(
                ctx.session_id,
                "error",
                {
                    "error_type": "crew_kickoff_failed",
                    "message": f"{type(exc).__name__}: {exc}",
                },
            )
            return

        # Emit the final assistant.message.
        result = result_box.get("result")
        final_text = self._extract_final_text(result)
        yield _make_event(
            ctx.session_id,
            "assistant.message",
            {
                "content": [{"type": "text", "text": final_text}],
                "stop_reason": "end_turn",
            },
        )

    async def on_lifecycle(
        self,
        ctx: SessionContext,
        event: LifecycleEvent,
    ) -> None:
        """No-op lifecycle hook.

        The adapter is stateless across step() calls — the Crew is
        rebuilt per turn by the factory. Subclasses may override to
        eagerly warm caches on ``created`` if needed.
        """
        return None

    # ------------------------------------------------------------------ internals

    @staticmethod
    async def _already_answered(events: EventStream, user_seq: int) -> bool:
        """True iff an ``assistant.message`` exists after ``user_seq``.

        Used for idempotence: re-running ``step()`` against an already
        answered log should be a no-op so the conformance ``resume``
        scenario passes.
        """
        latest_msg = await events.latest(type="assistant.message")
        if latest_msg is None:
            return False
        return bool(latest_msg.seq > user_seq)

    @staticmethod
    def _inject_tools(crew: Crew, tools: list[Any]) -> None:
        """Replace every agent's tool list with Wake-wrapped tools.

        We override per-agent tools rather than crew-level tools so
        single-agent and multi-agent crews behave the same.
        """
        for agent in crew.agents:
            try:
                agent.tools = list(tools)
            except Exception:  # noqa: BLE001 — pydantic frozen models
                # Some BaseAgent subclasses freeze ``tools``. Fall back
                # to direct attribute set bypassing pydantic.
                object.__setattr__(agent, "tools", list(tools))

    @staticmethod
    def _inject_callbacks(
        crew: Crew,
        session_id: str,
        emit: Callable[[Event], None],
    ) -> None:
        """Wire step_callback and task_callback to push Wake events.

        Existing callbacks (if any) are chained: we call the user's
        callback first, then ours, so user code observes the same
        events it always has.
        """
        existing_step = getattr(crew, "step_callback", None)
        existing_task = getattr(crew, "task_callback", None)

        our_step = make_step_callback(session_id, emit)
        our_task = make_task_callback(session_id, emit)

        if existing_step is not None and callable(existing_step):
            def chained_step(out: Any) -> None:
                try:
                    existing_step(out)
                finally:
                    our_step(out)
        else:
            chained_step = our_step  # type: ignore[assignment]

        if existing_task is not None and callable(existing_task):
            def chained_task(out: Any) -> None:
                try:
                    existing_task(out)
                finally:
                    our_task(out)
        else:
            chained_task = our_task  # type: ignore[assignment]

        # Pydantic v2 may guard these fields; fall back to object.__setattr__.
        for field_name, value in (
            ("step_callback", chained_step),
            ("task_callback", chained_task),
        ):
            try:
                setattr(crew, field_name, value)
            except Exception:  # noqa: BLE001
                object.__setattr__(crew, field_name, value)

    @staticmethod
    def _extract_final_text(crew_result: Any) -> str:
        """Pull the final string out of a CrewAI result object.

        :class:`CrewOutput` exposes ``raw``; fall back to ``str()``.
        """
        if crew_result is None:
            return ""
        raw = getattr(crew_result, "raw", None)
        if isinstance(raw, str) and raw:
            return raw
        return str(crew_result)


# ---------------------------------------------------------------------------
# Entry point factory
# ---------------------------------------------------------------------------


def _trivial_echo_crew(user_input: str) -> Crew:
    """Build a minimal echo Crew for the entry-point factory.

    Real callers supply their own ``crew_factory`` to
    :class:`CrewAIAdapter` directly. This factory exists so the
    ``wake.adapters`` entry point is callable without arguments — it
    yields a Crew that returns the user input unchanged, useful only as
    a smoke test of the dispatch path.
    """
    # Imported lazily so installing the package without CrewAI never
    # explodes at import time.
    from crewai import Agent, Crew, Task
    from crewai.llms.base_llm import BaseLLM

    class _EchoLLM(BaseLLM):
        """Inline fake LLM: returns ``Final Answer: <user_input>`` once."""

        def call(
            self,
            messages: Any,
            tools: Any = None,
            callbacks: Any = None,
            available_functions: Any = None,
            from_task: Any = None,
            from_agent: Any = None,
            response_model: Any = None,
        ) -> str:
            return f"Final Answer: {user_input}"

        def supports_function_calling(self) -> bool:
            return False

        def supports_stop_words(self) -> bool:
            return False

    llm = _EchoLLM(model="wake-echo")
    agent = Agent(
        role="echoer",
        goal="repeat back the user's request",
        backstory="A trivial echo agent.",
        llm=llm,
        verbose=False,
    )
    task = Task(
        description=user_input or "say hi",
        expected_output="The user's input, verbatim.",
        agent=agent,
    )
    return Crew(agents=[agent], tasks=[task], verbose=False)


def create() -> CrewAIAdapter:
    """Factory used by the ``wake.adapters`` entry point.

    Returns an adapter wired to a trivial echo crew. Real callers
    construct ``CrewAIAdapter(crew_factory)`` directly with their own
    factory.
    """
    return CrewAIAdapter(_trivial_echo_crew)
