"""Wake HarnessAdapter for CrewAI — Phase 2 STUB.

This package exposes :class:`CrewAIAdapter`, a stub implementation of
the ``HarnessAdapter`` Protocol. It demonstrates entry-point discovery
and the ABI surface, but does NOT yet run CrewAI ``Crew`` instances.

A full implementation is planned for Phase 3 (see
``phases/PHASE-3-spec-validation.md``).
"""

from wake_adapter_crewai.adapter import CrewAIAdapter, create

__all__ = ["CrewAIAdapter", "create"]
