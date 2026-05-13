# Phase 2 — First Adapter

> **Objetivo:** HarnessAdapter ABI implementada em código. Refatorar harness Anthropic da Phase 1 para usar a interface (dogfooding). Conformance test suite que valida qualquer adapter contra a spec.

| | |
|---|---|
| **Status** | ⚪ not_started |
| **Duração estimada** | 2 semanas (10 working days) |
| **Dependências** | Phase 1 done (skeleton funcionando) |

---

## Por que essa fase existe

Phase 1 hardcoded o harness. Funciona, mas viola o princípio central: **um runtime, qualquer harness**. Phase 2 transforma o harness hardcoded em o primeiro adapter conformante à HarnessAdapter ABI.

Crítico: **a abstração é construída a partir de um caso real funcionando**, não no vazio. Isso evita premature abstraction.

Resultado: a ABI é validada por um adapter de produção (Claude SDK) E acompanhada de um test suite que qualquer adapter futuro precisa passar.

---

## Entry criteria

- ✅ Phase 1 done
- ✅ Examples 01 e 02 funcionando
- ✅ Anthropic harness loop existe e funciona

---

## Exit criteria (gates)

Todos verificadamente cumpridos:

- [ ] Protocol `wake.adapters.HarnessAdapter` definido em código, matching `SPEC-HARNESS-ADAPTER.md`
- [ ] `wake.types` package com `SessionContext`, `EventStream`, `ToolRegistry`, `Event`, `LifecycleEvent`
- [ ] Plugin discovery via Python `entry_points` funcionando
- [ ] Harness Anthropic refatorado como `wake-adapter-claude-sdk` package
- [ ] Default runtime path usa o adapter — sem código especial para Claude SDK
- [ ] Conformance test suite (`wake-test-conformance`) implementada
- [ ] Conformance tests cobrem ≥10 cenários (lista abaixo)
- [ ] Claude SDK adapter passa 100% dos conformance tests
- [ ] Example 02 ainda funciona (regression check)
- [ ] Docs novas: `docs/WRITING-AN-ADAPTER.md` com tutorial
- [ ] 2 outros adapters STUB (não implementação completa) demonstram que a interface generaliza:
  - [ ] `wake-adapter-langgraph` (stub que delega pra LangGraph mas só faz hello-world)
  - [ ] `wake-adapter-crewai` (idem)
- [ ] Documentação clara sobre como instalar e usar adapter externo:
  ```bash
  pip install wake-adapter-langgraph
  wake session create --agent x --harness langgraph
  ```

---

## Deliverables

### Pacotes Python publicados (ou prontos para publicar)

```
wake-ai                          # core, já existia
wake-adapter-claude-sdk          # primeiro adapter conformante
wake-adapter-langgraph           # stub (Phase 3 completa)
wake-adapter-crewai              # stub (Phase 3 completa)
wake-test-conformance            # test suite
```

### Estrutura adicional do código

```
src/wake/
├── adapters/                    # framework do adapter system
│   ├── __init__.py
│   ├── base.py                  # HarnessAdapter Protocol
│   ├── registry.py              # plugin discovery
│   └── runtime.py               # session executor que usa adapter
├── types.py                     # expandido com SessionContext etc.
└── conformance/                 # test suite
    ├── __init__.py
    ├── runner.py
    ├── scenarios/
    │   ├── basic_step.py
    │   ├── tool_use.py
    │   ├── streaming.py
    │   ├── cancellation.py
    │   ├── resume.py
    │   ├── parallel_tools.py
    │   ├── error_handling.py
    │   ├── pause_turn.py
    │   ├── lifecycle.py
    │   └── idempotence.py
    └── harness_under_test.py    # fixture genérica

adapters/                         # workspace pra adapters separados
├── claude-sdk/
│   ├── pyproject.toml
│   ├── src/wake_adapter_claude_sdk/
│   │   ├── __init__.py
│   │   └── adapter.py
│   └── tests/
│       └── test_conformance.py  # roda o conformance suite
├── langgraph/
│   └── (stub)
└── crewai/
    └── (stub)

docs/
└── WRITING-AN-ADAPTER.md         # tutorial
```

### Refactor crítico

```python
# antes (Phase 1):
class WakeServer:
    def __init__(self):
        self.harness = AnthropicHarness()  # hardcoded

    async def run_session(self, session):
        await self.harness.step(session)

# depois (Phase 2):
class WakeServer:
    def __init__(self):
        self.adapter_registry = AdapterRegistry()
        self.adapter_registry.discover()  # via entry_points

    async def run_session(self, session):
        adapter = self.adapter_registry.get(session.agent.harness)
        async for event in adapter.step(session.context, session.events, session.tools):
            await self.event_log.append(session.id, event)
```

