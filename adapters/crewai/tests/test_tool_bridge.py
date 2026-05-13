"""Unit tests for :mod:`wake_adapter_crewai.tool_bridge`.

We exercise the wrapper class produced by :func:`wake_tool_to_crewai`
without involving CrewAI's agent loop — we just call ``_run`` directly
the way CrewAI eventually would. This isolates the bridge from the
LLM-driven side and keeps the tests fast and deterministic.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from wake_adapter_crewai.tool_bridge import (
    _coerce_input,
    _result_to_string,
    build_crewai_tools,
    wake_tool_to_crewai,
)

from wake.types import TextBlock, ToolDescriptor, ToolResult


class FakeRegistry:
    """Minimal :class:`ToolRegistry` for unit tests.

    Stores tools and records every execute() call (matching the
    InMemoryToolRegistry contract used by the conformance harness).
    """

    def __init__(self, descriptors: list[ToolDescriptor] | None = None) -> None:
        self._descriptors = descriptors or []
        self.calls: list[dict[str, Any]] = []
        self.next_result: ToolResult = ToolResult(
            content=[TextBlock(text="ok")], is_error=False
        )

    def list(self) -> list[ToolDescriptor]:
        return list(self._descriptors)

    def get(self, name: str) -> ToolDescriptor:
        for d in self._descriptors:
            if d.name == name:
                return d
        raise KeyError(name)

    async def execute(
        self,
        name: str,
        input: dict[str, Any],  # noqa: A002 — matches ToolRegistry ABI
        *,
        tool_use_id: str,
    ) -> ToolResult:
        self.calls.append(
            {"name": name, "input": input, "tool_use_id": tool_use_id}
        )
        return self.next_result


# ---------------------------------------------------------------------------
# _coerce_input
# ---------------------------------------------------------------------------


def test_coerce_input_keyword_args() -> None:
    """Kwargs pass through as the dict."""
    assert _coerce_input((), {"text": "hi"}) == {"text": "hi"}


def test_coerce_input_single_dict_positional() -> None:
    assert _coerce_input(({"text": "hi"},), {}) == {"text": "hi"}


def test_coerce_input_single_json_string_positional() -> None:
    """Agents sometimes hand the tool a JSON-serialized object."""
    assert _coerce_input((json.dumps({"text": "hi"}),), {}) == {"text": "hi"}


def test_coerce_input_single_plain_string_positional() -> None:
    """A bare string becomes ``{'input': string}``."""
    assert _coerce_input(("hi",), {}) == {"input": "hi"}


def test_coerce_input_empty() -> None:
    assert _coerce_input((), {}) == {}


# ---------------------------------------------------------------------------
# _result_to_string
# ---------------------------------------------------------------------------


def test_result_to_string_joins_text_blocks() -> None:
    res = ToolResult(
        content=[TextBlock(text="line1"), TextBlock(text="line2")],
        is_error=False,
    )
    assert _result_to_string(res) == "line1\nline2"


def test_result_to_string_marks_errors() -> None:
    res = ToolResult(
        content=[TextBlock(text="boom")],
        is_error=True,
        error_code="boom_code",
    )
    out = _result_to_string(res)
    assert out.startswith("[tool error]")
    assert "boom" in out


# ---------------------------------------------------------------------------
# wake_tool_to_crewai + build_crewai_tools
# ---------------------------------------------------------------------------


def test_wrap_single_tool_runs_through_registry() -> None:
    desc = ToolDescriptor(
        name="echo",
        description="echo back",
        schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )
    registry = FakeRegistry([desc])
    registry.next_result = ToolResult(
        content=[TextBlock(text="echo: hi")], is_error=False
    )

    captured: list[tuple[str, str, dict[str, Any], ToolResult]] = []

    def on_inv(
        tool_use_id: str,
        name: str,
        input_data: dict[str, Any],
        result: ToolResult,
    ) -> None:
        captured.append((tool_use_id, name, input_data, result))

    wrapper = wake_tool_to_crewai(desc, registry, on_invocation=on_inv)
    assert wrapper.name == "echo"
    # CrewAI BaseTool augments ``description`` with "Tool Name: ..." plus
    # the JSON arg schema. The original text is still substring-present.
    assert "echo back" in wrapper.description

    rendered = wrapper._run(text="hi")
    assert rendered == "echo: hi"

    # The registry recorded the execute() call (not a direct invocation).
    assert len(registry.calls) == 1
    call = registry.calls[0]
    assert call["name"] == "echo"
    assert call["input"] == {"text": "hi"}
    assert call["tool_use_id"]  # non-empty

    # The on_invocation hook fired once with the correlating data.
    assert len(captured) == 1
    use_id, name, input_data, result = captured[0]
    assert use_id == call["tool_use_id"]
    assert name == "echo"
    assert input_data == {"text": "hi"}
    assert _result_to_string(result) == "echo: hi"


def test_wrap_tool_handles_exceptions_as_tool_error() -> None:
    """Registry errors don't crash the wrapper — they surface as tool errors."""
    desc = ToolDescriptor(
        name="boom", description="explodes", schema={"type": "object"}
    )

    class ExplodingRegistry(FakeRegistry):
        async def execute(self, name, input, *, tool_use_id):  # type: ignore[override]  # noqa: A002
            raise RuntimeError("kaboom")

    registry = ExplodingRegistry([desc])
    captured: list[ToolResult] = []
    wrapper = wake_tool_to_crewai(
        desc, registry, on_invocation=lambda _i, _n, _d, r: captured.append(r)
    )
    out = wrapper._run()
    assert "kaboom" in out
    assert out.startswith("[tool error]")
    assert captured and captured[0].is_error is True


def test_build_crewai_tools_yields_one_per_descriptor() -> None:
    descs = [
        ToolDescriptor(name="a", description="a", schema={"type": "object"}),
        ToolDescriptor(name="b", description="b", schema={"type": "object"}),
    ]
    registry = FakeRegistry(descs)
    tools = build_crewai_tools(registry, on_invocation=lambda *_: None)
    assert [t.name for t in tools] == ["a", "b"]


def test_build_crewai_tools_empty_registry() -> None:
    registry = FakeRegistry([])
    tools = build_crewai_tools(registry, on_invocation=lambda *_: None)
    assert tools == []


@pytest.mark.parametrize(
    "schema,args,kwargs,expected_input",
    [
        # Properly typed schema -> kwargs forwarded.
        (
            {
                "type": "object",
                "properties": {"x": {"type": "string"}},
                "required": ["x"],
            },
            (),
            {"x": "v"},
            {"x": "v"},
        ),
        # No schema -> empty dict ok.
        ({}, (), {}, {}),
    ],
)
def test_wrapper_input_routing(
    schema: dict[str, Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    expected_input: dict[str, Any],
) -> None:
    desc = ToolDescriptor(name="t", description="t", schema=schema)
    registry = FakeRegistry([desc])
    wrapper = wake_tool_to_crewai(
        desc, registry, on_invocation=lambda *_: None
    )
    wrapper._run(*args, **kwargs)
    assert registry.calls[0]["input"] == expected_input
