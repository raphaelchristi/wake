"""Adapter-level smoke tests: Protocol conformance, name/version, factory.

These tests do not run a Crew — they only verify the adapter's metadata
and Protocol membership. Functional behavior is covered by
``test_simple_crew``, ``test_multi_agent``, and ``test_conformance``.
"""

from __future__ import annotations

from crewai import Agent, Crew, Task
from wake_adapter_crewai import CrewAIAdapter, create

from wake.adapters import AdapterRegistry, HarnessAdapter


def _trivial_factory(_input: str) -> Crew:
    # The body never runs in these tests — we just need a callable for
    # the constructor's required parameter.
    raise AssertionError("factory should not be invoked in metadata tests")


def test_package_imports() -> None:
    """``from wake_adapter_crewai import CrewAIAdapter`` works."""
    assert CrewAIAdapter is not None
    assert create is not None


def test_adapter_metadata_matches_spec() -> None:
    """name, version, compatibility match Phase 3 contract."""
    adapter = CrewAIAdapter(_trivial_factory)
    assert adapter.name == "crewai"
    assert adapter.version == "0.1.0"
    assert adapter.compatibility == "wake-harness-adapter@^0.1"


def test_adapter_satisfies_harness_protocol() -> None:
    """``HarnessAdapter`` is ``@runtime_checkable``; verify duck typing."""
    adapter = CrewAIAdapter(_trivial_factory)
    assert isinstance(adapter, HarnessAdapter)


def test_create_returns_adapter() -> None:
    """The ``wake.adapters`` entry point ``create()`` yields an adapter."""
    adapter = create()
    assert isinstance(adapter, CrewAIAdapter)
    assert adapter.name == "crewai"


def test_entry_point_discoverable() -> None:
    """``AdapterRegistry.discover()`` finds us via the entry-point group."""
    registry = AdapterRegistry()
    registry.discover()
    assert "crewai" in registry.names()
    adapter = registry.get("crewai")
    assert adapter.name == "crewai"
    assert adapter.version == "0.1.0"


def test_constructor_accepts_crew_factory(fake_llm_factory: type) -> None:
    """The constructor's required argument is the crew factory callable."""
    FakeLLM = fake_llm_factory  # noqa: N806

    def factory(user_input: str) -> Crew:
        llm = FakeLLM(model="fake", responses=["Final Answer: ok"])
        agent = Agent(role="t", goal="g", backstory="b", llm=llm)
        task = Task(description=user_input, expected_output="o", agent=agent)
        return Crew(agents=[agent], tasks=[task])

    adapter = CrewAIAdapter(factory)
    # Stash for introspection — name lookup goes via the public attr.
    assert callable(adapter._crew_factory)
