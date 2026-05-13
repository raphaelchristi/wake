"""Wake tool injection into LangGraph graphs.

LangGraph's ``ToolNode`` expects ``BaseTool`` instances. Wake adapters
are required to route tool execution through ``tools.execute(name,
input, tool_use_id=...)`` instead of calling tool functions directly.

This module provides:

- :func:`wake_tools_for_langchain`  — wrap each Wake ``ToolDescriptor``
  as a ``BaseTool`` whose async invocation forwards to
  ``ToolRegistry.execute``.
- :func:`wake_tool_node`            — a drop-in replacement for
  ``langgraph.prebuilt.ToolNode``: an async callable that reads the
  latest ``AIMessage.tool_calls`` from state and emits a list of
  ``ToolMessage`` via ``tools.execute``.
- :func:`inject_wake_tools`         — deep-copy a compiled graph's
  builder, swap every ``ToolNode`` node for the Wake-aware variant,
  and recompile.
"""

from __future__ import annotations

import copy
import dataclasses
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.prebuilt import ToolNode
from pydantic import Field, PrivateAttr, create_model

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    from wake.adapters.tool_registry import ToolRegistry
    from wake.types import ToolDescriptor


def _python_type_for_schema(schema: dict[str, Any]) -> Any:
    """Best-effort JSON-schema → Python type.

    The adapter is happy to be loose here: LangGraph only uses the
    args_schema for serialisation/validation, and our Wake tools
    accept ``dict[str, Any]`` anyway. ``Any`` is a safe default.
    """
    t = schema.get("type")
    if t == "string":
        return str
    if t == "integer":
        return int
    if t == "number":
        return float
    if t == "boolean":
        return bool
    if t == "array":
        return list
    if t == "object":
        return dict
    return Any


def _args_schema_for_descriptor(desc: ToolDescriptor) -> Any:
    """Build a tiny pydantic model from a Wake JSON-schema descriptor.

    LangChain's ``BaseTool`` uses ``args_schema`` to validate inputs.
    We synthesise a permissive model: required fields keep their type,
    optional fields default to ``None``. Unknown shapes degrade to
    ``Any``.
    """
    properties: dict[str, Any] = (desc.schema or {}).get("properties", {})
    required: set[str] = set((desc.schema or {}).get("required", []))
    fields: dict[str, tuple[Any, Any]] = {}
    for name, prop in properties.items():
        if not isinstance(prop, dict):
            fields[name] = (Any, Field(default=None, description=""))
            continue
        py_type = _python_type_for_schema(prop)
        description = prop.get("description", "") or ""
        if name in required:
            fields[name] = (py_type, Field(..., description=description))
        else:
            fields[name] = (py_type | None, Field(default=None, description=description))

    # ``create_model`` accepts kwargs for fields; mypy struggles with
    # the dynamic call, hence Any-typed return.
    return create_model(f"WakeToolArgs_{desc.name}", **fields)  # type: ignore[call-overload]


class WakeToolWrapper(BaseTool):
    """LangChain ``BaseTool`` that forwards execution to a Wake ``ToolRegistry``.

    Instances are constructed by :func:`wake_tools_for_langchain` from a
    Wake ``ToolDescriptor``. ``_arun`` calls
    ``self._registry.execute(self.name, kwargs, tool_use_id=...)`` and
    returns the textual content of the result.

    The wrapper is NOT meant to be invoked directly by the adapter —
    when our :func:`wake_tool_node` is in place, the adapter executes
    tools itself with the correct ``tool_use_id``. The wrapper exists
    so that any *non-replaced* tool node (e.g. one the user attaches
    elsewhere) still routes through Wake.
    """

    name: str = ""
    description: str = ""
    args_schema: Any = None
    _registry: Any = PrivateAttr()

    def __init__(self, *, descriptor: ToolDescriptor, registry: ToolRegistry, **kwargs: Any) -> None:
        super().__init__(
            name=descriptor.name,
            description=descriptor.description or descriptor.name,
            args_schema=_args_schema_for_descriptor(descriptor),
            **kwargs,
        )
        self._registry = registry

    def _run(self, *args: Any, **kwargs: Any) -> str:
        raise NotImplementedError(
            "WakeToolWrapper is async-only; use ainvoke / await _arun"
        )

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        # Strip LangChain-injected kwargs that aren't tool args.
        kwargs.pop("run_manager", None)
        kwargs.pop("config", None)
        kwargs.pop("runtime", None)
        # We don't have a tool_use_id at this layer; use a sentinel that
        # the registry can still log. In practice the wake_tool_node
        # pathway carries the real id.
        result = await self._registry.execute(
            self.name,
            dict(kwargs),
            tool_use_id=f"wrapper-{self.name}",
        )
        if not result.content:
            return ""
        text: str = result.content[0].text
        return text


