"""Tests for ``wake.eval.runner`` and the report writers.

Uses an injected ``invoke_fn`` so nothing here hits the network. Three
focus areas:

1. Runner orchestration — sync/async invoke_fn, error handling per row,
   concurrency cap, latency stamping.
2. Aggregation — accuracy, p95 latency, total cost.
3. Report rendering — markdown shape + JSON round-trip.
"""

from __future__ import annotations

import asyncio
import json
from io import StringIO

import pytest

from wake.eval.dataset import parse_row
from wake.eval.report import to_json, to_markdown, write_json, write_markdown
from wake.eval.runner import (
    AgentInvocation,
    EvalRunner,
    RowReport,
    _percentile,
)
from wake.eval.scorer import ScorerRegistry, ScorerResult


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _row(input: str, expected=None, metadata=None):  # type: ignore[no-untyped-def]
    return parse_row(
        {"input": input, "expected": expected, "metadata": metadata or {}},
        line_no=1,
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def test_runner_sync_invoke_fn_works() -> None:
    rows = [
        _row("ping", expected="pong"),
        _row("foo", expected="bar"),
    ]

    def invoke(row):  # type: ignore[no-untyped-def]
        # Echo the expected — perfect run.
        return AgentInvocation(output=row.expected, latency_ms=10.0, cost_usd=0.0001)

    runner = EvalRunner(invoke_fn=invoke, scorers="exact_match")
    report = runner.run_sync(rows, agent_id="agent-test", dataset_path="memory:")
    assert report.total == 2
    assert report.passed == 2
    assert report.failed == 0
    assert report.errored == 0
    assert report.accuracy == 1.0
    assert report.total_cost_usd == pytest.approx(0.0002)
    # Latency was supplied explicitly → no auto-stamp.
    assert all(r.invocation is not None and r.invocation.latency_ms == 10.0 for r in report.rows)


def test_runner_async_invoke_fn_works() -> None:
    rows = [_row("a", expected="a"), _row("b", expected="b")]

    async def invoke(row):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0)
        return AgentInvocation(output=row.expected)

    runner = EvalRunner(invoke_fn=invoke, scorers="exact_match")
    report = runner.run_sync(rows, agent_id="async-agent")
    assert report.passed == 2
    # Latency should have been auto-stamped because invoke_fn didn't set it.
    for r in report.rows:
        assert r.invocation is not None
        assert r.invocation.latency_ms is not None
        assert r.invocation.latency_ms >= 0.0


def test_runner_invoke_failure_captured_per_row() -> None:
    rows = [_row("ok", expected="x"), _row("boom", expected="x")]

    def invoke(row):  # type: ignore[no-untyped-def]
        if row.input == "boom":
            raise RuntimeError("simulated transport failure")
        return AgentInvocation(output="x")

    runner = EvalRunner(invoke_fn=invoke, scorers="exact_match")
    report = runner.run_sync(rows, agent_id="agent")
    assert report.passed == 1
    assert report.errored == 1
    # The errored row has its error message captured but no scores.
    errored = [r for r in report.rows if r.error is not None][0]
    assert "simulated transport failure" in errored.error  # type: ignore[arg-type]
    assert errored.scores == []
    assert errored.invocation is None


def test_runner_scorer_exception_marks_row_failed_without_crashing() -> None:
    rows = [_row("x", expected="y")]

    class ExplodingScorer:
        name = "explode"

        def score(self, **_: object) -> ScorerResult:
            raise ValueError("scorer bug")

    registry = ScorerRegistry(autodiscover=False)
    registry.register(ExplodingScorer())

    def invoke(row):  # type: ignore[no-untyped-def]
        return AgentInvocation(output="anything")

    runner = EvalRunner(
        invoke_fn=invoke,
        scorers="explode",
        registry=registry,
    )
    report = runner.run_sync(rows, agent_id="agent")
    assert report.failed == 1
    assert report.errored == 0  # only invoke failures count as "errored"
    assert "scorer bug" in report.rows[0].scores[0].details


def test_runner_row_level_scorer_override() -> None:
    rows = [
        _row("x", expected=r"\d+", metadata={"scorer": "regex"}),
        _row("y", expected="exact", metadata={"scorer": "exact_match"}),
    ]

    def invoke(row):  # type: ignore[no-untyped-def]
        return AgentInvocation(output="42 then exact")

    runner = EvalRunner(invoke_fn=invoke, scorers="exact_match")
    report = runner.run_sync(rows, agent_id="agent")
    # First row uses regex (matches \d+) → pass.
    # Second row uses exact_match against "exact" → fail.
    assert report.rows[0].passed is True
    assert report.rows[1].passed is False


