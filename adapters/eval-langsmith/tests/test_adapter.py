"""Unit tests for ``wake_eval_langsmith.LangSmithAdapter``.

No real network calls — every test injects an ``httpx.MockTransport``
that pretends to be LangSmith. We exercise both happy paths and the
error mapping that produces :class:`LangSmithError`.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
import pytest

from wake.eval.dataset import parse_row
from wake.eval.runner import AgentInvocation, EvalRunner

from wake_eval_langsmith import LangSmithAdapter, LangSmithError, LangSmithExample
from wake_eval_langsmith.adapter import _maybe_collapse, _run_uuid


# ---------------------------------------------------------------------------
# Mock transport plumbing
# ---------------------------------------------------------------------------


def _build_client(routes: dict[str, Any]) -> httpx.Client:
    """Create an httpx.Client whose responses come from a routing dict.

    ``routes`` maps ``(method, path)`` -> either:

    * a JSON-serialisable payload (returned with 200 OK), or
    * a callable ``request -> httpx.Response`` for full control.
    """

    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        key = (request.method, request.url.path)
        if key not in routes:
            return httpx.Response(404, json={"detail": f"no mock for {key}"})
        spec = routes[key]
        if callable(spec):
            return spec(request)
        return httpx.Response(200, json=spec)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="http://langsmith.test")
    client._captured = captured  # type: ignore[attr-defined]  # debug aid
    return client


# ---------------------------------------------------------------------------
# Auth + endpoint
# ---------------------------------------------------------------------------


def test_adapter_requires_api_key(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    with pytest.raises(LangSmithError, match="API key missing"):
        LangSmithAdapter()


def test_adapter_uses_env_api_key(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-test")
    adapter = LangSmithAdapter()
    assert adapter._api_key == "ls-test"  # type: ignore[attr-defined]


def test_adapter_uses_env_endpoint(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-x")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "http://self-hosted/")
    adapter = LangSmithAdapter()
    assert adapter.endpoint == "http://self-hosted"


# ---------------------------------------------------------------------------
# get_dataset / list_examples / pull_dataset
# ---------------------------------------------------------------------------


def test_get_dataset_returns_matching_entry() -> None:
    client = _build_client(
        {
            ("GET", "/datasets"): {
                "items": [
                    {"id": "ds-1", "name": "other"},
                    {"id": "ds-2", "name": "golden"},
                ]
            }
        }
    )
    adapter = LangSmithAdapter(api_key="ls-test", http_client=client)
    result = adapter.get_dataset("golden")
    assert result["id"] == "ds-2"


def test_get_dataset_raises_when_not_found() -> None:
    client = _build_client({("GET", "/datasets"): []})
    adapter = LangSmithAdapter(api_key="ls-test", http_client=client)
    with pytest.raises(LangSmithError) as info:
        adapter.get_dataset("missing")
    assert info.value.status_code == 404


def test_list_examples_pages_until_short_response() -> None:
    page1 = [{"id": f"ex-{i}", "dataset_id": "ds-1", "inputs": {"text": f"i{i}"}} for i in range(100)]
    page2 = [{"id": "ex-100", "dataset_id": "ds-1", "inputs": {"text": "last"}}]
    state = {"calls": 0}

    def examples_handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] == 1:
            return httpx.Response(200, json={"items": page1})
        return httpx.Response(200, json={"items": page2})

    client = _build_client({("GET", "/examples"): examples_handler})
    adapter = LangSmithAdapter(api_key="ls-test", http_client=client)
    examples = adapter.list_examples("ds-1")
    assert len(examples) == 101
    assert state["calls"] == 2  # stopped because page2 was shorter than page size


def test_list_examples_respects_limit() -> None:
    client = _build_client(
        {
            ("GET", "/examples"): {
                "items": [
                    {"id": f"ex-{i}", "dataset_id": "ds-1", "inputs": {"text": f"i{i}"}}
                    for i in range(50)
                ]
            }
        }
    )
    adapter = LangSmithAdapter(api_key="ls-test", http_client=client)
    examples = adapter.list_examples("ds-1", limit=10)
    assert len(examples) == 10


def test_pull_dataset_returns_wake_rows() -> None:
    client = _build_client(
        {
            ("GET", "/datasets"): [{"id": "ds-x", "name": "golden"}],
            ("GET", "/examples"): {
                "items": [
                    {
                        "id": "ex-1",
                        "dataset_id": "ds-x",
                        "inputs": {"text": "what is 2+2"},
                        "outputs": {"answer": "4"},
                        "metadata": {"tags": ["math"]},
                    },
                ]
            },
        }
    )
    adapter = LangSmithAdapter(api_key="ls-test", http_client=client)
    rows = adapter.pull_dataset("golden")
    assert len(rows) == 1
    row = rows[0]
    assert row.input == "what is 2+2"
    assert row.expected == "4"
    assert row.metadata["id"] == "ex-1"
    # tags preserved
    assert row.tags == ["math"]


# ---------------------------------------------------------------------------
# Example → wake_row collapse helpers
# ---------------------------------------------------------------------------


def test_maybe_collapse_single_key() -> None:
    assert _maybe_collapse({"text": "hi"}) == "hi"


def test_maybe_collapse_multi_key_returns_dict() -> None:
    assert _maybe_collapse({"text": "hi", "lang": "pt"}) == {"text": "hi", "lang": "pt"}


def test_maybe_collapse_none_passthrough() -> None:
    assert _maybe_collapse(None) is None


def test_example_to_wake_row_keeps_metadata() -> None:
    ex = LangSmithExample(
        id="ex-1",
        dataset_id="ds-1",
        inputs={"q": "hi"},
        outputs={"a": "hello"},
        metadata={"tags": ["smoke"], "scorer": "regex"},
        created_at="2024-01-01T00:00:00Z",
    )
    row = ex.to_wake_row()
    assert row["input"] == "hi"
    assert row["expected"] == "hello"
    assert row["metadata"]["id"] == "ex-1"
    assert row["metadata"]["scorer"] == "regex"
    assert row["metadata"]["tags"] == ["smoke"]
    assert row["metadata"]["langsmith_dataset_id"] == "ds-1"


# ---------------------------------------------------------------------------
# push_results
# ---------------------------------------------------------------------------


def _make_report():  # type: ignore[no-untyped-def]
    """Run a tiny in-memory eval to produce a real EvalReport."""
    rows = [
        parse_row(
            {"input": "hi", "expected": "hi", "metadata": {"id": "ex-1"}}, line_no=1
        ),
        parse_row(
            {"input": "bye", "expected": "bye", "metadata": {"id": "ex-2"}}, line_no=2
        ),
    ]

    def invoke(row):  # type: ignore[no-untyped-def]
        return AgentInvocation(output=row.expected, latency_ms=42.0, cost_usd=0.001)

    runner = EvalRunner(invoke_fn=invoke, scorers="exact_match")
    return runner.run_sync(rows, agent_id="agt-1", dataset_path="memory:")


def test_push_results_creates_runs_and_feedback() -> None:
    posts: list[dict[str, Any]] = []

    def post_runs(request: httpx.Request) -> httpx.Response:
        posts.append({"path": request.url.path, "body": json.loads(request.content)})
        return httpx.Response(202, json={})

    client = _build_client(
        {
            ("POST", "/runs"): post_runs,
            ("POST", "/feedback"): post_runs,
        }
    )
    adapter = LangSmithAdapter(api_key="ls-test", http_client=client, project="prj")
    report = _make_report()
    result = adapter.push_results(report, dataset_name="golden")
    # 2 rows → 2 runs + 2 feedback entries (one scorer each).
    assert result["created_runs"] == 2
    assert result["created_feedback"] == 2
    assert result["errors"] == []
    run_paths = [p["path"] for p in posts if p["path"] == "/runs"]
    fb_paths = [p["path"] for p in posts if p["path"] == "/feedback"]
    assert len(run_paths) == 2
    assert len(fb_paths) == 2
    # Each run carries the deterministic ID.
    run_bodies = [p["body"] for p in posts if p["path"] == "/runs"]
    assert {b["id"] for b in run_bodies} == {_run_uuid("agt-1", "ex-1"), _run_uuid("agt-1", "ex-2")}
    # Project name propagated as session_name.
    assert all(b.get("session_name") == "prj" for b in run_bodies)


def test_push_results_collects_errors_without_crashing() -> None:
    state = {"runs": 0}

    def post_runs(request: httpx.Request) -> httpx.Response:
        state["runs"] += 1
        if state["runs"] == 1:
            return httpx.Response(200, json={})
        return httpx.Response(500, text="boom")

    client = _build_client(
        {
            ("POST", "/runs"): post_runs,
            ("POST", "/feedback"): lambda req: httpx.Response(200, json={}),
        }
    )
    adapter = LangSmithAdapter(api_key="ls-test", http_client=client)
    result = adapter.push_results(_make_report(), dataset_name="golden")
    # Only the first row produced a run; the second errored. Feedback
    # is only attempted for successful runs.
    assert result["created_runs"] == 1
    assert result["created_feedback"] == 1
    assert any("create_run failed" in e for e in result["errors"])


def test_push_results_feedback_error_is_captured() -> None:
    state = {"fb": 0}

    def post_feedback(request: httpx.Request) -> httpx.Response:
        state["fb"] += 1
        if state["fb"] == 2:
            return httpx.Response(429, text="rate limited")
        return httpx.Response(200, json={})

    client = _build_client(
        {
            ("POST", "/runs"): lambda req: httpx.Response(200, json={}),
            ("POST", "/feedback"): post_feedback,
        }
    )
    adapter = LangSmithAdapter(api_key="ls-test", http_client=client)
    result = adapter.push_results(_make_report(), dataset_name="golden")
    assert result["created_runs"] == 2
    assert result["created_feedback"] == 1
    assert len(result["errors"]) == 1
    assert "feedback failed" in result["errors"][0]


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


def test_error_includes_status_code_and_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="bad api key")

    client = _build_client({("GET", "/datasets"): handler})
    adapter = LangSmithAdapter(api_key="ls-test", http_client=client)
    with pytest.raises(LangSmithError) as info:
        adapter.get_dataset("any")
    assert info.value.status_code == 401
    assert "/datasets" in (info.value.url or "")


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_run_uuid_is_stable() -> None:
    a = _run_uuid("agt-1", "row-1")
    b = _run_uuid("agt-1", "row-1")
    c = _run_uuid("agt-1", "row-2")
    assert a == b
    assert a != c