---

## Tasks detalhadas

### T2.1 — Definir HarnessAdapter Protocol (4h)

Em `src/wake/adapters/base.py`:

```python
from typing import Protocol, AsyncIterator

class HarnessAdapter(Protocol):
    name: str
    version: str
    compatibility: str  # ex: "wake-harness-adapter@^0.1"

    async def step(
        self,
        ctx: SessionContext,
        events: EventStream,
        tools: ToolRegistry,
    ) -> AsyncIterator[Event]: ...

    async def on_lifecycle(self, ctx, event: LifecycleEvent) -> None: ...
```

Validação match exato com `SPEC-HARNESS-ADAPTER.md`.

### T2.2 — Implementar types compartilhados (4h)

Em `src/wake/types.py`:

- `SessionContext` (dataclass)
- `EventStream` (class com `all()`, `since()`, `latest()`, `count()`)
- `ToolRegistry` (class com `list()`, `get()`, `execute()`)
- `LifecycleEvent` (enum)

### T2.3 — Plugin discovery via entry_points (4h)

```toml
# adapters/claude-sdk/pyproject.toml
[project.entry-points."wake.adapters"]
claude-sdk = "wake_adapter_claude_sdk.adapter:ClaudeSDKAdapter"
```

```python
# src/wake/adapters/registry.py
import importlib.metadata

class AdapterRegistry:
    def discover(self):
        for ep in importlib.metadata.entry_points(group="wake.adapters"):
            self.register(ep.name, ep.load())
```

### T2.4 — Refatorar Anthropic harness em `wake-adapter-claude-sdk` (1.5d)

Mover código da Phase 1 para `adapters/claude-sdk/`. Implementar `HarnessAdapter` Protocol. Empacotar como package separado mas no mesmo monorepo.

```python
# adapters/claude-sdk/src/wake_adapter_claude_sdk/adapter.py
from anthropic import AsyncAnthropic
from wake.adapters import HarnessAdapter

class ClaudeSDKAdapter:
    name = "claude-sdk"
    version = "0.1.0"
    compatibility = "wake-harness-adapter@^0.1"

    def __init__(self, client: AsyncAnthropic | None = None):
        self.client = client or AsyncAnthropic()

    async def step(self, ctx, events, tools):
        # lógica que estava no harness Phase 1
        ...
```

### T2.5 — Session executor usa adapter (1d)

```python
# src/wake/adapters/runtime.py
class AdapterRuntime:
    async def execute_step(self, session, adapter):
        async for event in adapter.step(
            session.context,
            session.events,
            session.tools,
        ):
            await self.event_log.append(session.id, event)
```

### T2.6 — Conformance test suite (2d)

10 cenários, cada um como módulo Python:

1. **basic_step.py** — adapter responde "hello" a "say hi"
2. **tool_use.py** — adapter chama uma tool e processa resultado
3. **streaming.py** — adapter emite assistant.delta antes de assistant.message
4. **cancellation.py** — adapter respeita asyncio cancel
5. **resume.py** — adapter funciona quando re-chamado após interrupção
6. **parallel_tools.py** — adapter lida com tool calls paralelas
7. **error_handling.py** — adapter trata tool_result com is_error=true
8. **pause_turn.py** — adapter emite pause_turn quando apropriado
9. **lifecycle.py** — adapter recebe on_lifecycle corretamente
10. **idempotence.py** — chamar step() duas vezes não duplica

Runner:

```python
# src/wake/conformance/runner.py
async def run_conformance(adapter: HarnessAdapter) -> ConformanceReport:
    results = []
    for scenario in SCENARIOS:
        result = await scenario.run(adapter)
        results.append(result)
    return ConformanceReport(adapter=adapter, results=results)
```

### T2.7 — Claude SDK adapter passa conformance (1d)

Rodar conformance suite contra Claude SDK adapter. Corrigir adapter conforme falhas. Iterar até 100% green.

Output esperado:

```
$ pytest adapters/claude-sdk/tests/test_conformance.py
test_basic_step ........... PASSED
test_tool_use ............. PASSED
test_streaming ............ PASSED
test_cancellation ......... PASSED
test_resume ............... PASSED
test_parallel_tools ....... PASSED
test_error_handling ....... PASSED
test_pause_turn ........... PASSED
test_lifecycle ............ PASSED
test_idempotence .......... PASSED

10 passed in 12.34s
```

### T2.8 — Stub adapters: langgraph, crewai (1d)

Não implementação completa. Só:

- Package structure
- Stub que retorna "hello from langgraph adapter"
- Entry point registrado
- Test "adapter is discovered"

