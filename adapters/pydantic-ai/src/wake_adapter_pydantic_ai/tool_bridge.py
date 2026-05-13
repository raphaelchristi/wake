"""Bridge Wake :class:`ToolRegistry` ↔ Pydantic AI tools.

The Wake runtime owns the canonical view of "what tools is this session
allowed to use" (with permission policy, sandbox routing, vault
credential injection — all done in ``tools.execute``).

Pydantic AI lets a caller attach a sequence of :class:`AbstractToolset`
to a run via the ``toolsets=...`` keyword on :meth:`Agent.run_stream`.
We build a :class:`FunctionToolset` from the Wake registry on every
``step()`` call: each Wake :class:`ToolDescriptor` becomes a
Python function whose body calls ``tools.execute(name, kwargs,
tool_use_id=...)`` — so the adapter never invokes a tool implementation
directly. That's the contract from
``docs/SPEC-HARNESS-ADAPTER.md`` §"Requisitos de conformidade".

The tool_use_id we send to Wake's registry is the *same* id that
Pydantic AI assigns to the originating ``ToolCallPart``
(``RunContext.tool_call_id``). That keeps the pairing clean in both
directions: Wake's emitted ``tool_use`` / ``tool_result`` events
reuse the Pydantic AI id, and Pydantic AI's own message history is
left untouched.

Why dynamic toolsets (not ``@agent.tool``)?
-------------------------------------------

``@agent.tool`` is a *decorator* that mutates the ``Agent`` instance at
import time; using it from inside ``step()`` would leak state across
sessions (and accumulate duplicates on every step). ``FunctionToolset``
+ ``run_stream(toolsets=[...])`` is the official escape hatch for
runtime-attached tools — see the Pydantic AI Toolsets docs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

# ``RunContext`` is imported at module load time (not in a TYPE_CHECKING
# block) because Pydantic AI calls ``typing.get_type_hints`` on our tool
# functions at registration time and would otherwise fail with
# ``NameError: RunContext``.
from pydantic_ai import RunContext  # noqa: TC002
from pydantic_ai.toolsets import FunctionToolset

if TYPE_CHECKING:
    from wake.adapters.tool_registry import ToolRegistry
    from wake.types import ToolDescriptor


def _python_identifier(name: str) -> str:
    """Coerce a Wake tool name into a valid Python identifier.

    Pydantic AI infers a tool's exposed name from the underlying
    function's ``__name__`` (when no ``name=`` override is supplied).
    Wake tool names are otherwise free-form (e.g. ``"mcp.weather"``)
    which would crash :func:`exec` in ``add_function``. We supply
    ``name=`` explicitly to FunctionToolset.add_function so the wire
    name matches the Wake descriptor verbatim, and use a safe
    identifier for the underlying function ``__name__`` to keep
    Pydantic AI's introspection happy.
    """
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in name)
    if not safe:
        return "wake_tool"
    if safe[0].isdigit():
        safe = f"t_{safe}"
    return safe


def _make_tool_function(
    descriptor: ToolDescriptor,
    tools_registry: ToolRegistry,
    error_index: dict[str, Any],
    fallback_id_factory: Any,
) -> Any:
    """Build the Python function we'll register with Pydantic AI.

    The returned callable is ``async def`` and accepts ``RunContext``
    as its first positional argument (via ``takes_ctx=True`` when
    registering). We pull ``tool_call_id`` straight off the context
    and forward it to ``tools.execute(tool_use_id=...)`` — Pydantic
    AI's tool_call_id IS Wake's tool_use_id for this turn.

    When the Wake tool returns ``is_error=True`` we cannot just raise
    (Pydantic AI's loop would retry the tool or abort the run) and we
    cannot set ``outcome="failed"`` on the resulting ``ToolReturnPart``
    either — Pydantic AI assigns ``outcome`` itself based on whether
    the tool returned cleanly. So we keep a side-channel:
    ``error_index[tool_use_id]`` is populated when the Wake side
    flagged an error, and the adapter consults it at message-
    translation time to set ``is_error=True`` on the emitted Wake
    ``tool_result`` event. The Pydantic AI conversation still sees a
    string (with an ``[error]`` marker) so the model can react.
    """

    async def wake_tool_impl(ctx: RunContext[Any], **kwargs: Any) -> Any:
        # Use the Pydantic AI tool_call_id as the Wake tool_use_id so
        # the two log views stay synchronised. Fall back to a minted
        # id only if Pydantic AI somehow leaves the field blank.
        tool_use_id = ctx.tool_call_id or fallback_id_factory(descriptor.name)
        result = await tools_registry.execute(
            descriptor.name,
            kwargs,
            tool_use_id=tool_use_id,
        )
        text = "\n".join(block.text for block in result.content)
        if result.is_error:
            error_index[tool_use_id] = result.error_code or "unknown"
            return f"[tool_error:{result.error_code or 'unknown'}] {text}"
        error_index.setdefault(tool_use_id, None)
        return text

    wake_tool_impl.__name__ = _python_identifier(descriptor.name)
    wake_tool_impl.__doc__ = descriptor.description
    return wake_tool_impl


def build_wake_toolset(
    tools_registry: ToolRegistry,
    *,
    tool_use_id_factory: Any,
    error_index: dict[str, Any] | None = None,
) -> FunctionToolset[Any]:
    """Build a :class:`FunctionToolset` exposing every Wake tool.

    Parameters
    ----------
    tools_registry:
        The Wake registry passed to ``HarnessAdapter.step``. Tools are
        already filtered by permission policy.
    tool_use_id_factory:
        Callable ``(tool_name: str) -> str`` used as a fallback when
        Pydantic AI fails to attach a ``tool_call_id`` to the
        :class:`RunContext` for this invocation (rare; defensive).
    error_index:
        Optional dict used as a side channel between the tool
        functions and the adapter — see :func:`_make_tool_function`.

    Returns
    -------
    FunctionToolset
        Pass this to ``Agent.run_stream(..., toolsets=[ts])``.
    """
    ei = error_index if error_index is not None else {}
    ts: FunctionToolset[Any] = FunctionToolset()
    for descriptor in tools_registry.list():
        fn = _make_tool_function(
            descriptor,
            tools_registry,
            ei,
            tool_use_id_factory,
        )
        ts.add_function(
            fn,
            takes_ctx=True,
            name=descriptor.name,
            description=descriptor.description or fn.__name__,
        )
    return ts


def register_wake_tools(
    agent: Any,
    tools_registry: ToolRegistry,
    *,
    tool_use_id_factory: Any,
    error_index: dict[str, Any] | None = None,
) -> FunctionToolset[Any]:
    """Convenience wrapper that returns a toolset for the given agent.

    The actual attachment happens at run time via the ``toolsets=``
    kwarg on :meth:`Agent.run_stream` — see :meth:`PydanticAIAdapter.step`.
    The ``agent`` parameter is kept in the signature for symmetry with
    ``ClaudeSDKAdapter`` (and so future versions can do
    capability-gating). Currently we just delegate to
    :func:`build_wake_toolset`.
    """
    del agent  # unused — toolsets are passed per-run, not bound to the agent
    return build_wake_toolset(
        tools_registry,
        tool_use_id_factory=tool_use_id_factory,
        error_index=error_index,
    )
