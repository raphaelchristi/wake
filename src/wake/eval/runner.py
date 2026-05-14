"""Eval runner — orchestrates dataset → agent invocations → scoring.

The runner is intentionally decoupled from how rows are submitted: it
takes an ``invoke_fn`` callable that maps a :class:`DatasetRow` to an
:class:`AgentInvocation` (containing the agent's output, latency, cost,
events). For real workflows that ``invoke_fn`` calls the Wake REST API
through ``wake.cli.client.WakeClient``; for unit tests it can be any
local callable.

Why this shape?

* The CLI doesn't need to depend on the SDK package (which is owned by
  the parallel ``dx-sdks`` slice and may not be installed). Going via
  ``WakeClient`` keeps eval CLI usable from a fresh checkout.
* LangSmith / Phoenix adapters also use the runner — they just feed
  pre-pulled rows in and consume the report at the end.
* Tests can run a tight loop with zero IO.

Concurrency: rows are dispatched with ``asyncio.gather`` bounded by
``concurrency`` (default 4). Failures are captured per-row and surfaced
in :class:`RowReport.error`, never bubble up — one bad row should not
abort the whole suite.
"""

from __future__ import annotations

import asyncio
import statistics
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from wake.eval.dataset import DatasetRow
from wake.eval.scorer import (
    Scorer,
    ScorerRegistry,
    ScorerResult,
    default_registry,
)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentInvocation:
    """Result of running one row through the target agent.

    ``output`` is whatever the agent ultimately produced — typically the
    last ``assistant.message`` text, but may be any JSON-serialisable
    object the scorer understands.

    ``latency_ms`` and ``cost_usd`` are wall-clock and provider cost.
    They're optional because not every transport surfaces them; the
    report aggregates only the ones present.

    ``events`` (optional) is the raw event log, useful for replay /
    debugging. The runner never inspects it; it just forwards it.
    """

    output: Any
    latency_ms: float | None = None
    cost_usd: float | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RowReport:
    """Scoring result for one dataset row."""

    row_id: str
    row: DatasetRow
    invocation: AgentInvocation | None
    scores: list[ScorerResult]
    error: str | None = None

    @property
    def passed(self) -> bool:
        if self.error is not None or not self.scores:
            return False
        return all(s.passed for s in self.scores)

    @property
    def aggregate_score(self) -> float:
        if not self.scores:
            return 0.0
        return statistics.fmean(s.score for s in self.scores)


