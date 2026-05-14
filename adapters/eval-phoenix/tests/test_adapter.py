"""Tests for wake-eval-phoenix adapter (mock-based)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from wake_eval_phoenix import PhoenixEvalAdapter, PhoenixDatasetRow


def test_adapter_construction() -> None:
    """Adapter accepts endpoint + optional api_key."""
    adapter = PhoenixEvalAdapter(endpoint="http://phoenix:6006")
    assert adapter.endpoint == "http://phoenix:6006"
    assert adapter.api_key is None

    adapter2 = PhoenixEvalAdapter(endpoint="...", api_key="secret")
    assert adapter2.api_key == "secret"


@pytest.mark.asyncio
async def test_pull_dataset_translates_examples() -> None:
    """pull_dataset converts Phoenix examples to PhoenixDatasetRow."""
    fake_example = MagicMock()
    fake_example.input = {"q": "hello"}
    fake_example.output = {"a": "world"}
    fake_example.metadata = {"tag": "v1"}
    fake_example.id = "ex-123"

    fake_ds = MagicMock()
    fake_ds.examples = [fake_example]

    fake_client = MagicMock()
    fake_client.get_dataset.return_value = fake_ds

    fake_module = MagicMock()
    fake_module.Client.return_value = fake_client

    with patch.dict("sys.modules", {"phoenix": fake_module}):
        adapter = PhoenixEvalAdapter(endpoint="http://test")
        rows = await adapter.pull_dataset("my-ds")

    assert len(rows) == 1
    row = rows[0]
    assert isinstance(row, PhoenixDatasetRow)
    assert row.input == {"q": "hello"}
    assert row.expected == {"a": "world"}
    assert row.metadata == {"tag": "v1"}
    assert row.row_id == "ex-123"


@pytest.mark.asyncio
async def test_pull_dataset_raises_when_phoenix_missing() -> None:
    """Without arize-phoenix-client installed, raise ImportError."""
    adapter = PhoenixEvalAdapter(endpoint="http://test")

    with patch.dict("sys.modules", {"phoenix": None}):
        with pytest.raises(ImportError):
            await adapter.pull_dataset("ds")


@pytest.mark.asyncio
async def test_push_results_creates_experiment() -> None:
    """push_results forwards to phoenix client.create_experiment."""
    fake_experiment = MagicMock()
    fake_experiment.id = "exp-456"

    fake_client = MagicMock()
    fake_client.create_experiment.return_value = fake_experiment

    fake_module = MagicMock()
    fake_module.Client.return_value = fake_client

    with patch.dict("sys.modules", {"phoenix": fake_module}):
        adapter = PhoenixEvalAdapter(endpoint="http://test")
        exp_id = await adapter.push_results(
            "exp-2026",
            [{"row_id": "x", "score": 0.9}],
        )

    assert exp_id == "exp-456"
    fake_client.create_experiment.assert_called_once()


def test_dataclass_phoenix_dataset_row() -> None:
    """PhoenixDatasetRow holds input/expected/metadata/row_id."""
    row = PhoenixDatasetRow(input={"a": 1}, expected={"b": 2})
    assert row.input == {"a": 1}
    assert row.metadata == {}
    assert row.row_id is None
