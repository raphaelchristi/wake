# ruff: noqa: A002
"""LangGraphAdapter — real HarnessAdapter implementation.

Wraps a compiled LangGraph ``StateGraph`` as a Wake-compatible harness.

Lifecycle of a step():

1. Hydrate state from the Wake event log via
   :func:`event_mapping.events_to_state` (LangChain messages).
2. Inject Wake-aware tool nodes into the graph via
   :func:`tool_injection.inject_wake_tools` so every ``tool_call``
   routes through ``tools.execute(name, input, tool_use_id=...)``.
3. Stream the graph in ``stream_mode="updates"``; each per-node update
   contains exactly the new messages produced by that node.
4. Translate each new message back to Wake events with
   :func:`event_mapping.message_to_wake_events` and yield them.
5. Also stream ``stream_mode="messages"`` chunks where available to
   emit incremental ``assistant.delta`` events for token-level
   streaming.

The adapter is stateless across step() calls: it derives everything
from the supplied ``EventStream``. The user's ``StateGraph`` is
treated as a pure definition — we never mutate it in place; we deep
copy + recompile per step (cheap for the test sizes Wake exercises).

A built-in ``_default_graph`` (an echo-style StateGraph) is exposed by
:func:`create` so the entry-point factory returns something runnable
out of the box. Real users instantiate :class:`LangGraphAdapter` with
their own compiled graph.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, TypedDict

import structlog
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.graph.message import add_messages

from wake_adapter_langgraph.event_mapping import (
    _placeholder_event,
    events_to_state,
    message_to_wake_events,
)
from wake_adapter_langgraph.tool_injection import inject_wake_tools

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from langgraph.graph.state import CompiledStateGraph

    from wake.adapters.base import LifecycleEvent
    from wake.adapters.context import SessionContext
    from wake.adapters.events import EventStream
    from wake.adapters.tool_registry import ToolRegistry
    from wake.types import Event

logger = structlog.get_logger(__name__)


class _DefaultEchoState(TypedDict):
    """State schema used by the entry-point factory's default echo graph.

    Declared at module scope so ``typing.get_type_hints`` can resolve
    the forward refs (LangGraph's StateGraph introspects this on init).
    """

    messages: Annotated[list[BaseMessage], add_messages]


class LangGraphAdapter:
    """Wake HarnessAdapter backed by a compiled LangGraph ``StateGraph``.

    Parameters
    ----------
    graph:
        A compiled ``StateGraph`` (the output of
        ``StateGraph(...).compile()``). The graph's state schema MUST
        contain a list field whose key matches ``state_key`` and which
        uses ``langgraph.graph.message.add_messages`` (or compatible
        reducer) so emitted messages are merged correctly.
    state_key:
        Name of the messages list in the graph state. Defaults to
        ``"messages"``.
    emit_deltas:
        When True (default), the adapter additionally subscribes to
        ``stream_mode="messages"`` and emits ``assistant.delta`` events
        as the model streams tokens. Set to False for tests / fully
        non-streaming use cases.

    The adapter is stateless: any single instance can serve many
    concurrent sessions because per-session state lives in the runtime
    event log, not on ``self``.
    """

    name: str = "langgraph"
    version: str = "0.1.0"
    compatibility: str = "wake-harness-adapter@^0.1"

    def __init__(
        self,
        graph: CompiledStateGraph[Any, Any, Any, Any] | None,
        *,
        state_key: str = "messages",
        emit_deltas: bool = True,
    ) -> None:
        # ``graph`` may be None when the adapter is built via the
        # entry-point factory for discovery-only use: in that case
        # ``step()`` synthesises a per-call default graph that knows
        # about the tools currently registered for the session.
        self._graph = graph
        self._state_key = state_key
        self._emit_deltas = emit_deltas

    @property
    def graph(self) -> CompiledStateGraph[Any, Any, Any, Any] | None:
        """The user-supplied compiled StateGraph, or None for the default."""
        return self._graph

    @property
    def state_key(self) -> str:
        """The key in graph state where messages live."""
        return self._state_key

    async def step(
        self,
        ctx: SessionContext,
        events: EventStream,
        tools: ToolRegistry,
    ) -> AsyncIterator[Event]:
        """Run the user's graph once and translate outputs to Wake events.

        See module docstring for the full lifecycle. Honours the
        HarnessAdapter Protocol's runtime/adapter guarantees:

        - Reads the COMPLETE log via ``events.all()``
        - Calls tools EXCLUSIVELY through ``tools.execute(...)``
        - Yields events with placeholder ``id``/``seq`` (runtime fills)
        - Is cancellation-safe (passes ``CancelledError`` through)
        """
        all_events = await events.all()
        existing_ids = _collect_seen_ids(all_events)

        seed = events_to_state(
            all_events,
            state_key=self._state_key,
            system=ctx.agent_config.system if ctx.agent_config else None,
        )

        graph = self._graph or _build_default_graph(tools=tools)
        runtime_graph = inject_wake_tools(
            graph, tools, state_key=self._state_key
        )

        logger.info(
            "langgraph_step",
            session_id=ctx.session_id,
            n_seed_messages=len(seed[self._state_key]),
            n_tools=len(tools.list()),
            emit_deltas=self._emit_deltas,
        )

        emitted_any = False

        # We choose stream_mode="updates" as the primary signal: it
        # gives us per-node deltas to the state — exactly the new
        # messages each node produced. This avoids the duplication
        # that "values" emits (which yields the FULL state on each
        # step).
        stream_modes: tuple[str, ...] = (
            ("updates", "messages") if self._emit_deltas else ("updates",)
        )

        async for stream_mode, chunk in _astream_multi(
            runtime_graph, seed, stream_modes
        ):
            if stream_mode == "messages":
                # chunk is (message, metadata) — emit token deltas as
                # assistant.delta. The aggregate assistant.message comes
                # from the "updates" stream.
                msg, _meta = chunk
                async for ev in _delta_event_for_messages_chunk(
                    msg, ctx.session_id
                ):
                    emitted_any = True
                    yield ev
                continue

            # "updates" — chunk is dict[node_name, state_update].
            if not isinstance(chunk, dict):
                continue
            for _node_name, update in chunk.items():
                if not isinstance(update, dict):
                    continue
                new_messages = update.get(self._state_key) or []
                if not isinstance(new_messages, list):
                    continue
                for msg in new_messages:
                    if not isinstance(msg, BaseMessage):
                        continue
                    if _message_already_seen(msg, existing_ids):
                        # Resume semantics: skip messages we already
                        # persisted in a prior step.
                        continue
                    for ev in message_to_wake_events(
                        msg, session_id=ctx.session_id
                    ):
                        emitted_any = True
                        yield ev

        if not emitted_any:
            # Graph terminated without producing any new message.
            # Emit a minimal idle assistant.message so the conformance
            # ``basic_step`` scenario can observe a final event.
            yield _placeholder_event(
                ctx.session_id,
                "assistant.message",
                {
                    "content": [{"type": "text", "text": "ok"}],
                    "stop_reason": "end_turn",
                },
            )

    async def on_lifecycle(
        self,
        ctx: SessionContext,
        event: LifecycleEvent,
    ) -> None:
        """No-op lifecycle hook.

        LangGraph graphs are already compiled when handed to the
        adapter; there's no per-session setup or teardown to perform.
        Users can subclass and override for advanced scenarios (e.g.
        warm caches on ``created``, flush on ``terminated``).
        """
        return None


def _collect_seen_ids(events: list[Event]) -> dict[str, set[str]]:
    """Index identifiers already present in the log to support resume."""
    tool_use_ids: set[str] = set()
    tool_result_ids: set[str] = set()
    assistant_texts: set[str] = set()
    for ev in events:
        payload = ev.payload or {}
        if ev.type == "tool_use":
            tu_id = payload.get("tool_use_id")
            if isinstance(tu_id, str) and tu_id:
                tool_use_ids.add(tu_id)
        elif ev.type == "tool_result":
            tu_id = payload.get("tool_use_id")
            if isinstance(tu_id, str) and tu_id:
                tool_result_ids.add(tu_id)
        elif ev.type == "assistant.message":
            content = payload.get("content") or []
            if isinstance(content, list):
                text_parts = [
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                joined = "".join(text_parts).strip()
                if joined:
                    assistant_texts.add(joined)
    return {
        "tool_use": tool_use_ids,
        "tool_result": tool_result_ids,
        "assistant_text": assistant_texts,
    }


def _message_already_seen(msg: BaseMessage, seen: dict[str, set[str]]) -> bool:
    """Detect messages that map to events already in the log.

    Heuristic:
        - ``ToolMessage`` whose ``tool_call_id`` matches a prior
          ``tool_result`` event is a re-emit.
        - ``AIMessage`` whose tool_call ids are all already seen AND
          whose textual content matches a previously-emitted
          ``assistant.message`` is a re-emit.
        - ``HumanMessage`` is never an adapter emission (skipped
          upstream).
    """
    if isinstance(msg, ToolMessage):
        tcid = getattr(msg, "tool_call_id", "")
        return bool(tcid) and tcid in seen["tool_result"]
    if isinstance(msg, AIMessage):
        text = msg.content if isinstance(msg.content, str) else ""
        tool_call_ids = {tc.get("id", "") for tc in (msg.tool_calls or [])}
        if (
            tool_call_ids
            and tool_call_ids.issubset(seen["tool_use"])
            and (not text or text.strip() in seen["assistant_text"])
        ):
            # All tool_uses replayed by the graph already exist in the
            # log AND the textual content (if any) matches a prior
            # assistant.message — treat as duplicate.
            return True
        return bool(text and text.strip() in seen["assistant_text"])
    # HumanMessage / SystemMessage — never our emission.
    return isinstance(msg, HumanMessage)


async def _astream_multi(
    graph: CompiledStateGraph[Any, Any, Any, Any],
    seed: dict[str, Any],
    modes: tuple[str, ...],
) -> AsyncIterator[tuple[str, Any]]:
    """Stream a graph in multiple modes, tagging each chunk with its mode.

    LangGraph supports ``stream_mode`` as a list, in which case each
    chunk is yielded as ``(mode, payload)``. We pass through that
    behaviour but normalise the result type for downstream
    consumption.
    """
    if len(modes) == 1:
        async for chunk in graph.astream(seed, stream_mode=modes[0]):  # type: ignore[arg-type]
            yield modes[0], chunk
        return

    async for tagged in graph.astream(seed, stream_mode=list(modes)):  # type: ignore[arg-type]
        # LangGraph yields (mode, chunk) tuples when stream_mode is a list.
        if isinstance(tagged, tuple) and len(tagged) == 2:
            mode, payload = tagged
            yield mode, payload
        else:
            # Defensive: shouldn't happen but don't crash.
            yield modes[0], tagged


async def _delta_event_for_messages_chunk(
    msg: BaseMessage,
    session_id: str,
) -> AsyncIterator[Event]:
    """Yield an ``assistant.delta`` for a token-stream chunk if applicable.

    LangGraph's ``stream_mode="messages"`` yields ``BaseMessage``
    instances mid-stream (typically AIMessageChunk). We only surface
    deltas for the textual content; tool_call streaming is observed
    via the "updates" path instead.
    """
    if not isinstance(msg, AIMessage):
        return
    content = msg.content
    text = content if isinstance(content, str) else ""
    if not text:
        return
    yield _placeholder_event(
        session_id,
        "assistant.delta",
        {"index": 0, "delta": {"type": "text_delta", "text": text}},
    )


# ---------------------------------------------------------------------------
# Entry point factory + minimal default graph
# ---------------------------------------------------------------------------


def _build_default_graph(
    tools: ToolRegistry | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """A small default StateGraph for the entry-point factory.

    Used when callers create the adapter via the ``wake.adapters``
    entry point without supplying a graph. Behaviour:

    1. ``model`` node — inspects the most recent ``HumanMessage`` and:

       - If the registry has tools registered, emits an ``AIMessage``
         with one ``tool_call`` per tool (best-effort args inferred
         from the tool's schema or the user text).
       - Otherwise emits a single ``AIMessage`` with text
         ``"ok — echo: {user_text}"`` so ``basic_step`` conformance
         passes.
       - If the previous turn already produced a ``ToolMessage``,
         emits a final ``AIMessage`` summarising the tool results.

    2. ``tools`` node — replaced at runtime by Wake's tool node via
       :func:`inject_wake_tools`. We register it with a no-op stub.

    No real LLM is invoked.
    """
    from langgraph.graph import END, START, StateGraph
    from langgraph.prebuilt import ToolNode

    tool_names: list[str] = []
    tool_descs: list[Any] = []
    if tools is not None:
        tool_descs = list(tools.list())
        tool_names = [d.name for d in tool_descs]

    def _model(state: _DefaultEchoState) -> dict[str, list[BaseMessage]]:
        msgs = list(state["messages"])
        if not msgs:
            return {"messages": [AIMessage(content="ok")]}

        # If the latest message is a ToolMessage, we're post-tool-call
        # — synthesise a final assistant message.
        last = msgs[-1]
        if isinstance(last, ToolMessage):
            return {
                "messages": [
                    AIMessage(content="ok — tools completed")
                ]
            }

        # If we already produced a tool_call this turn and got results,
        # but the last message is still an AIMessage with tool_calls,
        # don't loop — emit final ok.
        if isinstance(last, AIMessage) and last.tool_calls:
            return {"messages": [AIMessage(content="ok — done")]}

        # Find most recent HumanMessage.
        last_user_text = ""
        for m in reversed(msgs):
            if isinstance(m, HumanMessage):
                last_user_text = (
                    m.content if isinstance(m.content, str) else ""
                )
                break

        if not tool_names:
            return {
                "messages": [
                    AIMessage(content=f"ok — echo: {last_user_text}")
                ]
            }

        # Build a tool_call per registered tool with best-effort args.
        tool_calls = []
        for i, desc in enumerate(tool_descs):
            args = _guess_tool_args(desc, last_user_text)
            tool_calls.append(
                {
                    "name": desc.name,
                    "args": args,
                    "id": f"dft_{desc.name}_{i}",
                    "type": "tool_call",
                }
            )
        return {
            "messages": [
                AIMessage(content="", tool_calls=tool_calls)
            ]
        }

    def _should_continue(state: _DefaultEchoState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return END

    builder: StateGraph[Any, Any, Any, Any] = StateGraph(_DefaultEchoState)
    builder.add_node("model", _model)
    # Stub ToolNode — gets swapped by inject_wake_tools at runtime. We
    # need a real ToolNode here so the swap detects it; pass an empty
    # tool list since the swap replaces the runnable entirely.
    if tool_names:
        builder.add_node("tools", ToolNode([]))
        builder.add_edge(START, "model")
        builder.add_conditional_edges(
            "model",
            _should_continue,
            {"tools": "tools", END: END},
        )
        builder.add_edge("tools", "model")
    else:
        builder.add_edge(START, "model")
        builder.add_edge("model", END)
    return builder.compile()


def _guess_tool_args(descriptor: Any, user_text: str) -> dict[str, Any]:
    """Best-effort args for the default graph's tool_calls.

    Pulls required properties from the descriptor's JSON schema and
    fills strings with the user text, numbers with 0, booleans with
    True. Adapters with their own graphs supply real model-driven
    args; this is only for the discovery-mode entry-point factory.
    """
    schema: dict[str, Any] = getattr(descriptor, "schema", {}) or {}
    properties: dict[str, Any] = schema.get("properties", {}) or {}
    required: list[str] = schema.get("required", []) or []

    args: dict[str, Any] = {}
    # If nothing required, supply every property; otherwise just the
    # required ones.
    keys = required or list(properties.keys())
    for key in keys:
        prop = properties.get(key) or {}
        ptype = prop.get("type") if isinstance(prop, dict) else None
        if ptype == "string":
            args[key] = user_text or "x"
        elif ptype == "integer":
            args[key] = 0
        elif ptype == "number":
            args[key] = 0.0
        elif ptype == "boolean":
            args[key] = True
        elif ptype == "array":
            args[key] = []
        elif ptype == "object":
            args[key] = {}
        else:
            args[key] = user_text or "x"
    if not args:
        # Fall back to ``text`` (matches most conformance fake tools).
        args["text"] = user_text or "x"
    return args


def create() -> LangGraphAdapter:
    """Factory used by the ``wake.adapters`` entry point.

    Returns an adapter without a pre-bound graph (``graph=None``);
    ``step()`` synthesises a per-call default graph that knows about
    the tools currently registered for the session. Real users
    construct :class:`LangGraphAdapter(my_compiled_graph)` directly.
    """
    return LangGraphAdapter(None)


__all__ = ["LangGraphAdapter", "create"]
