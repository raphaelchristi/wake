"""Stub conformance for ``wake-adapter-langgraph``.

These tests are intentionally minimal: they exercise the three things a
Phase 2 stub must guarantee.

1. The package imports.
2. The ``wake.adapters`` entry point is discoverable by
   :class:`wake.adapters.AdapterRegistry`.
3. ``step()`` and ``on_lifecycle()`` behave as documented.

The full conformance suite (``wake-test-conformance``) is run against
the production Claude SDK adapter; stubs are exempt from it for now.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from wake.adapters import AdapterRegistry, HarnessAdapter
from wake.adapters.context import SessionContext
from wake.types import AgentConfig, ModelConfig

# ---------------------------------------------------------------------------
# Fixtures: a SessionContext + dummy events / tools the stub doesn't read.
# ---------------------------------------------------------------------------


def _make_ctx() -> SessionContext:
    """Build a minimal :class:`SessionContext` for the stub to ignore."""
    now = datetime.now(UTC)
    agent = AgentConfig(
        id="agt_test",
        name="stub-test-agent",
        model=ModelConfig(id="claude-opus-4-7"),
        created_at=now,
        updated_at=now,
    )
    return SessionContext(
        session_id="sess_test",
        agent_id=agent.id,
        agent_version=agent.version,
        agent_config=agent,
    )


class _NullEventStream:
    """Stand-in EventStream — never read by the stub."""

    async def all(self) -> list[Any]:
        return []

    async def since(self, seq: int) -> list[Any]:
        return []

    async def latest(self, type: Any = None) -> Any:  # noqa: A002 — matches EventStream ABI
        return None

    async def count(self) -> int:
        return 0


class _NullToolRegistry:
    """Stand-in ToolRegistry — never read by the stub."""

    def list(self) -> list[Any]:
        return []

    def get(self, name: str) -> Any:
        raise KeyError(name)

    async def execute(
        self,
        name: str,
        input: dict[str, Any],  # noqa: A002 — matches ToolRegistry ABI
        *,
        tool_use_id: str,
    ) -> Any:
        raise NotImplementedError("stub never calls tools")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_package_imports() -> None:
    """``from wake_adapter_langgraph import LangGraphAdapter`` works."""
    from wake_adapter_langgraph import LangGraphAdapter, create

    adapter = create()
    assert isinstance(adapter, LangGraphAdapter)


def test_adapter_protocol_conformance() -> None:
    """The stub satisfies the ``HarnessAdapter`` Protocol at runtime."""
    from wake_adapter_langgraph import LangGraphAdapter

    adapter = LangGraphAdapter()
    # runtime_checkable Protocol — duck-typed via isinstance
    assert isinstance(adapter, HarnessAdapter)
    assert adapter.name == "langgraph"
    assert adapter.version == "0.1.0-stub"
    assert adapter.compatibility == "wake-harness-adapter@^0.1"


def test_entry_point_discoverable() -> None:
    """``AdapterRegistry.discover()`` picks up the stub via entry points."""
    registry = AdapterRegistry()
    registry.discover()

    assert "langgraph" in registry.names(), (
        f"langgraph stub not discovered; saw {registry.names()!r}"
    )
    adapter = registry.get("langgraph")
    assert adapter.name == "langgraph"
    assert adapter.version == "0.1.0-stub"


@pytest.mark.asyncio
async def test_step_emits_single_message() -> None:
    """``step()`` yields exactly one ``assistant.message`` event."""
    from wake_adapter_langgraph import LangGraphAdapter

    adapter = LangGraphAdapter()
    ctx = _make_ctx()
    events = _NullEventStream()
    tools = _NullToolRegistry()

    emitted = [ev async for ev in adapter.step(ctx, events, tools)]

    assert len(emitted) == 1, f"expected 1 event, got {len(emitted)}"
    (msg,) = emitted
    assert msg.type == "assistant.message"
    assert msg.session_id == ctx.session_id
    content = msg.payload["content"]
    assert content == [{"type": "text", "text": "stub from langgraph"}]
    assert msg.payload["stop_reason"] == "end_turn"


@pytest.mark.asyncio
async def test_on_lifecycle_is_noop() -> None:
    """``on_lifecycle()`` is callable for every lifecycle event without raising."""
    from wake_adapter_langgraph import LangGraphAdapter

    adapter = LangGraphAdapter()
    ctx = _make_ctx()

    for ev in ("created", "resumed", "interrupted", "terminated"):
        result = await adapter.on_lifecycle(ctx, ev)  # type: ignore[arg-type]
        assert result is None
