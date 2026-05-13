"""Wake HarnessAdapter for LangGraph — Phase 2 STUB.

This package exposes :class:`LangGraphAdapter`, a stub implementation of
the ``HarnessAdapter`` Protocol. It demonstrates entry-point discovery
and the ABI surface, but does NOT yet run LangGraph StateGraphs.

A full implementation is planned for Phase 3 (see
``phases/PHASE-3-spec-validation.md``).
"""

from wake_adapter_langgraph.adapter import LangGraphAdapter, create

__all__ = ["LangGraphAdapter", "create"]
