# Phase 2 Execution Contract

> Interface contract entre os 3 agents trabalhando Phase 2 em paralelo.
> Cada agent owns paths disjoint. Compartilham o `HarnessAdapter` Protocol
> em `src/wake/adapters/` (pré-existente, escrito como scaffolding).

---

## Pre-existing — não modificar

O scaffolding do Phase 2 já está em `src/wake/adapters/`:

```
src/wake/adapters/__init__.py       — public exports
src/wake/adapters/base.py           — HarnessAdapter Protocol + LifecycleEvent
src/wake/adapters/context.py        — SessionContext
src/wake/adapters/events.py         — EventStream ABC
src/wake/adapters/tool_registry.py  — ToolRegistry ABC
src/wake/adapters/registry.py       — AdapterRegistry (plugin discovery)
```

Esses são **AUTORITATIVOS** — agents implementam contra essas interfaces. Se um agent encontra problema, abre issue em vez de mudar.

---

## Divisão de slices

| Agent | Owns | Não toca |
|---|---|---|
| `wake-core-claude-sdk` | adapter Claude SDK + runtime integration + dependencies wiring | conformance/, langgraph/, crewai/, docs/adapters/ |
| `wake-conformance` | conformance test suite package | adapters/claude-sdk/, adapters/langgraph/, adapters/crewai/, src/wake/api/, src/wake/core/, src/wake/store/ |
| `wake-stubs-docs` | langgraph stub + crewai stub + WRITING-AN-ADAPTER.md + example 03 | adapters/claude-sdk/, adapters/conformance/, src/wake/ |

---

## Files ownership

### wake-core-claude-sdk owns

```
# Refactor existing harness into adapter package
adapters/claude-sdk/pyproject.toml
adapters/claude-sdk/src/wake_adapter_claude_sdk/__init__.py
adapters/claude-sdk/src/wake_adapter_claude_sdk/adapter.py    ← from src/wake/harness/anthropic.py
adapters/claude-sdk/tests/test_adapter.py
adapters/claude-sdk/tests/test_conformance.py                  ← runs wake-test-conformance

# Runtime wiring — events.py + dependencies.py switch from direct AnthropicHarness to adapter
src/wake/api/dependencies.py       ← MODIFY: inject AdapterRegistry
src/wake/api/routes/events.py      ← MODIFY: use adapter from registry

# Concrete impls of the abstract context/tool_registry/events for runtime
src/wake/runtime/__init__.py
src/wake/runtime/event_stream.py   ← concrete EventStream that wraps EventLog
src/wake/runtime/tool_registry.py  ← concrete ToolRegistry (wraps existing tools.registry)
src/wake/runtime/dispatcher.py     ← session executor that calls adapter.step()

# Updated harness module — keep as thin compat shim or remove entirely
src/wake/harness/anthropic.py      ← REPLACE with deprecation shim that imports from wake_adapter_claude_sdk
src/wake/harness/__init__.py       ← update re-exports

# Tests updated to match new structure
tests/unit/test_harness.py         ← UPDATE / migrate to adapters/claude-sdk/tests/
tests/unit/test_runtime_dispatcher.py  ← NEW
tests/unit/test_runtime_event_stream.py ← NEW
tests/unit/test_runtime_tool_registry.py ← NEW

# Main pyproject.toml gets entry_points + workspace setup
pyproject.toml                     ← MODIFY: add [project.entry-points."wake.adapters"]
                                     also add adapters/claude-sdk as workspace dep (or path install)
```

### wake-conformance owns

