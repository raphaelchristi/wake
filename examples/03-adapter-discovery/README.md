# 03 — Adapter Discovery

Demonstrates that Wake's `HarnessAdapter` ABI is **plug-and-play**.
After installing the two stub adapter packages (`wake-adapter-langgraph`
and `wake-adapter-crewai`), `AdapterRegistry.discover()` picks them up
automatically via the `wake.adapters` Python entry-point group — no
edit to the Wake runtime required.

This is the killer ergonomics demo: **third parties can ship their own
adapter on PyPI, and Wake will find it.**

## What it does

1. Installs the two stub adapter packages in editable mode
   (`adapters/langgraph` and `adapters/crewai`).
2. Builds an `AdapterRegistry` and calls `.discover()`.
3. Prints every adapter found, including `name`, `version`,
   `compatibility`.
4. Calls `step()` against each stub and prints the emitted
   `assistant.message` payload — proving the two adapters produce
   distinct, framework-tagged output (`stub from langgraph` vs
   `stub from crewai`).

Total runtime: <10 seconds (no LLM calls, no server boot).

> The Phase 1 Wake CLI does not yet expose `wake adapter list` — that
> command is on the Phase 3 roadmap. Until then, the example uses the
> `AdapterRegistry` Python API directly (see `run.sh` for the inline
> Python that prints the same info).

## Prerequisites

- `pip install -e ".[dev]"` from the repo root (one-time wake install).
- A clean virtualenv recommended.

## Run

```bash
cd examples/03-adapter-discovery
./run.sh
```

Expected output (abridged):

```
[wake] installing stub adapters...
[wake] discovered adapters:
  crewai@0.1.0-stub      compat=wake-harness-adapter@^0.1
  langgraph@0.1.0-stub   compat=wake-harness-adapter@^0.1
[wake] calling step() against each adapter...
  langgraph → assistant.message: 'stub from langgraph'
  crewai    → assistant.message: 'stub from crewai'
[wake] done
```

## Why this matters

The Wake runtime never imports `wake_adapter_langgraph` or
`wake_adapter_crewai`. It doesn't know they exist at compile time. The
only contract is the entry-point group `wake.adapters` and the
`HarnessAdapter` Protocol. Any package on PyPI that publishes a
matching entry point becomes available to every Wake installation that
has it `pip install`-ed — exactly the same shape as `pytest` plugins.

The corollary: adding a third framework adapter (Pydantic AI, AutoGen,
your in-house DSL) is **a new package**, not a Wake fork.

## Inspecting the registry interactively

After running the script, the venv still has both adapters installed.
Try:

```python
from wake.adapters import AdapterRegistry

reg = AdapterRegistry()
reg.discover()
print(reg.names())
# ['crewai', 'langgraph']

adapter = reg.get("langgraph")
print(adapter.name, adapter.version, adapter.compatibility)
```

When the production Claude SDK adapter (`wake-adapter-claude-sdk`)
lands in Phase 2, it will appear in the same list — alongside the
stubs — with no extra configuration.
