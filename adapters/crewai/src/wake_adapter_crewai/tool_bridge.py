# ruff: noqa: TC001, TC003, A002
"""Bridge Wake :class:`ToolRegistry` <-> CrewAI :class:`BaseTool`.

Wake adapters must call ``tools.execute(name, input, tool_use_id=...)`` for
every tool invocation; they may NEVER call tool functions directly. CrewAI,
on the other hand, expects each tool to be a :class:`crewai.tools.BaseTool`
instance whose synchronous ``_run`` method does the work.

This module builds a thin wrapper class per Wake tool descriptor. The
wrapper exposes the Wake tool's ``name`` and ``description`` to CrewAI and
funnels every ``_run`` call through ``tools.execute()`` so the runtime's
permission/audit/dedup invariants are preserved.

Each tool invocation gets a fresh ULID-based ``tool_use_id`` and reports the
call through a callback supplied by the adapter — the adapter uses that
hook to emit a Wake ``tool_use`` event *before* the tool body runs and a
``tool_result`` event *after* it returns.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from crewai.tools import BaseTool
from pydantic import BaseModel as PydanticBaseModel
from pydantic import create_model
from ulid import ULID

if TYPE_CHECKING:
    from wake.adapters.tool_registry import ToolRegistry
    from wake.types import ToolDescriptor, ToolResult


_JSON_TYPE_TO_PY: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": dict,
    "array": list,
}


def _schema_to_pydantic(
    name: str, json_schema: dict[str, Any]
) -> type[PydanticBaseModel]:
    """Translate a (subset of) JSON schema into a pydantic model class.

    Only top-level ``properties`` and ``required`` are honored — enough
    for the agent prompt CrewAI emits to include the expected argument
    names. Anything more elaborate (nested objects, enums, anyOf) is
    left as ``Any`` so we don't fight the schema.
    """
    properties = json_schema.get("properties", {}) if json_schema else {}
    required = set(json_schema.get("required", []) if json_schema else [])

    fields: dict[str, Any] = {}
    if not properties:
        # No structured arguments — CrewAI tolerates an empty schema.
        return create_model(f"{name}Args", __base__=PydanticBaseModel)

    for prop_name, prop_schema in properties.items():
        py_type: Any = _JSON_TYPE_TO_PY.get(
            prop_schema.get("type", "string") if isinstance(prop_schema, dict) else "string",
            Any,
        )
        if prop_name in required:
            fields[prop_name] = (py_type, ...)
        else:
            fields[prop_name] = (py_type, None)

    return create_model(f"{name}Args", __base__=PydanticBaseModel, **fields)


ToolEventCallback = Callable[[str, str, dict[str, Any], "ToolResult"], None]
"""Adapter-supplied hook: (tool_use_id, name, input, result) -> None.

