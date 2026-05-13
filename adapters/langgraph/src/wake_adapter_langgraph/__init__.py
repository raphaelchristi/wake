"""Wake HarnessAdapter for LangGraph StateGraphs.

Implements the ``HarnessAdapter`` Protocol declared in ``wake.adapters``
against a compiled LangGraph ``StateGraph``.

The adapter is a thin generator: it reads events from the supplied
``EventStream``, translates them into LangChain ``BaseMessage`` objects,
streams the graph via ``astream``, translates each new message back into
canonical Wake events, and yields them.

Tool execution is routed through ``tools.execute()`` via a custom node
that replaces any ``ToolNode`` instance in the graph at runtime.

See:
    - ``docs/SPEC-HARNESS-ADAPTER.md`` — narrative spec
    - ``adapters/langgraph/README.md`` — usage + supported features
"""

from wake_adapter_langgraph.adapter import LangGraphAdapter, create
from wake_adapter_langgraph.event_mapping import (
    events_to_state,
    message_to_wake_events,
)
from wake_adapter_langgraph.tool_injection import (
    WakeToolWrapper,
    inject_wake_tools,
    wake_tool_node,
    wake_tools_for_langchain,
)

__all__ = [
    "LangGraphAdapter",
    "WakeToolWrapper",
    "create",
    "events_to_state",
    "inject_wake_tools",
    "message_to_wake_events",
    "wake_tool_node",
    "wake_tools_for_langchain",
]

__version__ = "0.1.0"
