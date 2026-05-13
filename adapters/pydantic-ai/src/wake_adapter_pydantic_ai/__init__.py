"""Wake HarnessAdapter for the Pydantic AI framework.

Implements the ``HarnessAdapter`` Protocol declared in ``wake.adapters``
against a user-supplied :class:`pydantic_ai.Agent`.

The adapter is a thin generator: it reads events from the supplied
``EventStream``, builds a ``message_history`` (and the latest user
prompt) for Pydantic AI, dynamically attaches a ``FunctionToolset``
whose tools route through the Wake :class:`ToolRegistry`, runs the
agent via :meth:`Agent.run_stream`, translates new Pydantic AI messages
into Wake events as the run progresses, and emits a final
``assistant.message``.

Because Pydantic AI is the most strictly-typed framework in the Wake
adapter family (typed outputs via ``output_type``, typed tools via
JSON-schema-from-pydantic), the mapping is the cleanest of the three:
each Wake event maps 1:1 to a Pydantic AI message part and vice
versa.
"""

from wake_adapter_pydantic_ai.adapter import (
    MAX_RECURSION,
    PydanticAIAdapter,
    events_to_message_history,
)
from wake_adapter_pydantic_ai.tool_bridge import (
    build_wake_toolset,
    register_wake_tools,
)

__all__ = [
    "MAX_RECURSION",
    "PydanticAIAdapter",
    "build_wake_toolset",
    "events_to_message_history",
    "register_wake_tools",
]

__version__ = "0.1.0"
