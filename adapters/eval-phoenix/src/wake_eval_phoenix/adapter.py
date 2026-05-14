"""Arize Phoenix bridge for Wake eval framework.

Phoenix is a self-hostable observability + eval platform. This adapter
mirrors the wake-eval-langsmith pattern: pull datasets, push results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = structlog.get_logger(__name__)


@dataclass
class PhoenixDatasetRow:
    """Single row from a Phoenix dataset, normalized to wake.eval shape."""

    input: dict[str, Any]
    expected: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    row_id: str | None = None


@dataclass
class PhoenixEvalAdapter:
    """Pull/push bridge between Wake eval framework and Arize Phoenix.

    Parameters
    ----------
    endpoint
        Phoenix server URL (e.g. ``http://phoenix:6006``).
    api_key
        Optional API key for hosted Phoenix.
    """

    endpoint: str
    api_key: str | None = None

    async def pull_dataset(self, dataset_name: str) -> list[PhoenixDatasetRow]:
        """Pull a Phoenix dataset and convert to wake.eval format.

        Real implementation uses `arize-phoenix-client`; this stub
        documents the contract.
        """
        # Lazy import — Phoenix client is optional
        try:
            import phoenix as px  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover
            msg = (
                "arize-phoenix-client not installed. "
                "Install with `pip install wake-eval-phoenix[phoenix]`"
            )
            raise ImportError(msg) from exc

        client = px.Client(endpoint=self.endpoint, api_key=self.api_key)
        ds = client.get_dataset(name=dataset_name)
        rows: list[PhoenixDatasetRow] = []
        for example in ds.examples:
            rows.append(
                PhoenixDatasetRow(
                    input=example.input,
                    expected=example.output,
                    metadata=example.metadata or {},
                    row_id=str(example.id),
                )
            )
        logger.info(
            "phoenix.dataset_pulled",
            dataset=dataset_name,
            rows=len(rows),
        )
        return rows

    async def push_results(
        self,
        experiment_name: str,
        results: Iterable[dict[str, Any]],
    ) -> str:
        """Push eval results as a Phoenix experiment.

        Returns the Phoenix experiment ID.
        """
        try:
            import phoenix as px  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover
            msg = "arize-phoenix-client not installed"
            raise ImportError(msg) from exc

        client = px.Client(endpoint=self.endpoint, api_key=self.api_key)
        experiment = client.create_experiment(
            name=experiment_name,
            evaluations=list(results),
        )
        logger.info(
            "phoenix.experiment_created",
            experiment=experiment_name,
            id=experiment.id,
        )
        return str(experiment.id)


__all__ = ["PhoenixDatasetRow", "PhoenixEvalAdapter"]
