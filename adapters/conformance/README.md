# wake-test-conformance

> Conformance test suite for Wake `HarnessAdapter` implementations.

Any adapter that wants to claim Wake compatibility runs this suite and posts the result. Pass = your adapter satisfies the v0.1 spec. Fail = the report tells you exactly which scenario broke and why.

The suite is **deterministic and zero-network**. Adapters under test must be deterministic on their end too — supply a fake LLM client, or write the adapter against a recorded fixture. No real model calls happen during conformance.

## Install

```bash
pip install wake-test-conformance
```

For development inside the Wake monorepo:

```bash
pip install -e adapters/conformance
```

## Quick start — standalone

```python
import asyncio
from wake_test_conformance import run_conformance

from my_package import MyAdapter

async def main() -> None:
    adapter = MyAdapter(client=fake_client)
    report = await run_conformance(adapter)
    print(report.summary())
    assert report.passed

asyncio.run(main())
```

`run_conformance(adapter)` returns a `ConformanceReport`:

- `report.passed: bool` — true iff every scenario passed
- `report.results: list[ScenarioResult]` — one per scenario
- `report.passed_count` / `report.failed_count` / `report.total`
- `report.total_duration_ms`
- `report.failures()` — only the failing results
- `report.summary()` — multi-line human-readable string

Each `ScenarioResult` has:

- `name` — canonical scenario name (e.g. `"tool_use"`)
- `passed` — bool
- `message` — actionable explanation (always populated on failure)
- `duration_ms` — wall-clock duration
- `warnings` — non-fatal observations (e.g. "adapter does not support streaming")

## Quick start — pytest

`wake-test-conformance` ships only the runner and scenarios — wire it into your test suite the way you prefer.

```python
# adapters/my_adapter/tests/test_conformance.py
import pytest
from wake_test_conformance import run_conformance

from my_package import MyAdapter

@pytest.mark.asyncio
async def test_conformance() -> None:
    adapter = MyAdapter(client=fake_client)
    report = await run_conformance(adapter)
    assert report.passed, "\n" + report.summary()
```

To get one test per scenario (better failure granularity):

```python
import pytest
from wake_test_conformance import run_scenario
from wake_test_conformance.scenarios import SCENARIOS

from my_package import MyAdapter

@pytest.fixture
def adapter():
    return MyAdapter(client=fake_client)

@pytest.mark.parametrize("scenario_name", [n for n, _ in SCENARIOS])
@pytest.mark.asyncio
async def test_scenario(adapter, scenario_name: str) -> None:
    result = await run_scenario(adapter, scenario_name)
    assert result.passed, result.message
```

To run only a subset:

```python
report = await run_conformance(adapter, scenarios=["basic_step", "tool_use"])
```

## The 10 scenarios

Spec v0.1.0 covers the surface area an adapter must handle correctly. Each scenario is a single Python module under `wake_test_conformance.scenarios` and can be inspected directly.

| # | Scenario | What it verifies | Lenience |
|---|---|---|---|
| 1 | `basic_step` | Adapter responds to a `user.message` with `assistant.message` containing "ok" | strict |
| 2 | `tool_use` | Adapter emits `tool_use`, calls `tools.execute()`, emits matching `tool_result` and a final message | strict |
| 3 | `streaming` | Adapter emits >=1 `assistant.delta` before the final `assistant.message` | warns if adapter is non-streaming |
| 4 | `cancellation` | `step()` honors `asyncio.CancelledError` without leaking exceptions | passes with warning if adapter completes before cancel fires |
| 5 | `resume` | Calling `step()` twice on the same log doesn't duplicate output | strict |
| 6 | `parallel_tools` | Multiple `tool_use` events in one turn produce distinct ids and matching results | strict |
| 7 | `error_handling` | A failing tool result is incorporated, not panicked on | passes with warning if adapter never invokes the failing tool |
| 8 | `pause_turn` | Adapter emits `pause_turn` when conditions warrant it | warns if unsupported |
| 9 | `lifecycle` | `on_lifecycle` accepts all four canonical events without raising | strict |
| 10 | `idempotence` | Repeated `step()` calls do not re-use `tool_use_id` values | strict |

### What "lenience" means

- **strict** — any deviation fails the scenario.
- **warns** — the scenario passes but emits a `ScenarioResult.warnings` entry. Consumers can choose to treat warnings as failures by inspecting `result.warnings`.

### Why so few scenarios?

v0.1.0 is the minimum viable conformance check. Future versions will add scenarios for: artifact emission, multimodal inputs, MCP-server tools, vault redaction, long-running pause/resume, and concurrency invariants. Suggestions and bug reports welcome — open an issue in the Wake repo.

## What the suite assumes about your adapter

- It implements the `wake.adapters.HarnessAdapter` Protocol.
- It's deterministic (no real network calls during the run — use fakes/mocks).
- It does not require an external sandbox provisioner (sandbox handle is `None` in the test context).
- It calls tools EXCLUSIVELY via `tools.execute(name, input, tool_use_id=...)`.

## Architecture

```text
wake_test_conformance/
  result.py         ScenarioResult, ConformanceReport (pydantic models)
  harness.py        TestHarness: in-memory EventStore + ToolRegistry + SessionContext
  scenarios/
    _helpers.py     Shared utilities (timing wrapper, text extraction)
    basic_step.py   one module per scenario
    tool_use.py
    streaming.py
    cancellation.py
    resume.py
    parallel_tools.py
    error_handling.py
    pause_turn.py
    lifecycle.py
    idempotence.py
    __init__.py     declares the SCENARIOS list
  runner.py         run_conformance() + run_scenario() entry points
```

Adding a new scenario is one new module + one line added to `SCENARIOS`.

## License

Apache-2.0
