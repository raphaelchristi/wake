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

## Reusable Components

### Sistemas de plugin Python (escolher um)

| Sistema | Fonte | License | Trade-off |
|---|---|---|---|
| `pluggy` | [pytest-dev/pluggy](https://github.com/pytest-dev/pluggy) | MIT | **Recomendado.** Usado por pytest, tox, devpi. Maturo, hookspec rico. |
| `stevedore` | [openstack/stevedore](https://github.com/openstack/stevedore) | Apache 2.0 | Mais pesado, OpenStack flavor. |
| `importlib.metadata` | stdlib (Python 3.10+) | PSF | Mínimo, sem hooks. Bom se não precisar de mais. |

**Decisão recomendada:** `pluggy` se queremos hooks futuros (pre/post step, on_error, etc.). `importlib.metadata` se for descoberta simples sem extensão.

### Patterns de conformance test suite

| Pattern | Fonte | Por quê estudar |
|---|---|---|
| ASGI test suite | [django/asgiref `testing.py`](https://github.com/django/asgiref) | spec conformance Python para ASGI |
| WSGI compliance | [pep3333_validator](https://peps.python.org/pep-3333/#validator) | template formal |
| MCP spec compliance tests | [modelcontextprotocol/specification](https://github.com/modelcontextprotocol/specification) | conformance moderno |
| pytest fixtures | [pytest docs](https://docs.pytest.org/en/stable/explanation/fixtures.html) | estrutura do runner |

### Bibliotecas de protocolo

| Lib | Fonte | License | Para que |
|---|---|---|---|
| `typing.Protocol` | stdlib (Python 3.8+) | PSF | Interface estrutural |
| `runtime-checkable` decorator | stdlib | PSF | Validação |
| `pydantic` v2 | MIT | MIT | Tipos de dados compartilhados |
| `attrs` ou `dataclasses` | stdlib + attrs | MIT | SessionContext, etc. |

### Code a estudar (não forkar)

| Código | Repo | Por quê |
|---|---|---|
| Plugin discovery pattern | [black](https://github.com/psf/black/blob/main/pyproject.toml) (entry_points) | exemplo mínimo |
| Plugin discovery rich | [pytest](https://github.com/pytest-dev/pytest) (pluggy) | exemplo completo |
| AsyncIterator patterns | [httpx streaming](https://github.com/encode/httpx/) | tipagem correta |
| Adapter pattern | OpenHands V1 Agent abstraction | comparação |

### Tools / utilities reusáveis

| Tool | Source | License | Uso |
|---|---|---|---|
| Tool schema validation | JSON Schema lib `jsonschema` | MIT | Validar input de tools |
| Bash tool example | Anthropic Cookbook | educacional | template bash tool |
| MCP tool wrapping | MCP Python SDK | MIT | mapping MCP ↔ Wake Tool |

### Anti-reuso

- ❌ Não importar LangChain/LangGraph como dep do core (eles são USERS via adapter, não deps)
- ❌ Não importar CrewAI (idem)
- ❌ Não criar framework de tools próprio se MCP serve

### Economia estimada com reuso

| Decisão | Economia |
|---|---|
| `pluggy` vs sistema de plugin custom | 1-2 dias |
| Adotar conformance test pattern do ASGI/MCP | 1 dia |
| `typing.Protocol` vs ABCs | 0.5 dia |
| **Total** | **2.5-3.5 dias** numa fase de 10 dias |

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
