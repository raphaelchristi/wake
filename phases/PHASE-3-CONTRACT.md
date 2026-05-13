# Phase 3 Execution Contract

> Substituir os 3 stubs de Phase 2 por implementações reais de LangGraph, CrewAI, e Pydantic AI.
> Cada agent owns 1 framework adapter (3 packages disjuntos).

---

## Pre-existing — não modificar

- `src/wake/adapters/` — Protocol + ABCs (AUTORITATIVO)
- `adapters/conformance/` — wake-test-conformance v0.1.0 (consumir, não modificar)
- `adapters/claude-sdk/` — reference adapter (consultar para padrões)
- `src/wake/runtime/` — dispatcher (não modificar)
- `src/wake/types.py` — canonical types (não modificar)
- `tests/unit/fakes.py` — fakes runtime (não modificar)

---

## Divisão de slices

| Agent | Owns | Framework version target |
|---|---|---|
| `wake-langgraph-real` | `adapters/langgraph/*` (replace stub) | `langgraph>=1.0` |
| `wake-crewai-real` | `adapters/crewai/*` (replace stub) | `crewai>=1.0` |
| `wake-pydantic-ai-real` | `adapters/pydantic-ai/*` (NEW package) | `pydantic-ai>=1.0` |

**Importante:** Pydantic AI ainda NÃO tem stub em main — é package totalmente novo. LangGraph e CrewAI ganham implementação real substituindo o stub.

---

## Files ownership

### wake-langgraph-real owns

```
adapters/langgraph/pyproject.toml                     ← REPLACE: add langgraph dep + version → 0.1.0
adapters/langgraph/README.md                          ← REPLACE: real adapter docs
adapters/langgraph/src/wake_adapter_langgraph/__init__.py
adapters/langgraph/src/wake_adapter_langgraph/adapter.py  ← REPLACE: real LangGraph integration
adapters/langgraph/src/wake_adapter_langgraph/event_mapping.py  ← NEW: events ↔ LangChain messages
adapters/langgraph/src/wake_adapter_langgraph/tool_injection.py  ← NEW: tools.execute() → LangChain BaseTool
adapters/langgraph/tests/test_adapter.py              ← REPLACE: real tests
adapters/langgraph/tests/test_event_mapping.py        ← NEW
adapters/langgraph/tests/test_tool_injection.py       ← NEW
adapters/langgraph/tests/test_simple_graph.py         ← NEW: integration with real graph
adapters/langgraph/tests/test_react_agent.py          ← NEW: ReAct pattern
adapters/langgraph/examples/__init__.py
adapters/langgraph/examples/simple_graph.py           ← NEW: runnable example
```

### wake-crewai-real owns

```
adapters/crewai/pyproject.toml                        ← REPLACE
adapters/crewai/README.md                             ← REPLACE
adapters/crewai/src/wake_adapter_crewai/__init__.py
adapters/crewai/src/wake_adapter_crewai/adapter.py    ← REPLACE: real CrewAI integration
adapters/crewai/src/wake_adapter_crewai/callbacks.py  ← NEW: Crew callbacks → Wake events
adapters/crewai/src/wake_adapter_crewai/tool_bridge.py ← NEW: wake tools → CrewAI BaseTool
adapters/crewai/tests/test_adapter.py                 ← REPLACE
adapters/crewai/tests/test_callbacks.py               ← NEW
adapters/crewai/tests/test_tool_bridge.py             ← NEW
adapters/crewai/tests/test_simple_crew.py             ← NEW: 1 agent, 1 task
adapters/crewai/tests/test_multi_agent.py             ← NEW: researcher + writer
adapters/crewai/examples/__init__.py
adapters/crewai/examples/simple_crew.py
```

### wake-pydantic-ai-real owns

