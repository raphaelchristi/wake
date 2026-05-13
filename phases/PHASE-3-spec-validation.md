# Phase 3 — Spec Validation

> **Objetivo:** Provar generalidade do HarnessAdapter implementando 3 adapters completos para frameworks com paradigmas diferentes (LangGraph, CrewAI, Pydantic AI). Amendar spec baseado em friction real. Lock v1.0.

| | |
|---|---|
| **Status** | ⚪ not_started |
| **Duração estimada** | 3 semanas (15 working days) |
| **Dependências** | Phase 2 done (Claude SDK adapter + stubs) |

---

## Por que essa fase existe

A HarnessAdapter da Phase 2 foi desenhada a partir de UM caso (Claude SDK direto). Pode estar superfitada a esse caso.

Phase 3 é stress test: forçamos 3 frameworks com paradigmas radicalmente diferentes (graph-based vs role-based vs type-safe) a caberem na mesma interface. Onde a interface dobra, ajustamos.

Resultado: spec é validada pela realidade, não por design. Lock v1.0 acontece com confiança.

---

## Entry criteria

- ✅ Phase 2 done
- ✅ HarnessAdapter Protocol implementado
- ✅ Claude SDK adapter passa conformance
- ✅ Stubs LangGraph e CrewAI installable

---

## Exit criteria (gates)

Todos verificadamente cumpridos:

- [ ] `wake-adapter-langgraph` implementação completa
  - [ ] Passa 100% do conformance suite
  - [ ] Roda exemplo real de StateGraph (multi-node, conditional edges)
  - [ ] Roda exemplo ReAct-style agent
  - [ ] Roda exemplo com tool calls usando LangChain tools
- [ ] `wake-adapter-crewai` implementação completa
  - [ ] Passa 100% do conformance suite
  - [ ] Roda exemplo de Crew com 2+ agents
  - [ ] Roda exemplo com Tasks dependentes
  - [ ] Eventos `assistant.thinking` capturam thoughts de cada agent
- [ ] `wake-adapter-pydantic-ai` implementação completa
  - [ ] Passa 100% do conformance suite
  - [ ] Roda exemplo de Agent tipado
  - [ ] Tool calls Pydantic AI mapeiam corretamente para events Wake
- [ ] Cada adapter tem suite de testes específica (além do conformance genérico)
- [ ] Spec `SPEC-HARNESS-ADAPTER.md` amendada para v0.2.0 baseado em friction real
- [ ] Changelog documentando o que mudou entre v0.1.0 e v0.2.0
- [ ] Examples adicionais funcionando:
  - [ ] `examples/03-langgraph-on-wake/`
  - [ ] `examples/04-crewai-on-wake/`
  - [ ] `examples/05-pydantic-ai-on-wake/`
- [ ] Blog post: "How 3 frameworks plug into Wake" publicado em docs/blog/
- [ ] Decisão: lock v1.0 ou v0.3.0 (continuar iterando)

---

## Deliverables

### Pacotes Python adicionais

```
wake-adapter-langgraph           # implementação completa
wake-adapter-crewai              # implementação completa
wake-adapter-pydantic-ai         # implementação completa
```

### Estrutura

```
adapters/
├── claude-sdk/                  # da Phase 2
├── langgraph/
│   ├── pyproject.toml
│   ├── src/wake_adapter_langgraph/
│   │   ├── __init__.py
│   │   ├── adapter.py
│   │   ├── event_mapping.py     # state ↔ events
│   │   └── tool_injection.py    # tools.execute() → LangChain tool node
│   └── tests/
│       ├── test_conformance.py
│       ├── test_simple_graph.py
│       ├── test_react_agent.py
│       └── test_langchain_tools.py
├── crewai/
│   ├── pyproject.toml
│   ├── src/wake_adapter_crewai/
│   │   ├── __init__.py
│   │   ├── adapter.py
│   │   └── callback_hook.py
│   └── tests/
│       └── ...
└── pydantic-ai/
    ├── pyproject.toml
    ├── src/wake_adapter_pydantic_ai/
    │   └── ...
    └── tests/
        └── ...

docs/
├── blog/
│   └── 2026-XX-three-frameworks-on-wake.md
└── SPEC-HARNESS-ADAPTER.md      # v0.2.0
```

---

## Tasks detalhadas

### LangGraph adapter (5 dias)

#### T3.1 — Estudar LangGraph internals (1d)

Foco em:
- `StateGraph` lifecycle e compilation
- `add_node`, `add_edge`, `add_conditional_edges`
- `astream` vs `ainvoke`
- Checkpointers (não usar — Wake é o checkpoint)
- Tool nodes (`ToolNode`, `create_react_agent`)
- Como interceptar tool calls

Entregar: doc interno `notes/langgraph-internals.md`.