```python
class LangGraphAdapter:
    name = "langgraph"
    version = "0.1.0-stub"

    async def step(self, ctx, events, tools):
        yield Event(type="assistant.message",
                    payload={"content": [{"type": "text",
                                          "text": "stub from langgraph"}]})
```

Justifica que a interface generaliza. Implementação real é Phase 3.

### T2.9 — Docs: WRITING-AN-ADAPTER.md (4h)

Tutorial passo-a-passo:

1. Setup do package (pyproject.toml, entry_points)
2. Implementar HarnessAdapter Protocol
3. Mapear events do framework → events Wake
4. Mapear tools.execute() → tool calls do framework
5. Rodar conformance suite
6. Publicar no PyPI

Com exemplo completo (não-stub) — pode ser um adapter trivial pra "echo bot".

### T2.10 — Example 02 regression (2h)

Garantir que exemplo de coding refactor da Phase 1 ainda funciona, agora rodando via adapter.

### T2.11 — Example: adapter discovery (4h)

Novo exemplo: `examples/03-adapter-discovery/`:

```bash
pip install wake-ai wake-adapter-claude-sdk wake-adapter-langgraph

wake adapter list
# claude-sdk@0.1.0
# langgraph@0.1.0-stub

wake session create --agent x --harness claude-sdk
wake session create --agent y --harness langgraph
```

Demonstra que plugins funcionam.

---

## Riscos e mitigações

### R2.1 — Signature da HarnessAdapter precisa mudar depois de implementar
**Probabilidade:** alta
**Impacto:** médio
**Mitigação:**
- É exatamente por isso que primeiro adapter é feito ANTES de lock formal
- Versionar spec como v0.1.x durante Phase 2
- Spec lock final acontece no fim da Phase 3 (após 4 adapters validarem)

### R2.2 — Plugin discovery via entry_points é fiddly
**Probabilidade:** média
**Impacto:** baixo
**Mitigação:**
- Pattern bem documentado (FastAPI, Black, Sphinx usam)
- Fallback: registry manual via env var ou config file

### R2.3 — Conformance tests incompletos
**Probabilidade:** alta (descobre buracos só com adapters reais)
**Impacto:** baixo
**Mitigação:**
- Phase 3 adiciona mais cenários conforme adapters reais aparecem
- v0.1.0 do conformance suite é mínimo viável

### R2.4 — Stub adapters criam impressão de "feature complete" antes da hora
**Probabilidade:** baixa
**Impacto:** médio (expectation management)
**Mitigação:**
- Stubs marcados explicitamente como `0.1.0-stub`
- Docs claras: "stub adapters demonstrate discovery, not full integration"
- README de cada stub diz "implementação completa em Phase 3"

### R2.5 — Refactor da Phase 1 quebra exemplos
**Probabilidade:** média
**Impacto:** baixo
**Mitigação:**
- Manter examples 01 e 02 como regression tests no CI
- Não merge se quebrar exemplos

### R2.6 — Tools.execute() interceptado por adapter introduz bug sutil
**Probabilidade:** média
**Impacto:** médio
**Mitigação:**
- Conformance test `parallel_tools` cobre isso
- Documentação reforça: adapters NUNCA chamam funções tool diretamente

---

## Decisões adiadas

- ❌ LangGraph adapter completo (Phase 3)
- ❌ CrewAI adapter completo (Phase 3)
- ❌ Pydantic AI adapter (Phase 3)
- ❌ Spec lock v1.0 (final Phase 3)
- ❌ Tudo o que era adiado em Phase 1

---

## Definition of Done

- [ ] Todos os Exit Criteria checkados
- [ ] CI green em todos os packages (core + claude-sdk + stubs)
- [ ] 10 conformance tests passando para Claude SDK adapter
- [ ] Stubs LangGraph e CrewAI installable e discoverable
- [ ] Tutorial `WRITING-AN-ADAPTER.md` testado por outsider
- [ ] Tag `v0.0.2-first-adapter` em git
- [ ] Status em `phases/README.md` atualizado

---

## Métricas de sucesso

| Métrica | Mínimo | Meta |
|---|---|---|
| Conformance tests passando para Claude SDK | 10/10 | 10/10 |
| Test coverage do core | ≥75% | ≥90% |
| Tempo total `pip install + wake run` | <3min | <2min |
| Tamanho do core package | n/a | <500KB |
| Tempo de discovery de adapters | n/a | <100ms |

---

## After this phase

→ [Phase 3: Spec Validation](./PHASE-3-spec-validation.md) — implementação completa dos adapters LangGraph, CrewAI, Pydantic AI. Prova generalidade da interface contra paradigmas diferentes de frameworks.