```
adapters/pydantic-ai/pyproject.toml                   ← NEW
adapters/pydantic-ai/README.md                        ← NEW
adapters/pydantic-ai/src/wake_adapter_pydantic_ai/__init__.py
adapters/pydantic-ai/src/wake_adapter_pydantic_ai/adapter.py  ← NEW
adapters/pydantic-ai/src/wake_adapter_pydantic_ai/tool_bridge.py  ← NEW
adapters/pydantic-ai/tests/test_adapter.py
adapters/pydantic-ai/tests/test_tool_bridge.py
adapters/pydantic-ai/tests/test_typed_agent.py
adapters/pydantic-ai/tests/test_streaming.py
adapters/pydantic-ai/examples/__init__.py
adapters/pydantic-ai/examples/typed_agent.py
```

---

## ACCEPTANCE CRITERIA per slice

### wake-langgraph-real done quando:

- [ ] `pip install -e adapters/langgraph` works with `langgraph>=1.0` installed
- [ ] `from wake_adapter_langgraph import LangGraphAdapter` works
- [ ] `LangGraphAdapter(graph: StateGraph)` constructor signature
- [ ] `isinstance(LangGraphAdapter(simple_graph), HarnessAdapter)` returns True
- [ ] `name="langgraph"`, `version="0.1.0"`, `compatibility="wake-harness-adapter@^0.1"`
- [ ] Supports `StateGraph` with conditional edges + tool nodes
- [ ] Supports `create_react_agent`-style agents (or documented as TODO if too complex)
- [ ] Maps LangChain `HumanMessage`/`AIMessage`/`ToolMessage` ↔ Wake `user.message`/`assistant.message`/`tool_use`+`tool_result`
- [ ] Wake `tools` injection: substitui o tool node do graph por wrapper que chama `tools.execute()`
- [ ] Streaming via `graph.astream()` emits `assistant.delta` events
- [ ] All test suites pass (mock model client)
- [ ] Conformance suite passes ≥8/10 scenarios (some lenience for pause_turn/parallel_tools acceptable, document gaps)
- [ ] Example `simple_graph.py` runnable (with mock or real model)
- [ ] ruff + mypy clean on owned paths

### wake-crewai-real done quando:

- [ ] `pip install -e adapters/crewai` works with `crewai>=1.0` installed
- [ ] `from wake_adapter_crewai import CrewAIAdapter` works
- [ ] `CrewAIAdapter(crew_factory: Callable[[str], Crew])` constructor
- [ ] `isinstance(CrewAIAdapter(factory), HarnessAdapter)` returns True
- [ ] `name="crewai"`, `version="0.1.0"`, `compatibility="wake-harness-adapter@^0.1"`
- [ ] Supports single-agent Crew
- [ ] Supports multi-agent Crew (researcher + writer pattern)
- [ ] CrewAI `step_callback` / `task_callback` emit Wake events:
  - Agent thoughts → `assistant.thinking`
  - Tool calls → `tool_use` (with tool_use_id)
  - Tool results → `tool_result`
  - Final task output → `assistant.message`
- [ ] Wake `tools` injection: CrewAI tools wrap `tools.execute()`
- [ ] All test suites pass
- [ ] Conformance ≥7/10
- [ ] Example `simple_crew.py` runnable
- [ ] ruff + mypy clean

### wake-pydantic-ai-real done quando:

- [ ] `pip install -e adapters/pydantic-ai` works with `pydantic-ai>=1.0` installed
- [ ] `from wake_adapter_pydantic_ai import PydanticAIAdapter` works
- [ ] `PydanticAIAdapter(agent: pydantic_ai.Agent)` constructor
- [ ] `isinstance(PydanticAIAdapter(agent), HarnessAdapter)` returns True
- [ ] `name="pydantic-ai"`, `version="0.1.0"`, `compatibility="wake-harness-adapter@^0.1"`
- [ ] Supports typed Agents with result_type
- [ ] Supports tool calls
- [ ] Streaming via `agent.run_stream()` emits `assistant.delta`
- [ ] Maps Pydantic AI message history ↔ Wake event log
- [ ] Wake `tools` registration on Pydantic AI Agent
- [ ] All test suites pass
- [ ] Conformance ≥8/10 (Pydantic AI is most strict-typed; should be highest score)
- [ ] Example `typed_agent.py` runnable
- [ ] ruff + mypy clean

