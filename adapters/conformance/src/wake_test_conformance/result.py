"""Result data types for the conformance suite.

``ScenarioResult`` is the outcome of a single scenario; ``ConformanceReport``
aggregates results across the whole suite for a given adapter.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ScenarioResult(BaseModel):
    """Outcome of running a single conformance scenario."""

    model_config = ConfigDict(frozen=True)

    name: str
    """Canonical scenario name (matches the module name)."""

    passed: bool
    """True iff the scenario satisfied all assertions."""

    message: str = ""
    """Human-readable summary. For failures, must be actionable."""

    duration_ms: float = 0.0
    """Wall-clock duration of the scenario in milliseconds."""

    warnings: list[str] = Field(default_factory=list)
    """Non-fatal observations (e.g. adapter lacks an optional feature)."""

    def __str__(self) -> str:
        flag = "PASS" if self.passed else "FAIL"
        msg = f" — {self.message}" if self.message else ""
        warn = f" (warnings: {len(self.warnings)})" if self.warnings else ""
        return f"[{flag}] {self.name} ({self.duration_ms:.1f}ms){warn}{msg}"


class ConformanceReport(BaseModel):
    """Aggregate report across all scenarios run for a single adapter."""

    model_config = ConfigDict(frozen=True)

    adapter_name: str
    """Value of ``adapter.name`` at the time of the run."""

    adapter_version: str = ""
    """Value of ``adapter.version`` if exposed."""

    spec_version: str = "0.1.0"
    """HarnessAdapter spec version this run validates against."""

    results: list[ScenarioResult]
    """One ``ScenarioResult`` per scenario executed."""

    @property
    def passed(self) -> bool:
        """True iff every scenario passed."""
        return all(r.passed for r in self.results)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def total_duration_ms(self) -> float:
        return sum(r.duration_ms for r in self.results)

    def failures(self) -> list[ScenarioResult]:
        """Just the failed scenarios, in original order."""
        return [r for r in self.results if not r.passed]

    def summary(self) -> str:
        """Human-readable multi-line summary suitable for assertion messages."""
        header = (
            f"Wake HarnessAdapter conformance v{self.spec_version}\n"
            f"Adapter: {self.adapter_name}"
            + (f"@{self.adapter_version}" if self.adapter_version else "")
            + "\n"
            f"Result: {self.passed_count}/{self.total} passed"
            f" ({self.total_duration_ms:.1f}ms)\n"
        )
        rows = []
        for r in self.results:
            rows.append(str(r))
            for w in r.warnings:
                rows.append(f"     ! {w}")
        return header + "\n".join(rows)