def test_runner_concurrency_cap_respected() -> None:
    in_flight = {"current": 0, "peak": 0}
    rows = [_row(f"r{i}", expected="x") for i in range(10)]

    async def invoke(row):  # type: ignore[no-untyped-def]
        in_flight["current"] += 1
        in_flight["peak"] = max(in_flight["peak"], in_flight["current"])
        await asyncio.sleep(0.01)
        in_flight["current"] -= 1
        return AgentInvocation(output="x")

    runner = EvalRunner(invoke_fn=invoke, scorers="exact_match", concurrency=3)
    runner.run_sync(rows, agent_id="agent")
    assert in_flight["peak"] <= 3


def test_runner_no_rows_yields_empty_report() -> None:
    def invoke(_row):  # type: ignore[no-untyped-def]
        return AgentInvocation(output="x")

    runner = EvalRunner(invoke_fn=invoke, scorers="exact_match")
    report = runner.run_sync([], agent_id="agent")
    assert report.total == 0
    assert report.accuracy == 0.0
    assert report.latency_p95_ms is None


def test_runner_requires_at_least_one_scorer() -> None:
    with pytest.raises(ValueError, match="at least one scorer"):
        EvalRunner(invoke_fn=lambda _r: AgentInvocation(output=""), scorers=[])


# ---------------------------------------------------------------------------
# Percentile helper
# ---------------------------------------------------------------------------


def test_percentile_empty_returns_none() -> None:
    assert _percentile([], 95.0) is None


def test_percentile_single_value() -> None:
    assert _percentile([42.0], 99.0) == 42.0


def test_percentile_interpolates() -> None:
    # values 1..10 → p95 between 9 and 10
    p = _percentile([float(i) for i in range(1, 11)], 95.0)
    assert p == pytest.approx(9.55, abs=0.01)


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def _build_report():  # type: ignore[no-untyped-def]
    rows = [
        _row("hello", expected="world", metadata={"id": "row-a"}),
        _row("foo", expected="bar", metadata={"id": "row-b"}),
    ]

    def invoke(row):  # type: ignore[no-untyped-def]
        return AgentInvocation(
            output=row.expected if row.row_id == "row-a" else "WRONG",
            latency_ms=42.5,
            cost_usd=0.001,
            session_id=f"sess-{row.row_id}",
        )

    return EvalRunner(invoke_fn=invoke, scorers="exact_match").run_sync(
        rows,
        agent_id="agt-123",
        dataset_path="/tmp/golden.jsonl",
    )


def test_to_markdown_includes_summary_and_rows() -> None:
    report = _build_report()
    md = to_markdown(report)
    assert "# Eval Report — agent `agt-123`" in md
    assert "| Total rows | 2 |" in md
    assert "| Passed | 1 |" in md
    assert "row-a" in md
    assert "row-b" in md
    # Markdown escape of pipes — output never breaks the row table.
    assert "\n| " in md


def test_to_markdown_lists_errors_section_when_present() -> None:
    rows = [_row("x", expected="y")]

    def invoke(_row):  # type: ignore[no-untyped-def]
        raise RuntimeError("kapow")

    report = EvalRunner(invoke_fn=invoke, scorers="exact_match").run_sync(
        rows, agent_id="a"
    )
    md = to_markdown(report)
    assert "## Errors" in md
    assert "kapow" in md


def test_write_markdown_path(tmp_path):  # type: ignore[no-untyped-def]
    report = _build_report()
    target = tmp_path / "report.md"
    write_markdown(report, target)
    assert target.read_text().startswith("# Eval Report")


def test_write_markdown_to_stream() -> None:
    report = _build_report()
    buf = StringIO()
    write_markdown(report, buf)
    assert "# Eval Report" in buf.getvalue()


def test_to_json_roundtrip_preserves_essentials() -> None:
    report = _build_report()
    payload = to_json(report)
    serialised = json.dumps(payload, default=str)
    reparsed = json.loads(serialised)
    assert reparsed["agent_id"] == "agt-123"
    assert reparsed["summary"]["total"] == 2
    assert reparsed["summary"]["passed"] == 1
    assert reparsed["rows"][0]["row_id"] == "row-a"
    assert reparsed["rows"][0]["passed"] is True
    assert reparsed["rows"][0]["invocation"]["session_id"] == "sess-row-a"


def test_write_json_path(tmp_path):  # type: ignore[no-untyped-def]
    report = _build_report()
    target = tmp_path / "report.json"
    write_json(report, target)
    payload = json.loads(target.read_text())
    assert payload["summary"]["passed"] == 1
