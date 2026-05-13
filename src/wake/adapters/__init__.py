"""Wake HarnessAdapter ABI v0.1.0.

The HarnessAdapter Protocol is the contract any harness (Claude SDK,
LangGraph, CrewAI, Pydantic AI, custom) must implement to run on the Wake
runtime.

This package is the **source of truth** for the ABI. Other modules and
external adapters import from here.

Schema: ``docs/SPEC-HARNESS-ADAPTER.md`` v0.1.0.
"""

from wake.adapters.base import HarnessAdapter, LifecycleEvent
from wake.adapters.context import SessionContext
from wake.adapters.events import EventStream
from wake.adapters.registry import AdapterRegistry, AdapterRegistryError
from wake.adapters.tool_registry import ToolRegistry

__all__ = [
    "HarnessAdapter",
    "LifecycleEvent",
    "SessionContext",
    "EventStream",
    "ToolRegistry",
    "AdapterRegistry",
    "AdapterRegistryError",
]