def wake_tools_for_langchain(registry: ToolRegistry) -> list[BaseTool]:
    """Wrap every tool exposed by ``registry`` as a LangChain ``BaseTool``."""
    return [WakeToolWrapper(descriptor=d, registry=registry) for d in registry.list()]


def wake_tool_node(
    registry: ToolRegistry,
    *,
    state_key: str = "messages",
) -> Any:
    """Build an async node callable that replaces ``ToolNode``.

    The returned coroutine handles BOTH invocation conventions that
    LangGraph uses for tool nodes:

    1. **Classic** — ``state`` is the graph's state dict with a
       ``messages`` key. The node reads the trailing ``AIMessage``,
       executes every ``tool_call``, and returns
       ``{state_key: [ToolMessage, ...]}``.

    2. **Send-based (LangGraph 1.x ReAct)** — ``state`` is a
       ``tool_call_with_context`` dict ``{"__type": ..., "tool_call":
       {...}, "state": {...}}``. The node executes the single
       ``tool_call`` and returns ``{state_key: [ToolMessage]}`` for the
       parent state.

    Errors from ``registry.execute`` are returned as ``ToolMessage``s
    with ``status='error'`` so the model can decide how to recover —
    matching ``ToolNode``'s default behaviour with
    ``handle_tool_errors``.
    """

    async def _execute_call(tc: dict[str, Any]) -> ToolMessage:
        tc_id = tc.get("id", "")
        name = tc.get("name", "")
        args = tc.get("args", {}) or {}
        try:
            result = await registry.execute(name, args, tool_use_id=tc_id)
        except Exception as exc:  # noqa: BLE001
            return ToolMessage(
                content=f"tool {name!r} raised {type(exc).__name__}: {exc}",
                tool_call_id=tc_id,
                name=name,
                status="error",
            )
        text = result.content[0].text if result.content else ""
        return ToolMessage(
            content=text,
            tool_call_id=tc_id,
            name=name,
            status="error" if result.is_error else "success",
        )

    async def _node(state: dict[str, Any]) -> dict[str, list[ToolMessage]]:
        # Send-based dispatch (LangGraph 1.x ReAct): each invocation
        # carries exactly one tool_call.
        if isinstance(state, dict) and state.get("__type") == "tool_call_with_context":
            tc = state.get("tool_call") or {}
            return {state_key: [await _execute_call(tc)]}

        # Classic dispatch: pull tool_calls off the trailing AIMessage.
        messages = state.get(state_key) or []
        if not messages:
            return {state_key: []}
        last = messages[-1]
        tool_calls = getattr(last, "tool_calls", None) or []
        if not isinstance(last, AIMessage) or not tool_calls:
            return {state_key: []}
        out: list[ToolMessage] = []
        for tc in tool_calls:
            out.append(await _execute_call(tc))
        return {state_key: out}

    return _node


def inject_wake_tools(
    graph: CompiledStateGraph[Any, Any, Any, Any],
    registry: ToolRegistry,
    *,
    state_key: str = "messages",
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Return a runtime clone of ``graph`` with Wake-aware tool nodes.

    Strategy:
        1. Deep-copy the graph's builder so we don't mutate the
           caller's graph definition.
        2. Walk ``builder.nodes``; for every node whose runnable is a
           ``ToolNode``, swap in :func:`wake_tool_node`.
        3. Recompile and return the new ``CompiledStateGraph[Any, Any, Any, Any]``.

    If the graph contains no ``ToolNode`` instances, the clone is
    structurally identical and any tool calls the user model makes will
    still be routed through Wake provided the user wired
    :func:`wake_tools_for_langchain` as their model's tools.
    """
    builder = getattr(graph, "builder", None)
    if builder is None:
        # Graph constructed without ``StateGraph.compile`` (e.g. a custom
        # Pregel). We can't rewrite — return as-is. Real Wake tool
        # routing then depends on the user binding ``wake_tools_for_langchain``
        # to their model.
        return graph

    cloned_builder = copy.deepcopy(builder)

    wake_node = wake_tool_node(registry, state_key=state_key)

    replaced = False
    for node_name, spec in cloned_builder.nodes.items():
        runnable = getattr(spec, "runnable", None)
        # Detect ToolNode by isinstance OR by class name (tolerates
        # subclasses and wrapped variants).
        is_tool_node = isinstance(runnable, ToolNode) or (
            runnable is not None and type(runnable).__name__ == "ToolNode"
        )
        if is_tool_node:
            cloned_builder.nodes[node_name] = dataclasses.replace(spec, runnable=wake_node)
            replaced = True

    if not replaced:
        # Nothing to rewrite; return the original compiled graph to
        # avoid the recompile cost.
        return graph

    new_graph: CompiledStateGraph[Any, Any, Any, Any] = cloned_builder.compile()
    return new_graph


__all__ = [
    "WakeToolWrapper",
    "inject_wake_tools",
    "wake_tool_node",
    "wake_tools_for_langchain",
]