@dataclass(frozen=True)
class EvalReport:
    """Suite-level aggregation."""

    agent_id: str
    dataset_path: str
    rows: list[RowReport]
    started_at: float
    finished_at: float
    metadata: dict[str, Any] = field(default_factory=dict)

    # ---- aggregates -----------------------------------------------------

    @property
    def total(self) -> int:
        return len(self.rows)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.rows if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.rows if not r.passed and r.error is None)

    @property
    def errored(self) -> int:
        return sum(1 for r in self.rows if r.error is not None)

    @property
    def accuracy(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def mean_score(self) -> float:
        if not self.rows:
            return 0.0
        return statistics.fmean(r.aggregate_score for r in self.rows)

    @property
    def latency_p95_ms(self) -> float | None:
        latencies = [
            r.invocation.latency_ms
            for r in self.rows
            if r.invocation is not None and r.invocation.latency_ms is not None
        ]
        return _percentile(latencies, 95.0)

    @property
    def latency_mean_ms(self) -> float | None:
        latencies = [
            r.invocation.latency_ms
            for r in self.rows
            if r.invocation is not None and r.invocation.latency_ms is not None
        ]
        return statistics.fmean(latencies) if latencies else None

    @property
    def total_cost_usd(self) -> float:
        costs = [
            r.invocation.cost_usd
            for r in self.rows
            if r.invocation is not None and r.invocation.cost_usd is not None
        ]
        return float(sum(costs))

    @property
    def duration_s(self) -> float:
        return max(0.0, self.finished_at - self.started_at)


# ---------------------------------------------------------------------------
# Invoke callable type
# ---------------------------------------------------------------------------


InvokeFn = Callable[[DatasetRow], "AgentInvocation | Awaitable[AgentInvocation]"]
"""Callable that runs the agent on one dataset row.

The signature is intentionally minimal — implementations capture
state (agent ID, server URL, auth) via closure.
"""


# ---------------------------------------------------------------------------
# Scorer plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScorerPlan:
    """Per-row scoring plan resolved by :class:`EvalRunner`.

    Each row may use one or more scorers; the runner picks the row's
    explicit ``metadata.scorer`` if present, otherwise the runner-wide
    default(s). ``kwargs`` come from ``metadata.scorer_args``.
    """

    name: str
    scorer: Scorer
    kwargs: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class EvalRunner:
    """Drive an :class:`AgentInvocation` over each dataset row + score.

    Parameters
    ----------
    invoke_fn
        Callable mapping :class:`DatasetRow` -> :class:`AgentInvocation`.
        Can be sync or async; both work transparently.
    scorers
        Default scorer name(s) used when a row does not specify its own
        in ``metadata.scorer``. Accepts a single string or list.
    scorer_args
        Default kwargs applied to every scorer invocation, merged with
        per-row overrides.
    concurrency
        Maximum number of in-flight invocations. Defaults to 4 — high
        enough for I/O parallelism, low enough not to swamp rate limits.
    registry
        Optional :class:`ScorerRegistry`. Defaults to the auto-
        discovered registry (built-ins + entry-point plugins).
    """

    def __init__(
        self,
        *,
        invoke_fn: InvokeFn,
        scorers: str | Iterable[str] = ("exact_match",),
        scorer_args: dict[str, Any] | None = None,
        concurrency: int = 4,
        registry: ScorerRegistry | None = None,
    ) -> None:
        self._invoke_fn = invoke_fn
        self._scorer_names: list[str] = (
            [scorers] if isinstance(scorers, str) else list(scorers)
        )
        if not self._scorer_names:
            raise ValueError("at least one scorer must be configured")
        self._default_scorer_args = dict(scorer_args or {})
        self._concurrency = max(1, int(concurrency))
        self._registry = registry or default_registry()

    # ------------------------------------------------------------------
    # Public entrypoint
    # ------------------------------------------------------------------

    async def run(
        self,
        rows: Iterable[DatasetRow],
        *,
        agent_id: str,
        dataset_path: str = "<memory>",
    ) -> EvalReport:
        rows_list = list(rows)
        sem = asyncio.Semaphore(self._concurrency)
        started_at = time.time()

        async def _process(row: DatasetRow) -> RowReport:
            async with sem:
                return await self._run_row(row)

        # `gather` preserves input order; we rely on that for stable reports.
        row_reports = await asyncio.gather(
            *[_process(r) for r in rows_list],
            return_exceptions=False,  # we catch inside _run_row
        )
        finished_at = time.time()
        return EvalReport(
            agent_id=agent_id,
            dataset_path=dataset_path,
            rows=list(row_reports),
            started_at=started_at,
            finished_at=finished_at,
        )

    def run_sync(
        self,
        rows: Iterable[DatasetRow],
        *,
        agent_id: str,
        dataset_path: str = "<memory>",
    ) -> EvalReport:
        """Sync entrypoint used by the CLI and tests."""
        return asyncio.run(self.run(rows, agent_id=agent_id, dataset_path=dataset_path))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_plan(self, row: DatasetRow) -> list[ScorerPlan]:
        names = [row.scorer] if row.scorer else self._scorer_names
        out: list[ScorerPlan] = []
        merged_kwargs = {**self._default_scorer_args, **row.scorer_args}
        for name in names:
            scorer = self._registry.get(name)
            out.append(ScorerPlan(name=name, scorer=scorer, kwargs=dict(merged_kwargs)))
        return out

    async def _invoke(self, row: DatasetRow) -> AgentInvocation:
        t0 = time.perf_counter()
        result = self._invoke_fn(row)
        if asyncio.iscoroutine(result):
            invocation = await result
        else:
            invocation = result  # type: ignore[assignment]
        # Stamp latency if the caller didn't.
        if invocation.latency_ms is None:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            invocation = AgentInvocation(
                output=invocation.output,
                latency_ms=elapsed_ms,
                cost_usd=invocation.cost_usd,
                events=list(invocation.events),
                session_id=invocation.session_id,
                metadata=dict(invocation.metadata),
            )
        return invocation

    async def _run_row(self, row: DatasetRow) -> RowReport:
        # 1. Invoke
        try:
            invocation = await self._invoke(row)
        except Exception as exc:  # noqa: BLE001 — capture per-row failure
            return RowReport(
                row_id=row.row_id,
                row=row,
                invocation=None,
                scores=[],
                error=f"invoke failed: {type(exc).__name__}: {exc}",
            )
        # 2. Score
        try:
            plans = self._resolve_plan(row)
        except KeyError as exc:
            return RowReport(
                row_id=row.row_id,
                row=row,
                invocation=invocation,
                scores=[],
                error=f"scorer resolution failed: {exc}",
            )
        scores: list[ScorerResult] = []
        for plan in plans:
            try:
                result = plan.scorer.score(
                    output=invocation.output,
                    expected=row.expected,
                    row=row,
                    **plan.kwargs,
                )
            except Exception as exc:  # noqa: BLE001
                result = ScorerResult(
                    name=plan.name,
                    score=0.0,
                    passed=False,
                    details=f"scorer raised {type(exc).__name__}: {exc}",
                )
            scores.append(result)
        return RowReport(
            row_id=row.row_id,
            row=row,
            invocation=invocation,
            scores=scores,
            error=None,
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _percentile(values: list[float], pct: float) -> float | None:
    """Compute a percentile without numpy.

    Uses linear interpolation, matching ``numpy.percentile``'s default.
    Returns ``None`` if ``values`` is empty.
    """
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    sv = sorted(values)
    k = (len(sv) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sv) - 1)
    if lo == hi:
        return float(sv[lo])
    frac = k - lo
    return float(sv[lo] + (sv[hi] - sv[lo]) * frac)


__all__ = [
    "AgentInvocation",
    "EvalReport",
    "EvalRunner",
    "InvokeFn",
    "RowReport",
    "ScorerPlan",
]
