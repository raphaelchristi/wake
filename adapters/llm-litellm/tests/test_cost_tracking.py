"""Tests for the cost-tracking callback wiring."""

from __future__ import annotations

import sys
from datetime import datetime
from types import ModuleType, SimpleNamespace

import pytest

from wake_llm_litellm.cost_tracking import (
    CostMetadata,
    CostTracker,
    get_tracker,
    install_litellm_callback,
)


def test_tracker_records_and_totals() -> None:
    tr = CostTracker()
    tr.record(CostMetadata(
        model="anthropic/claude-opus-4-7",
        cost_usd=0.01,
        input_tokens=100,
        output_tokens=50,
        timestamp=datetime.utcnow(),
        session_id="sess_1",
    ))
    tr.record(CostMetadata(
        model="openai/gpt-4o",
        cost_usd=0.005,
        input_tokens=200,
        output_tokens=20,
        timestamp=datetime.utcnow(),
        session_id="sess_1",
    ))
    tr.record(CostMetadata(
        model="ollama/qwen",
        cost_usd=0.0,
        input_tokens=10,
        output_tokens=5,
        timestamp=datetime.utcnow(),
        session_id="sess_2",
    ))

    assert tr.total_usd() == pytest.approx(0.015)
    assert tr.session_total_usd("sess_1") == pytest.approx(0.015)
    assert tr.session_total_usd("sess_2") == 0.0
    assert tr.session_total_usd("unknown") == 0.0


def test_tracker_reset() -> None:
    tr = CostTracker()
    tr.record(CostMetadata("m", 1.0, 1, 1, datetime.utcnow(), None))
    assert tr.total_usd() == 1.0
    tr.reset()
    assert tr.total_usd() == 0.0
    assert tr.all() == []


def test_get_tracker_returns_global_singleton() -> None:
    a = get_tracker()
    b = get_tracker()
    assert a is b


def test_install_litellm_callback_no_op_without_litellm(monkeypatch: pytest.MonkeyPatch) -> None:
    """If litellm is missing entirely, install is a silent no-op."""
    # Force the import to fail.
    monkeypatch.setitem(sys.modules, "litellm", None)
    install_litellm_callback()
    # No exception ⇒ success.


def test_install_callback_pushes_to_litellm(monkeypatch: pytest.MonkeyPatch) -> None:
    """``install_litellm_callback`` appends our callback to
    ``litellm.success_callback`` exactly once even if called twice."""
    # Fake litellm module.
    fake = ModuleType("litellm")
    fake.success_callback = []  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "litellm", fake)

    tr = CostTracker()
    install_litellm_callback(tr)
    install_litellm_callback(tr)
    assert len(fake.success_callback) == 1  # type: ignore[attr-defined]

    # Invoke the callback as litellm would.
    cb = fake.success_callback[0]  # type: ignore[attr-defined]
    response = SimpleNamespace(
        response_cost=0.0123,
        usage=SimpleNamespace(
            model_dump=lambda: {"prompt_tokens": 50, "completion_tokens": 10}
        ),
    )
    cb(
        {"model": "openai/gpt-4o", "metadata": {"session_id": "sess_99"}},
        response,
        datetime.utcnow(),
        datetime.utcnow(),
    )

    records = tr.all()
    assert len(records) == 1
    assert records[0].model == "openai/gpt-4o"
    assert records[0].cost_usd == pytest.approx(0.0123)
    assert records[0].session_id == "sess_99"
    assert records[0].input_tokens == 50
    assert records[0].output_tokens == 10


def test_callback_swallows_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    """A buggy ``completion_response`` must NOT crash the callback."""
    fake = ModuleType("litellm")
    fake.success_callback = []  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "litellm", fake)
    install_litellm_callback(CostTracker())

    cb = fake.success_callback[0]  # type: ignore[attr-defined]
    # Pass a response that will explode on access.
    bad = SimpleNamespace()  # no response_cost / usage
    cb({"model": "x"}, bad, None, None)  # must not raise