---

## ENTRY POINTS

Each `pyproject.toml`:

```toml
[project.entry-points."wake.adapters"]
langgraph = "wake_adapter_langgraph.adapter:create"
# OR
crewai = "wake_adapter_crewai.adapter:create"
# OR
pydantic-ai = "wake_adapter_pydantic_ai.adapter:create"
```

The `create()` factory should accept optional args via env vars or be a stub that creates a minimal default (e.g. echo graph) — real usage requires `Adapter(my_graph)`.

---

## STREAMING & EVENT EMISSION

Common pattern for all 3:

1. Adapter `step()` is an async generator
2. Read existing events via `await events.all()` → map to framework's input
3. Run framework (e.g. `graph.astream()`, `crew.kickoff_async()`, `agent.run_stream()`)
4. Translate framework events → Wake events, `yield` them
5. Tool calls go via `tools.execute(name, input, tool_use_id=id)`
6. Final assistant message emitted before return
7. `on_lifecycle()` can be no-op (or hook framework cleanup if needed)

---

## CONFORMANCE TESTING

Each adapter package must have:

```python
# adapters/<framework>/tests/test_conformance.py
import pytest
from wake_test_conformance import run_conformance
from wake_adapter_<framework> import <Framework>Adapter

@pytest.mark.asyncio
async def test_conformance():
    adapter = <Framework>Adapter(...)  # with mock model
    report = await run_conformance(adapter)
    # Allow some scenarios to fail with warnings (framework-specific limits)
    assert report.passed_count >= 7  # or 8 per acceptance criteria
```

Document which scenarios fail and why in the adapter README.

---

## SHARED DECISIONS

### Versioning

- All 3 adapters version `0.1.0` (graduation from stub)
- Spec `compatibility` field: `"wake-harness-adapter@^0.1"`

### Python version

- All 3 require `>=3.11`

### Framework version pinning

- Pin minimum versions in `dependencies`
- Pin maximum version in `dev` deps for CI determinism (e.g. `langgraph>=1.0,<2.0`)

### Mock strategy

- Use framework's official mock/test utilities if available
- Otherwise: stub the LLM client (mock anthropic / openai / etc.)
- NEVER hit real LLM in unit tests

---

## MERGE ORDER

Quando todos terminarem:

1. **wake-pydantic-ai-real** → main (new package, zero conflict)
2. **wake-langgraph-real** → main (replace stub, conflict in pyproject possible)
3. **wake-crewai-real** → main (replace stub, conflict in pyproject possible)

Conflitos esperados em: `adapters/<framework>/pyproject.toml` (entry_point já existe), `adapters/<framework>/src/wake_adapter_*/adapter.py` (replace stub completo).

---

## CONVENÇÕES

- Python 3.11+, async/await, ruff, mypy strict
- Commit messages com prefixo: `langgraph:`, `crewai:`, `pydantic-ai:`
- Cada agent trabalha no SEU worktree
- Não toque em files de outros slices
- Sem real LLM calls em tests

---

## REGRA DE OURO

1. **Leia este contrato + PHASE-3-spec-validation.md + adapters/claude-sdk/ ANTES de codar.**
2. **Use o Protocol e ABCs de `src/wake/adapters/` EXATAMENTE.**
3. **Conformance suite é a validação — passa ≥7-8/10 cenários.**
4. **Não invente — siga o pattern do `claude-sdk` adapter.**
5. **Commit no SEU worktree, não na main.**
6. **Estimativa: 60-120min wall-clock por slice (mais que Phase 2 — frameworks reais são complexos).**
