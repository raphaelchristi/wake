"""run_conformance — drives the full scenario suite against an adapter.

The runner is intentionally tiny: it just iterates `SCENARIOS`, calls
each, and collects results into a ``ConformanceReport``. Scenario
implementations carry their own timing and exception handling.
"""

from __future__ import annotations

from collections.abc import Iterable

from wake.adapters import HarnessAdapter

from wake_test_conformance.result import ConformanceReport, ScenarioResult
from wake_test_conformance.scenarios import SCENARIOS, ScenarioRun


def _adapter_meta(adapter: HarnessAdapter) -> tuple[str, str]:
    name = getattr(adapter, "name", adapter.__class__.__name__)
    version = getattr(adapter, "version", "")
    return name, version


def _select(names: Iterable[str] | None) -> list[tuple[str, ScenarioRun]]:
    if names is None:
        return list(SCENARIOS)
    wanted = set(names)
    unknown = wanted - {n for n, _ in SCENARIOS}
    if unknown:
        raise ValueError(
            f"unknown scenario(s): {sorted(unknown)}; "
            f"available: {sorted(n for n, _ in SCENARIOS)}"
        )
    return [(n, fn) for n, fn in SCENARIOS if n in wanted]


async def run_conformance(
    adapter: HarnessAdapter,
    *,
    scenarios: Iterable[str] | None = None,
) -> ConformanceReport:
    """Run the conformance suite against ``adapter``.

    Parameters
    ----------
    adapter:
        Any ``HarnessAdapter`` implementation (Protocol-compatible).
    scenarios:
        Optional subset of scenario names. If omitted, all are run.

    Returns
    -------
    ConformanceReport
        Structured results. Inspect ``report.passed`` (bool) and
        ``report.summary()`` (human-readable text).
    """
    name, version = _adapter_meta(adapter)
    selected = _select(scenarios)
    results: list[ScenarioResult] = []
    for _, fn in selected:
        result = await fn(adapter)
        results.append(result)
    return ConformanceReport(
        adapter_name=name,
        adapter_version=version,
        results=results,
    )


async def run_scenario(
    adapter: HarnessAdapter,
    scenario_name: str,
) -> ScenarioResult:
    """Convenience: run a single scenario by name and return its result."""
    for n, fn in SCENARIOS:
        if n == scenario_name:
            return await fn(adapter)
    raise ValueError(
        f"unknown scenario {scenario_name!r}; "
        f"available: {sorted(n for n, _ in SCENARIOS)}"
    )