#### T3.2 — Implementar LangGraphAdapter base (1d)

```python
class LangGraphAdapter:
    name = "langgraph"
    version = "0.1.0"
    compatibility = "wake-harness-adapter@^0.1"

    def __init__(self, graph: StateGraph, state_key: str = "messages"):
        self.graph = graph
        self.state_key = state_key

    async def step(self, ctx, events, tools):
        initial_state = self._events_to_state(await events.all(), tools)
        compiled = self.graph.compile()

        async for new_state in compiled.astream(initial_state):
            for ev in self._state_diff_to_events(new_state):
                yield ev
```

#### T3.3 — Event ↔ State mapping (1d)

`event_mapping.py`:

```python
def events_to_state(events: list[Event], state_key: str) -> dict:
    messages = []
    for ev in events:
        if ev.type == "user.message":
            messages.append(HumanMessage(content=ev.payload["content"]))
        elif ev.type == "assistant.message":
            messages.append(AIMessage(content=ev.payload["content"]))
        elif ev.type == "tool_use":
            # adiciona como AIMessage com tool_calls
            ...
        elif ev.type == "tool_result":
            messages.append(ToolMessage(...))
    return {state_key: messages}

def state_diff_to_events(prev_state, new_state, state_key) -> list[Event]:
    # detecta novos messages no state e converte
    ...
```

#### T3.4 — Tool injection (1d)

LangGraph espera tools como BaseTool. Wake quer tools via `tools.execute()`. Solução: wrapper:

```python
def wrap_wake_tools_as_langchain(tools: ToolRegistry) -> list[BaseTool]:
    return [WakeToolWrapper(t, tools) for t in tools.list()]

class WakeToolWrapper(BaseTool):
    def _run(self, **kwargs):
        return asyncio.run(self.tools.execute(self.name, kwargs))
```

Injetar nessas tools no `ToolNode` do graph.

#### T3.5 — Tests LangGraph adapter (1d)

- Test simple graph (model → END)
- Test ReAct (create_react_agent)
- Test conditional edges
- Test com LangChain tools
- Conformance suite full

### CrewAI adapter (4 dias)

#### T3.6 — Estudar CrewAI internals (1d)

- `Crew`, `Agent`, `Task`
- `kickoff_async` lifecycle
- Callbacks (`step_callback`, `task_callback`)
- Tools no CrewAI (`BaseTool`, `tool` decorator)

Entregar: doc interno `notes/crewai-internals.md`.

#### T3.7 — Implementar CrewAIAdapter (2d)

```python
class CrewAIAdapter:
    def __init__(self, crew_factory: Callable[[str], Crew]):
        self.crew_factory = crew_factory

    async def step(self, ctx, events, tools):
        latest = await events.latest(type="user.message")
        crew = self.crew_factory(latest.payload["content"])

        # injeta event emission via callbacks
        crew.step_callback = self._make_step_callback()
        crew.task_callback = self._make_task_callback()

        # injeta tools via wrapper
        self._inject_tools(crew, tools)

        result = await crew.kickoff_async()
        yield Event(type="assistant.message",
                    payload={"content": [{"type": "text", "text": result.raw}]})
```

#### T3.8 — Tests CrewAI adapter (1d)

- Simple crew (1 agent, 1 task)
- Multi-agent crew (researcher + writer)
- Tasks com dependencies
- Conformance suite

### Pydantic AI adapter (3 dias)

#### T3.9 — Estudar Pydantic AI internals (0.5d)

- `Agent` class
- Tool decorators
- Run loop (`run`, `run_sync`, `run_stream`)
- Capabilities (v1.71+)

Entregar: doc interno `notes/pydantic-ai-internals.md`.

#### T3.10 — Implementar PydanticAIAdapter (2d)

```python
class PydanticAIAdapter:
    def __init__(self, agent: PydanticAgent):
        self.agent = agent

    async def step(self, ctx, events, tools):
        # converte events em context Pydantic AI
        message_history = self._events_to_message_history(events)

        # injeta tools
        self._register_wake_tools(self.agent, tools)

        # run
        result = await self.agent.run(
            user_prompt=latest_user_message,
            message_history=message_history,
        )

        # converte result em events
        for ev in self._result_to_events(result):
            yield ev
```

#### T3.11 — Tests Pydantic AI adapter (0.5d)

- Typed agent simples
- Agent com tools
- Streaming
- Conformance suite

### Cross-cutting (3 dias)

#### T3.12 — Coletar friction points e propor amendments (1d)

Durante implementação dos 3 adapters, manter doc `notes/spec-friction.md`:

- "ABI assume X mas LangGraph espera Y"
- "Conformance test Z é ambíguo"
- "Falta primitiva W"

Ao fim, transformar em proposta de v0.2.0.