Called synchronously inside the tool wrapper. Implementations push two
Wake events (tool_use + tool_result) onto the adapter's event queue.
"""


def _result_to_string(result: ToolResult) -> str:
    """Render a Wake :class:`ToolResult` as a plain string for CrewAI.

    CrewAI tools return a string the agent then reasons over. We
    concatenate the text blocks; on error we prefix with an explicit
    marker so the agent's prompt sees the failure.
    """
    parts: list[str] = []
    for block in result.content:
        # ``block`` is a TextBlock; defensive getattr lets tests pass dicts.
        text = getattr(block, "text", None)
        if text is None and isinstance(block, dict):
            text = block.get("text", "")
        if text:
            parts.append(text)
    rendered = "\n".join(parts)
    if result.is_error:
        return f"[tool error] {rendered}"
    return rendered


def _coerce_input(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    """Normalize CrewAI's varied call shapes into a single input dict.

    CrewAI may invoke a tool with positional args, kwargs, or a single
    JSON-string positional argument (the latter happens when the agent
    serializes structured input). We coerce everything into the dict
    shape Wake tools expect.
    """
    if not args and not kwargs:
        return {}
    if not args:
        return dict(kwargs)
    if len(args) == 1 and not kwargs:
        only = args[0]
        if isinstance(only, dict):
            return dict(only)
        if isinstance(only, str):
            stripped = only.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError:
                    return {"input": only}
                if isinstance(parsed, dict):
                    return parsed
                return {"input": parsed}
            return {"input": only}
        return {"input": only}
    # Mixed positional + kwargs — best-effort merge under generic names.
    merged: dict[str, Any] = dict(kwargs)
    for i, val in enumerate(args):
        merged.setdefault(f"arg{i}", val)
    return merged


def _execute_async_safely(
    tools: ToolRegistry,
    name: str,
    input_data: dict[str, Any],
    tool_use_id: str,
) -> ToolResult:
    """Drive the async ``tools.execute()`` from synchronous CrewAI code.

    CrewAI calls ``_run`` synchronously even when the surrounding code is
    async. We may be:

    1. Outside any event loop -> ``asyncio.run`` is fine.
    2. Inside an event loop but on its thread -> need a fresh loop in
       another thread to avoid ``RuntimeError: asyncio.run() cannot be
       called from a running event loop``.

    The adapter always runs ``crew.kickoff()`` in a worker thread
    (``asyncio.to_thread``), so case 2 dominates in practice. We detect
    both, and never block the caller's loop.
    """
    coro = tools.execute(name, input_data, tool_use_id=tool_use_id)

    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None

    if running is None:
        return asyncio.run(coro)

    # We are inside a running loop. Spin a private loop in a worker
    # thread to drive the coroutine without re-entering the current one.
    import threading

    box: dict[str, Any] = {}

    def _runner() -> None:
        loop = asyncio.new_event_loop()
        try:
            box["result"] = loop.run_until_complete(coro)
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc
        finally:
            loop.close()

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    result: ToolResult = box["result"]
    return result


def wake_tool_to_crewai(
    descriptor: ToolDescriptor,
    tools: ToolRegistry,
    *,
    on_invocation: ToolEventCallback,
) -> BaseTool:
    """Wrap a single Wake :class:`ToolDescriptor` as a CrewAI :class:`BaseTool`.

    The returned BaseTool delegates every ``_run`` to
    ``tools.execute()`` and, just before and after the call, invokes
    ``on_invocation`` so the adapter can emit ``tool_use`` and
    ``tool_result`` Wake events.

    The wrapper class is built dynamically so the tool's name and
    description match the Wake descriptor (CrewAI binds them via pydantic
    Fields, so they must be class-level defaults).
    """
    tool_name = descriptor.name
    tool_desc = descriptor.description or f"Wake tool: {tool_name}"
    args_model = _schema_to_pydantic(
        tool_name, getattr(descriptor, "schema", {}) or {}
    )

    class _WakeToolWrapper(BaseTool):  # type: ignore[misc]
        name: str = tool_name
        description: str = tool_desc
        args_schema: type[PydanticBaseModel] = args_model

        def _run(self, *args: Any, **kwargs: Any) -> str:
            tool_use_id = str(ULID())
            input_data = _coerce_input(args, kwargs)
            try:
                result = _execute_async_safely(
                    tools, tool_name, input_data, tool_use_id
                )
            except Exception as exc:  # noqa: BLE001
                # Surface as a tool error so the agent's loop can react,
                # but also tell the adapter about the (failed) call.
                from wake.types import TextBlock, ToolResult

                result = ToolResult(
                    content=[TextBlock(text=f"{type(exc).__name__}: {exc}")],
                    is_error=True,
                    error_code="adapter_error",
                )
            on_invocation(tool_use_id, tool_name, input_data, result)
            return _result_to_string(result)

    # Hatch a unique class name for debuggability.
    _WakeToolWrapper.__name__ = f"WakeTool_{tool_name}"
    _WakeToolWrapper.__qualname__ = _WakeToolWrapper.__name__
    return _WakeToolWrapper()


def build_crewai_tools(
    tools: ToolRegistry,
    *,
    on_invocation: ToolEventCallback,
) -> list[BaseTool]:
    """Build CrewAI tool wrappers for every Wake tool in the registry.

    Returns an empty list if the registry has no tools — CrewAI agents
    tolerate ``tools=[]`` just fine.
    """
    return [
        wake_tool_to_crewai(desc, tools, on_invocation=on_invocation)
        for desc in tools.list()
    ]
