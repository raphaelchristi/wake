# wake-adapter-crewai

> **Phase 2 STUB.** This package proves Wake's `HarnessAdapter` ABI is
> discoverable and plug-and-play. It does **not** yet run CrewAI
> `Crew`s. A real implementation lands in Phase 3
> ([phases/PHASE-3-spec-validation.md](../../phases/PHASE-3-spec-validation.md)).

A [Wake](https://github.com/raphaelchristi/wake) `HarnessAdapter`
that — eventually — will let any
[CrewAI](https://github.com/crewAIInc/crewAI) `Crew` run on top of
Wake's durable substrate (event log, sandbox, vault, lifecycle).

## What this stub does today

- Registers itself under the `wake.adapters` Python entry point as
  `crewai`, so `AdapterRegistry.discover()` finds it.
- Implements the `HarnessAdapter` Protocol (`name`, `version`,
  `compatibility`, `step()`, `on_lifecycle()`).
- `step()` emits a single canned `assistant.message` event with text
  `"stub from crewai"` — independent of input.
- `on_lifecycle()` is a no-op.

That's the entire feature set. **It is a wiring proof, not a framework
integration.**

## Install

From the Wake monorepo (editable, recommended while pre-alpha):

```bash
cd adapters/crewai
pip install -e .
```

From a release wheel (once published):

```bash
pip install wake-adapter-crewai
```

## Use

```python
from wake.adapters import AdapterRegistry

registry = AdapterRegistry()
registry.discover()  # reads the wake.adapters entry-point group

adapter = registry.get("crewai")
assert adapter.name == "crewai"
assert adapter.version == "0.1.0-stub"
```

Or with the Wake CLI (once your runtime is configured to allow stubs):

```bash
wake session create --agent my-agent --harness crewai
```

The runtime will route `step()` calls to this adapter and persist the
single emitted event — useful for end-to-end smoke tests of the
adapter dispatch path.

## Run the tests

```bash
cd adapters/crewai
pip install -e ".[dev]"
pytest -v
```

Five tests, all fast:

- package imports
- runtime `isinstance(adapter, HarnessAdapter)`
- entry point discovered by `AdapterRegistry`
- `step()` emits exactly one `assistant.message`
- `on_lifecycle()` is a no-op for every event

## Plan for the full implementation (Phase 3)

The Phase 3 adapter will:

1. Accept a ``crew_factory: Callable[[str], Crew]`` via the
   constructor — CrewAI `Crew`s are usually built per-task, parametrized
   by the user prompt.
2. On `step()`, read the latest `user.message`, hand it to
   `crew_factory`, and call `await crew.kickoff_async()`.
3. Wire CrewAI's agent/task callbacks (`step_callback`,
   `task_callback`) to emit Wake events: `assistant.thinking` for
   agent thoughts, `tool_use`/`tool_result` for tool execution.
4. Wrap CrewAI `BaseTool` so its `_run`/`_arun` calls route through
   `tools.execute(name, input, tool_use_id=...)` — never the underlying
   function directly.
5. Pass the full `wake-test-conformance` suite (10 scenarios).

Track the work in
[`phases/PHASE-3-spec-validation.md`](../../phases/PHASE-3-spec-validation.md).

## License

Apache-2.0, same as Wake core.