#### T3.13 — Atualizar SPEC-HARNESS-ADAPTER.md → v0.2.0 (1d)

Aplicar amendments. Manter changelog explícito:

```markdown
## v0.2.0 — 2026-XX-XX

### Added
- `compatibility` field obrigatório
- `lifecycle` event `paused`

### Changed
- `step()` retorno agora é `AsyncIterator[Event]` (era `list[Event]`)

### Fixed
- Ambiguity em conformance test `parallel_tools`
```

#### T3.14 — Examples 03, 04, 05 (1d)

Três exemplos rodáveis, um por framework.

#### T3.15 — Blog post: "How 3 frameworks plug into Wake" (4h)

~1500 palavras. Mostra:
- Diagrama da arquitetura
- Code snippet de cada adapter
- Friction encontrada
- Como spec evoluiu

Publicar em `docs/blog/` e crosspost em Hacker News, dev.to, Medium.

#### T3.16 — Decisão: lock v1.0 ou v0.3.0 (4h)

Reunião / decisão técnica:

- **Lock v1.0** se as 3 implementações foram tranquilas e spec não mudou muito
- **Continuar v0.3.0** se ainda há fricção e spec parece imatura

Documentar decisão em `phases/decisions/spec-lock-decision.md`.

---

## Riscos e mitigações

### R3.1 — LangGraph internal API mudou entre versões
**Probabilidade:** alta (LangGraph se move rápido)
**Impacto:** alto (adapter pode quebrar)
**Mitigação:**
- Pin LangGraph version no pyproject (ex: `langgraph>=1.0,<2.0`)
- Documentar range suportado claramente
- Testes de integração contra latest a cada PR

### R3.2 — CrewAI callbacks API instável
**Probabilidade:** média
**Impacto:** médio
**Mitigação:**
- Pin CrewAI version
- Se callbacks faltarem, monkey-patch como último recurso

### R3.3 — Pydantic AI ainda é jovem, breaking changes
**Probabilidade:** média-alta
**Impacto:** médio
**Mitigação:**
- Pin >=1.0 e seguir releases de perto
- Comunidade Pydantic AI é responsiva — engajar mantenedores

### R3.4 — Algum framework não cabe na interface (falha de generalidade)
**Probabilidade:** baixa-média
**Impacto:** alto (impacta tese inteira)
**Mitigação:**
- Esse é o sinal mais importante desta fase
- Se aparecer, NÃO força-encaixe — amend spec
- Se nem amendment resolve, considerar: a tese está errada?

### R3.5 — Conformance suite revela bug no Claude SDK adapter
**Probabilidade:** média
**Impacto:** baixo (correção localizada)
**Mitigação:**
- Bug fix prioritário
- Adicionar test case ao conformance suite

### R3.6 — Tempo subestimado
**Probabilidade:** alta (3 adapters em 3 semanas é apertado)
**Impacto:** médio
**Mitigação:**
- Buffer de 30% built-in
- Se ultrapassar, cortar Pydantic AI adapter (deixa pra depois)
- LangGraph e CrewAI são prioridade absoluta (massa crítica)

---

## Decisões adiadas

- ❌ Postgres backend (Phase 4)
- ❌ sandbox-runtime backend (Phase 4)
- ❌ Vault (Phase 4)
- ❌ LiteLLM (Phase 4)
- ❌ MAF adapter (Day-30+ roadmap)
- ❌ OpenAI Agents SDK adapter (Day-30+ roadmap)
- ❌ AutoGen adapter (Day-30+ roadmap)

---

## Definition of Done

- [ ] Todos os Exit Criteria checkados
- [ ] 3 adapters publicados como packages instaláveis
- [ ] Conformance suite passa 100% em todos os 4 adapters (incluindo Claude SDK regression)
- [ ] CI green
- [ ] Blog post publicado
- [ ] Spec v0.2.0 (ou v1.0) tagueada
- [ ] Tag `v0.0.3-spec-validated` em git
- [ ] Status em `phases/README.md` atualizado

---

## Métricas de sucesso

| Métrica | Mínimo | Meta |
|---|---|---|
| Frameworks com adapter completo | 3 | 3 |
| Conformance pass rate | 100% | 100% |
| Amendments na spec entre v0.1.0 e v0.2.0 | 0-3 | 1-5 |
| Stars (orgânicos + blog) | +100 | +500 |
| Frameworks que fizeram repost / endorsement | 0 | 1-2 |
| Issues abertas por usuários após blog | n/a | 5-10 |

---

## After this phase

→ [Phase 4: Production Stack](./PHASE-4-production-stack.md) — substituir SQLite por Postgres, Docker por sandbox-runtime, adicionar Vault, LiteLLM, agentgateway. Tornar Wake production-ready para self-host multi-node.
