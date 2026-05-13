"""Wake HarnessAdapter for CrewAI.

Wraps a CrewAI ``Crew`` (constructed lazily per turn by a user-supplied
factory) into the Wake :class:`HarnessAdapter` Protocol. CrewAI owns the
orchestration; this adapter bridges Wake events <-> CrewAI callbacks and
Wake's ``ToolRegistry`` <-> CrewAI ``BaseTool``s.

See :mod:`wake_adapter_crewai.adapter` for the entry point and
:mod:`wake_adapter_crewai.callbacks` / :mod:`wake_adapter_crewai.tool_bridge`
for the bridges.
"""

from wake_adapter_crewai.adapter import CrewAIAdapter, create

__all__ = ["CrewAIAdapter", "create"]
