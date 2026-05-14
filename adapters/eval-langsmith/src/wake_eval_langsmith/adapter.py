"""LangSmith REST adapter — pull datasets, push run feedback.

We deliberately speak the LangSmith REST API directly (via ``httpx``)
rather than depending on the ``langsmith`` SDK. Two reasons:

1. The SDK pulls in heavyweight transitive dependencies that are not
   needed for our narrow read/write surface (dataset list, examples
   list, run create, feedback create).
2. The adapter doubles as documentation: anyone reading this file can
   see exactly which endpoints we call, which makes audit + air-gapped
   self-hosted LangSmith deployments easy to support.

The REST shapes we use are documented at
``https://api.smith.langchain.com/redoc`` — they are stable since
LangSmith ``v0.1``.

Authentication
--------------

The adapter accepts an ``api_key`` argument or falls back to the
``LANGSMITH_API_KEY`` environment variable. The ``endpoint`` defaults
to ``https://api.smith.langchain.com`` and can be overridden for
self-hosted installs via ``LANGSMITH_ENDPOINT``.

Testing
-------

The unit tests inject a mock ``httpx.Client`` so no real network calls
happen. The adapter never holds onto the client across method calls —
each method opens, uses, and closes — so passing a context-managed
mock is straightforward.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from wake.eval.dataset import DatasetRow, rows_from_objects
from wake.eval.runner import EvalReport, RowReport


# ---------------------------------------------------------------------------
# Errors + value objects
# ---------------------------------------------------------------------------


class LangSmithError(RuntimeError):
    """Raised when the LangSmith REST API returns a non-2xx response.

    We attach ``status_code`` and ``url`` so callers can decide whether
    to retry (5xx + 429) or surface to a human (4xx).
    """

    def __init__(self, message: str, *, status_code: int | None = None, url: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.url = url


@dataclass(frozen=True)
class LangSmithExample:
    """One row of a LangSmith dataset, as returned by the REST API.

    LangSmith stores ``inputs`` and ``outputs`` as opaque dicts. We
    keep the raw payload so adapters can round-trip provider-specific
    fields without us teaching the schema about each one.
    """

    id: str
    dataset_id: str
    inputs: dict[str, Any]
    outputs: dict[str, Any] | None
    metadata: dict[str, Any]
    created_at: str | None = None

    def to_wake_row(self) -> dict[str, Any]:
        """Convert to a Wake dataset row dict (compatible with
        :func:`wake.eval.dataset.parse_row`).

        Heuristics:

        * ``inputs`` with a single key collapses to that value (so
          ``{"text": "hi"}`` becomes ``"hi"``); LangSmith datasets
          commonly use that shape.
        * ``outputs`` is treated as the ``expected`` payload. Same
          single-key collapse.
        * The example ``id`` becomes the row ``metadata.id``, so
          push-back lines up rows with their LangSmith examples.
        """
        return {
            "input": _maybe_collapse(self.inputs),
            "expected": _maybe_collapse(self.outputs) if self.outputs else None,
            "metadata": {
                "id": self.id,
                "langsmith_dataset_id": self.dataset_id,
                "langsmith_created_at": self.created_at,
                **self.metadata,
            },
        }


def _maybe_collapse(d: dict[str, Any] | None) -> Any:
    """Return the single value of a 1-key dict, else the dict itself."""
    if not d:
        return d
    if len(d) == 1:
        return next(iter(d.values()))
    return d


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


DEFAULT_ENDPOINT = "https://api.smith.langchain.com"


class LangSmithAdapter:
    """Pull datasets + push runs to LangSmith.

    Parameters
    ----------
    api_key
        LangSmith API key. Defaults to ``$LANGSMITH_API_KEY``.
    endpoint
        Base URL of the LangSmith API. Defaults to
        ``$LANGSMITH_ENDPOINT`` or the public hosted endpoint.
    project
        Project name to attach pushed runs to. Optional — when
        omitted, LangSmith uses the workspace default.
    http_client
        Optional ``httpx.Client`` (used by tests to mock the API).
        When ``None`` a client is created per method call.
    timeout
        Per-request timeout in seconds.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        endpoint: str | None = None,
        project: str | None = None,
        http_client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("LANGSMITH_API_KEY")
        if not self._api_key:
            raise LangSmithError(
                "LangSmith API key missing — pass api_key= or set LANGSMITH_API_KEY"
            )
        self._endpoint = (endpoint or os.environ.get("LANGSMITH_ENDPOINT") or DEFAULT_ENDPOINT).rstrip("/")
        self._project = project or os.environ.get("LANGSMITH_PROJECT")
        self._client = http_client
        self._timeout = timeout

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key or "",
            "content-type": "application/json",
            "accept": "application/json",
            "user-agent": "wake-eval-langsmith/0.1.0",
        }

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self._endpoint}{path}"
        headers = {**self._headers(), **kwargs.pop("headers", {})}
        client = self._client
        owns = client is None
        if owns:
            client = httpx.Client(timeout=self._timeout)
        try:
            resp = client.request(method, url, headers=headers, **kwargs)  # type: ignore[union-attr]
        finally:
            if owns:
                client.close()  # type: ignore[union-attr]
        if resp.status_code >= 400:
            raise LangSmithError(
                f"LangSmith {method} {path} returned {resp.status_code}: "
                f"{resp.text[:200]}",
                status_code=resp.status_code,
                url=url,
            )
        if not resp.content:
            return {}
        return resp.json()

    # ------------------------------------------------------------------
    # Datasets — pull
    # ------------------------------------------------------------------

    def get_dataset(self, name: str) -> dict[str, Any]:
        """Look up a dataset by exact name.

        Returns the raw dataset object. Raises :class:`LangSmithError`
        with ``status_code=404`` if no dataset matches.
        """
        # LangSmith GET /datasets accepts ``name=`` (exact match) as a
        # query param and returns a list.
        result = self._request("GET", "/datasets", params={"name": name})
        items = result if isinstance(result, list) else result.get("items") or result.get("data") or []
        for entry in items:
            if entry.get("name") == name:
                return entry  # type: ignore[no-any-return]
        raise LangSmithError(
            f"dataset {name!r} not found",
            status_code=404,
            url=f"{self._endpoint}/datasets",
        )

    def list_examples(self, dataset_id: str, *, limit: int = 1000) -> list[LangSmithExample]:
        """Page through ``/examples`` for one dataset.

        Returns every example in a single list — LangSmith caps page
        size at 100 server-side, so we walk until the response is
        shorter than the page size (LangSmith does not return a
        ``next_offset`` token in v0.1).
        """
        out: list[LangSmithExample] = []
        offset = 0
        page = min(100, max(1, limit))
        while len(out) < limit:
            result = self._request(
                "GET",
                "/examples",
                params={"dataset": dataset_id, "limit": page, "offset": offset},
            )
            items = result if isinstance(result, list) else result.get("items") or []
            if not items:
                break
            for raw in items:
                if len(out) >= limit:
                    break
                out.append(
                    LangSmithExample(
                        id=str(raw.get("id") or raw.get("example_id") or ""),
                        dataset_id=str(raw.get("dataset_id") or dataset_id),
                        inputs=dict(raw.get("inputs") or {}),
                        outputs=(dict(raw["outputs"]) if isinstance(raw.get("outputs"), dict) else None),
                        metadata=dict(raw.get("metadata") or {}),
                        created_at=raw.get("created_at"),
                    )
                )
            if len(items) < page:
                break
            offset += len(items)
        return out

    def pull_dataset(self, name: str, *, limit: int = 1000) -> list[DatasetRow]:
        """Convenience: resolve dataset by name + return Wake rows.

        The returned rows are immediately usable by
        :class:`wake.eval.runner.EvalRunner`. Each row carries the
        LangSmith example ID in ``metadata.id`` so :meth:`push_results`
        can line them back up.
        """
        ds = self.get_dataset(name)
        examples = self.list_examples(str(ds["id"]), limit=limit)
        return rows_from_objects(
            [ex.to_wake_row() for ex in examples],
            source=f"langsmith://datasets/{name}",
        )

    # ------------------------------------------------------------------
    # Runs + feedback — push
    # ------------------------------------------------------------------

    def push_results(
        self,
        report: EvalReport,
        *,
        dataset_name: str | None = None,
        experiment_prefix: str = "wake-eval",
    ) -> dict[str, Any]:
        """Push an :class:`EvalReport` back as LangSmith runs + feedback.

        For each row we create a ``Run`` (kind="chain") plus one
        ``Feedback`` entry per scorer. Run IDs are deterministic via
        ``uuid5`` keyed on ``(report.agent_id, row.row_id)`` so re-push
        of the same suite updates rather than duplicates.

        Returns a small dict with counters for assertions in tests.
        """
        created_runs = 0
        created_feedback = 0
        errors: list[str] = []
        experiment_name = (
            f"{experiment_prefix}-{report.agent_id}-{int(report.started_at)}"
            if experiment_prefix
            else None
        )
        for row in report.rows:
            run_id = _run_uuid(report.agent_id, row.row_id)
            try:
                self._create_run(
                    run_id=run_id,
                    row=row,
                    dataset_name=dataset_name,
                    experiment_name=experiment_name,
                    agent_id=report.agent_id,
                )
                created_runs += 1
            except LangSmithError as exc:
                errors.append(f"{row.row_id}: create_run failed: {exc}")
                continue
            for scorer in row.scores:
                try:
                    self._create_feedback(run_id=run_id, scorer=scorer)
                    created_feedback += 1
                except LangSmithError as exc:
                    errors.append(f"{row.row_id}/{scorer.name}: feedback failed: {exc}")
        return {
            "created_runs": created_runs,
            "created_feedback": created_feedback,
            "errors": errors,
            "experiment_name": experiment_name,
        }

    def _create_run(
        self,
        *,
        run_id: str,
        row: RowReport,
        dataset_name: str | None,
        experiment_name: str | None,
        agent_id: str,
    ) -> None:
        invocation = row.invocation
        payload: dict[str, Any] = {
            "id": run_id,
            "name": experiment_name or f"wake-eval-{agent_id}",
            "run_type": "chain",
            "inputs": {"input": row.row.input},
            "outputs": (
                {"output": invocation.output if invocation else None}
                if invocation is not None
                else {}
            ),
            "start_time": _iso(row.row.metadata.get("start_time") or time.time()),
            "end_time": _iso(time.time()),
            "error": row.error,
            "extra": {
                "agent_id": agent_id,
                "row_id": row.row_id,
                "aggregate_score": row.aggregate_score,
                "passed": row.passed,
                "latency_ms": invocation.latency_ms if invocation else None,
                "cost_usd": invocation.cost_usd if invocation else None,
                "session_id": invocation.session_id if invocation else None,
                **{k: v for k, v in row.row.metadata.items() if k != "id"},
            },
        }
        if self._project:
            payload["session_name"] = self._project
        if dataset_name:
            payload["reference_example_id"] = row.row_id
        self._request("POST", "/runs", json=payload)

    def _create_feedback(self, *, run_id: str, scorer: Any) -> None:
        payload = {
            "id": str(uuid.uuid4()),
            "run_id": run_id,
            "key": scorer.name,
            "score": float(scorer.score),
            "value": "pass" if scorer.passed else "fail",
            "comment": (scorer.details or "")[:1024],
        }
        self._request("POST", "/feedback", json=payload)

    # ------------------------------------------------------------------
    # Misc / introspection
    # ------------------------------------------------------------------

    @property
    def endpoint(self) -> str:
        return self._endpoint

    @property
    def project(self) -> str | None:
        return self._project


def _run_uuid(agent_id: str, row_id: str) -> str:
    """Deterministic run ID keyed on (agent_id, row_id).

    Lets a CI loop re-push the same suite without creating duplicates.
    The namespace is a fixed UUIDv4 chosen once for this adapter.
    """
    ns = uuid.UUID("d6c1cf2a-7d68-4fab-bce7-7d1a2a4d0c91")
    return str(uuid.uuid5(ns, f"{agent_id}::{row_id}"))


def _iso(ts: float | str) -> str:
    """ISO-8601 (UTC, second precision) timestamp formatting.

    Accepts either an epoch float or a pre-formatted string (in which
    case we pass it through verbatim).
    """
    if isinstance(ts, str):
        return ts
    import datetime as _dt

    return _dt.datetime.fromtimestamp(float(ts), tz=_dt.timezone.utc).isoformat(timespec="seconds")


__all__ = [
    "LangSmithAdapter",
    "LangSmithError",
    "LangSmithExample",
]
