# wake-adapter-crewai

> **Phase 3.** Real CrewAI integration on Wake's HarnessAdapter ABI
> v0.1.0. Passes the full `wake-test-conformance` suite (10/10).

A [Wake](https://github.com/raphaelchristi/wake) `HarnessAdapter` that
lets any [CrewAI](https://github.com/crewAIInc/crewAI) `Crew` run on top
of Wake's durable substrate (event log, sandbox, vault, lifecycle).
Bring your Crew, plug it in, get persistence, replay, audit, and
permission-aware tools for free.

## What it does

- Accepts a `crew_factory: Callable[[str], Crew]` (CrewAI Crews are
  cheap to build, expensive to run — the factory pattern matches
  CrewAI's idiom of parameterizing Task descriptions by user prompt).
- On each `step()`, reads the latest `user.message`, asks the factory
  for a fresh Crew, and drives it via `crew.kickoff()` in a worker
  thread.
- Wraps every Wake tool as a CrewAI `BaseTool` whose `_run` funnels
  through `tools.execute(name, input, tool_use_id=...)` — preserving
  permission policy, audit logging, and idempotent retry.
- Hooks CrewAI's `step_callback` and `task_callback` to emit Wake events
  in real time:

  | CrewAI signal              | Wake event                                 |
  | -------------------------- | ------------------------------------------ |
  | `AgentAction.thought`      | `assistant.thinking` (phase=`action`)      |
  | `AgentFinish.thought`      | `assistant.thinking` (phase=`finish`)      |
  | Tool `_run` invocation     | `tool_use` + `tool_result` (correlated id) |
  | `TaskOutput.raw`           | `assistant.thinking` (phase=`task`)        |
  | Final `CrewOutput.raw`     | `assistant.message`                        |

- Idempotent on `resume`: if an `assistant.message` already follows the
  latest `user.message`, `step()` exits without re-running the crew.

## Install

From the Wake monorepo (editable):

```bash
cd adapters/crewai
pip install -e ".[dev]"
```

From PyPI (once published):

```bash
pip install wake-adapter-crewai
```

## Use

### Programmatic

```python
from crewai import Agent, Crew, Task, LLM
from wake_adapter_crewai import CrewAIAdapter

def build_crew(user_input: str) -> Crew:
    llm = LLM(model="gpt-4o-mini")
    researcher = Agent(
        role="researcher",
        goal=user_input,
        backstory="finds reliable information.",
        llm=llm,
    )
    task = Task(
        description=user_input,
        expected_output="A short, factual answer.",
        agent=researcher,
    )
    return Crew(agents=[researcher], tasks=[task])

adapter = CrewAIAdapter(build_crew)
# Hand `adapter` to your Wake runtime as the harness.
```

### Via entry-point discovery

The package registers itself as `crewai` under the `wake.adapters`
group:

```python
from wake.adapters import AdapterRegistry

registry = AdapterRegistry()
registry.discover()
adapter = registry.get("crewai")
```

The entry-point factory wires a trivial echo crew. Real callers
construct `CrewAIAdapter(crew_factory)` directly with their own
factory.

## Multi-agent example (researcher → writer)

CrewAI's value is multi-agent orchestration. The adapter surfaces each
agent's contribution through the event log:

```python
def build(user_input: str) -> Crew:
    researcher = Agent(role="researcher", goal="gather facts", ...)
    writer = Agent(role="writer", goal="rewrite prose", ...)
    t1 = Task(description=f"Research: {user_input}", agent=researcher,
              expected_output="key facts")
    t2 = Task(description="Turn facts into a blog post.", agent=writer,
              context=[t1], expected_output="prose")
    return Crew(agents=[researcher, writer], tasks=[t1, t2])

adapter = CrewAIAdapter(build)
```

The event log will contain `assistant.thinking` events with
`phase="task"` for each task, attributed to the correct agent role,
then a final `assistant.message` with the writer's output.

## Tests

```bash
cd adapters/crewai
pip install -e ".[dev]"
pytest -v
```

Coverage:

- `tests/test_adapter.py`   — Protocol conformance, name/version,
  entry-point discovery.
- `tests/test_callbacks.py` — Step/task callback event mapping.
- `tests/test_tool_bridge.py` — Wake tool → CrewAI BaseTool wrapper,
  input coercion, error handling.
- `tests/test_simple_crew.py` — Single-agent, single-task end-to-end.
- `tests/test_multi_agent.py` — Researcher + writer pipeline; task
  attribution; final message reflects last task.
- `tests/test_conformance.py` — Full `wake-test-conformance` suite.

All tests use scripted `FakeLLM` instances; no network is required.

## Conformance

`pytest -v tests/test_conformance.py` runs the canonical
`wake-test-conformance` suite. Current score: **10/10**.

| Scenario          | Status                                                |
| ----------------- | ------------------------------------------------------ |
| basic_step        | PASS                                                   |
| tool_use          | PASS                                                   |
| streaming         | PASS (warning: non-streaming — CrewAI is non-streaming)|
| cancellation      | PASS (worker thread joined cleanly on `CancelledError`)|
| resume            | PASS (idempotent — re-step is a no-op)                 |
| parallel_tools    | PASS                                                   |
| error_handling    | PASS                                                   |
| pause_turn        | PASS (warning: CrewAI does not expose pause_turn)      |
| lifecycle         | PASS (no-op on_lifecycle)                              |
| idempotence       | PASS (no duplicate `tool_use_id`s across steps)        |

## Example

```bash
cd adapters/crewai
python examples/simple_crew.py
```

The example builds an in-memory event log, injects one user message,
and prints every emitted Wake event. To use a real LLM, set
`CREWAI_REAL_LLM=1` and configure your LiteLLM credentials
(`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.).

## Design notes

- **Worker thread, not `kickoff_async`.** CrewAI's
  `kickoff_async` re-enters the sync loop in many cases and gives no
  meaningful benefit over `asyncio.to_thread(crew.kickoff)`. The latter
  is simpler and more robust against future CrewAI changes.
- **Tool dispatch goes through `tools.execute()`.** Even though
  CrewAI's `BaseTool._run` is synchronous, the adapter spins a private
  event loop in a worker thread (only when needed) to drive Wake's
  async `tools.execute()`. The wrapper class converts the result back
  to a string CrewAI's agent loop can incorporate.
- **Callbacks run on the worker thread**, but Wake events live on the
  main loop. We bridge with `loop.call_soon_threadsafe(queue.put_nowait, ev)`.
- **Final `assistant.message` is emitted by the adapter**, not the task
  callback. Doing so from the callback races with `kickoff()`
  completion in multi-task crews; emitting from the adapter guarantees
  order.

## License

Apache-2.0, same as Wake core.