```
adapters/conformance/pyproject.toml
adapters/conformance/README.md
adapters/conformance/src/wake_test_conformance/__init__.py
adapters/conformance/src/wake_test_conformance/runner.py        ← orchestrates all scenarios
adapters/conformance/src/wake_test_conformance/harness.py       ← test harness w/ in-memory stores
adapters/conformance/src/wake_test_conformance/scenarios/__init__.py
adapters/conformance/src/wake_test_conformance/scenarios/basic_step.py
adapters/conformance/src/wake_test_conformance/scenarios/tool_use.py
adapters/conformance/src/wake_test_conformance/scenarios/streaming.py
adapters/conformance/src/wake_test_conformance/scenarios/cancellation.py
adapters/conformance/src/wake_test_conformance/scenarios/resume.py
adapters/conformance/src/wake_test_conformance/scenarios/parallel_tools.py
adapters/conformance/src/wake_test_conformance/scenarios/error_handling.py
adapters/conformance/src/wake_test_conformance/scenarios/pause_turn.py
adapters/conformance/src/wake_test_conformance/scenarios/lifecycle.py
adapters/conformance/src/wake_test_conformance/scenarios/idempotence.py
adapters/conformance/tests/test_self.py                        ← validates runner against an echo adapter
```

### wake-stubs-docs owns

```
adapters/langgraph/pyproject.toml
adapters/langgraph/README.md
adapters/langgraph/src/wake_adapter_langgraph/__init__.py
adapters/langgraph/src/wake_adapter_langgraph/adapter.py       ← STUB returning "hello from langgraph"
adapters/langgraph/tests/test_stub.py

adapters/crewai/pyproject.toml
adapters/crewai/README.md
adapters/crewai/src/wake_adapter_crewai/__init__.py
adapters/crewai/src/wake_adapter_crewai/adapter.py             ← STUB
adapters/crewai/tests/test_stub.py

docs/WRITING-AN-ADAPTER.md                                     ← tutorial

examples/03-adapter-discovery/README.md
examples/03-adapter-discovery/run.sh
```

---

## CONFORMANCE SCENARIO SPECIFICATION (definitivo — wake-conformance segue)

Cada scenario implementa um pequeno teste isolado. O runner constrói o ambiente:

- `InMemoryEventStore` (foundation's fakes ou implementação própria minimal)
- `InMemoryToolRegistry` com 1-2 tools de mentira
- `SessionContext` com agente fake
- `EventStream` envolvendo o event store
- Cria a sessão com `user.message` inicial
- Chama `adapter.step(ctx, events, tools)` e verifica eventos emitidos

### Lista canônica (10 scenarios v0.1.0)

1. **basic_step** — adapter responde "ok" a "say ok" e emite `assistant.message` com stop_reason
2. **tool_use** — adapter chama tool `echo` quando user pede, emite `tool_use` + recebe `tool_result` + emite `assistant.message`
3. **streaming** — adapter emite ≥1 `assistant.delta` antes de `assistant.message` final
4. **cancellation** — quando step() é cancelado (asyncio.CancelledError), adapter limpa cleanly (sem warning, sem traceback)
5. **resume** — chamar step() duas vezes na mesma sessão produz comportamento sensato (re-emite events corretos ou termina cedo se sessão já completa)
6. **parallel_tools** — adapter pode lidar com múltiplas tool_use calls num turno (Claude às vezes faz isso)
7. **error_handling** — quando tool retorna `is_error=true`, adapter incorpora ao loop sem crash (pode pedir retry ou desistir, mas não panicar)
8. **pause_turn** — adapter emite `pause_turn` event quando atinge condições configuradas (e.g. max_tokens)
9. **lifecycle** — adapter recebe `on_lifecycle("created")` e similares quando runtime chama
10. **idempotence** — chamar step() duas vezes com mesmo input/event log não duplica eventos com mesmo `tool_use_id`

Cada scenario:

- Função `async def run(adapter: HarnessAdapter) -> ScenarioResult`
- Returns `ScenarioResult(name, passed, message, duration_ms)`
- Não usa LLM real — adapters under test usam fakes (echo, deterministic)

### Public API

```python
from wake_test_conformance import run_conformance, ConformanceReport

report = await run_conformance(adapter)
# report.results: list[ScenarioResult]
# report.passed: bool
# report.summary(): str
```

Também como pytest fixture:

```python
# adapters/claude-sdk/tests/test_conformance.py
import pytest
from wake_test_conformance import run_conformance
from wake_adapter_claude_sdk import ClaudeSDKAdapter

@pytest.mark.asyncio
async def test_conformance():
    # uses a mock anthropic client for determinism
    adapter = ClaudeSDKAdapter(client=fake_client)
    report = await run_conformance(adapter)
    assert report.passed, report.summary()
```

---

## STUB ADAPTER REQUIREMENTS

Stubs **não** precisam passar o conformance suite completo. Mas precisam:

- Implementar `HarnessAdapter` Protocol corretamente (versão `0.1.0-stub`)
- Ter `name` distinto: `langgraph`, `crewai`
- Em `step()`, emitir um único `assistant.message` com texto `"stub from <framework>"` (não importa o user input)
- `on_lifecycle()` pode ser no-op
- Declaração entry_point em `pyproject.toml`:
  ```toml
  [project.entry-points."wake.adapters"]
  langgraph = "wake_adapter_langgraph.adapter:create"
  ```
- `create()` factory para uso simples (sem args), demonstrando o pattern para implementação real depois

Testes:
- `test_stub.py` — adapter discoverable, step retorna o evento esperado

---

## WRITING-AN-ADAPTER.md

Tutorial linear (~1500-2500 palavras):

1. Conceitos — o que é um harness, o que Wake provê
2. A interface — copy de `SPEC-HARNESS-ADAPTER.md` essencial, sem redundância
3. Setup do package — pyproject.toml, entry_points, layout
4. Implementing `step()` — andar de eventos, chamar tools, emitir eventos
5. Implementing `on_lifecycle()` — opcional, casos de uso
6. Tools — adaptar tools do framework para `tools.execute(...)`
7. Conformance — rodar `wake-test-conformance`, interpretar falhas
8. Versioning — `compatibility` field, semver da spec
9. Publishing — PyPI conventions, README, exemplos
10. Real-world references — link para os 2 stubs + Claude SDK adapter completo

Tom: pragmático, copia-pode-rodar. Não documentação acadêmica.

---

## CLAUDE SDK ADAPTER REFACTOR (wake-core-claude-sdk)

### Source da refatoração

`src/wake/harness/anthropic.py` já tem o loop completo Phase 1:

- Constrói messages de events
- Chama Anthropic Messages API com streaming
- Trata `text_delta`, `tool_use`, `message_stop`
- Recursão em tool_use → tool_result → continue
- Emite eventos canônicos

### Target

```
adapters/claude-sdk/src/wake_adapter_claude_sdk/adapter.py
```

```python
from anthropic import AsyncAnthropic
from wake.adapters import HarnessAdapter

class ClaudeSDKAdapter:
    name = "claude-sdk"
    version = "0.1.0"
    compatibility = "wake-harness-adapter@^0.1"

    def __init__(self, client: AsyncAnthropic | None = None) -> None:
        self.client = client or AsyncAnthropic()

    async def step(self, ctx, events, tools):
        # SAME LOGIC as src/wake/harness/anthropic.py
        # But:
        #  - read events via `await events.all()` instead of event_store
        #  - call tools via `await tools.execute(name, input, tool_use_id=id)`
        #  - emit events with yield (this method is now async generator)
        ...

    async def on_lifecycle(self, ctx, event):
        # no-op for Claude SDK
        pass
```

### Runtime wiring

`src/wake/runtime/dispatcher.py`:

```python
class SessionDispatcher:
    """Routes session.step() calls to the configured HarnessAdapter."""

    def __init__(
        self,
        adapter_registry: AdapterRegistry,
        event_log: EventLog,
        session_service: SessionService,
        tools_factory: ToolsFactory,
    ) -> None:
        ...

    async def run_step(self, session: Session, agent: AgentConfig) -> None:
        adapter_name = agent.metadata.get("harness", "claude-sdk")
        adapter = self.adapter_registry.get(adapter_name)

        ctx = SessionContext(
            session_id=session.id,
            agent_id=agent.id,
            agent_version=agent.version,
            agent_config=agent,
            environment_id=session.environment_id,
            sandbox=None,  # provisioned lazily per tool call
            vault_id=None,
            metadata=session.metadata,
        )
        events = EventStreamImpl(self.event_log, session.id)
        tools = self.tools_factory.build(session, agent)

        async for new_event in adapter.step(ctx, events, tools):
            await self.event_log.append(session.id, new_event.type, new_event.payload, ...)
```

`src/wake/api/routes/events.py` — substituir uso direto de `AnthropicHarness` por chamada a `SessionDispatcher`.

`src/wake/api/dependencies.py` — wire o registry no startup.

### Backward compatibility

- Manter `src/wake/harness/anthropic.py` por enquanto como shim de deprecation que importa de `wake_adapter_claude_sdk` (warning + re-export).
- Phase 2.5 ou Phase 3: remover o shim.

---

## DEPS adicionais — pyproject.toml updates

wake-core-claude-sdk adiciona:

```toml
[project.optional-dependencies]
adapter-claude-sdk = [
    "wake-adapter-claude-sdk @ {root:uri}/adapters/claude-sdk",
]
```

E entry_points:

```toml
[project.entry-points."wake.adapters"]
# Discovered automatically when wake-adapter-claude-sdk is installed
```

Cada adapter package declara seu próprio entry_point em SEU pyproject.toml.

---

## DEFINITION OF DONE

### wake-core-claude-sdk done quando:

- [ ] `adapters/claude-sdk` é package instalável (`pip install -e adapters/claude-sdk` funciona)
- [ ] `from wake_adapter_claude_sdk import ClaudeSDKAdapter` importa sem erro
- [ ] `ClaudeSDKAdapter` implementa o Protocol (mypy/pyright valida)
- [ ] `wake.runtime.dispatcher.SessionDispatcher` despacha via adapter
- [ ] API routes (`events.py`) chamam dispatcher em vez de AnthropicHarness direto
- [ ] AdapterRegistry com entry_point discovery funcionando
- [ ] Tests existing Phase 1 continuam passando
- [ ] Novos tests para dispatcher/event_stream/tool_registry runtime impls (≥70% cov)
- [ ] Claude SDK adapter passa 100% do conformance suite (assumindo wake-conformance pronto)

### wake-conformance done quando:

- [ ] `adapters/conformance` é package instalável (`pip install -e adapters/conformance`)
- [ ] `from wake_test_conformance import run_conformance` importa
- [ ] 10 cenários implementados e testáveis isoladamente
- [ ] Runner reporta resultados estruturados (passed/failed/duration)
- [ ] `test_self.py` valida runner contra echo adapter
- [ ] Documentado como integrar com pytest

### wake-stubs-docs done quando:

- [ ] `adapters/langgraph` instalável, stub funciona
- [ ] `adapters/crewai` instalável, stub funciona
- [ ] Ambos discoverable via entry_points
- [ ] `WRITING-AN-ADAPTER.md` completo e testado por outsider mental walk-through
- [ ] `examples/03-adapter-discovery/` runnable em <2min

---

## INTEGRATION POINT

Quando todos terminarem, merge na ordem:

1. **wake-conformance** → main (independente, sem conflito)
2. **wake-core-claude-sdk** → main (modifica src/wake/, refactor crítico)
3. **wake-stubs-docs** → main (independente do refactor, mas precisa que pyproject tenha entry_points)

Conflitos esperados em: `pyproject.toml` (entry_points), `src/wake/harness/__init__.py` (re-exports), tests/unit/conftest.py.

---

## CONVENÇÕES

Mesmo Phase 1:

- Python 3.11+, async/await, ruff, mypy --strict
- Commit messages com prefixo do slice: `claude-sdk:`, `conformance:`, `stubs:`, `runtime:`
- Cada agent trabalha no SEU worktree
- Não mude `src/wake/adapters/*` — é spec

---

## REGRA DE OURO

1. **Leia este contrato + SPEC-HARNESS-ADAPTER.md + PHASE-2-first-adapter.md ANTES de codar.**
2. **Use os types de `src/wake/adapters/` EXATAMENTE como especificados.**
3. **Não invente novas interfaces — siga as Protocols deste contrato.**
4. **Se precisar de algo fora do seu slice, deixa TODO comment e segue.**
5. **Commit no SEU worktree, não na main.**
6. **Estimativa: completa o slice em 60-90min wall-clock.**
