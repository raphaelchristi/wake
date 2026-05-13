"""wake-test-conformance — verify Wake HarnessAdapter implementations.

Usage
-----

Standalone::

    from wake_test_conformance import run_conformance
    report = await run_conformance(my_adapter)
    assert report.passed, report.summary()

Pytest fixture::

    import pytest
    from wake_test_conformance import run_conformance

    @pytest.mark.asyncio
    async def test_conformance():
        adapter = MyAdapter()
        report = await run_conformance(adapter)
        assert report.passed, report.summary()

The suite is a v0.1.0 minimal viable conformance check. Adapters that
pass are considered Wake-compatible at the v0.1 spec level. Adapters
that fail get specific, actionable error messages per scenario.
"""

from wake_test_conformance.result import ConformanceReport, ScenarioResult
from wake_test_conformance.runner import run_conformance, run_scenario
from wake_test_conformance.scenarios import SCENARIOS

__all__ = [
    "ConformanceReport",
    "ScenarioResult",
    "SCENARIOS",
    "run_conformance",
    "run_scenario",
]

__version__ = "0.1.0"
