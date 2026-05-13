"""Conformance pass for the LangGraph adapter.

Drives the full ``wake-test-conformance`` suite against the default
adapter (entry-point factory output) and asserts the v0.1.0
acceptance threshold (≥8/10) is met. In practice the adapter passes
all 10 scenarios — but we keep the explicit threshold so version drift
is loud rather than silent.
"""

from __future__ import annotations

import pytest
from wake_adapter_langgraph import create
from wake_test_conformance import run_conformance


@pytest.mark.asyncio
async def test_conformance_default_adapter_meets_threshold() -> None:
    adapter = create()
    report = await run_conformance(adapter)

    assert report.passed_count >= 8, (
        f"adapter must pass at least 8/10 scenarios; got "
        f"{report.passed_count}/{report.total}.\n\n{report.summary()}"
    )


@pytest.mark.asyncio
async def test_conformance_full_pass() -> None:
    """Strict assertion: all 10 scenarios must pass.

    Documented in the README — if any scenario regresses, this test
    flips before the threshold guard above.
    """
    adapter = create()
    report = await run_conformance(adapter)
    if not report.passed:
        pytest.fail(report.summary())
