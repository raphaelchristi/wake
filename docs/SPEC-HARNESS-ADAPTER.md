# SPEC: HarnessAdapter v0.1.0

> Interface que permite qualquer harness rodar no runtime Wake.

Status: **Draft v0.1.0** — sujeito a revisão até v1.0.

---

## Motivação

Frameworks de agentes (LangGraph, CrewAI, Pydantic AI, Claude Agent SDK) trazem cada um seu próprio loop de execução, sua própria abstração de tool, seu próprio modelo de state. Wake oferece um substrato (event log, sandbox, vault, lifecycle) que beneficia todos.

A `HarnessAdapter` é a interface que conecta um framework qualquer ao substrato Wake. Quem implementa a interface, roda no Wake. Sem mais.

Analogia: WSGI (Python) ou Servlet (Java) — uma interface estável que separa framework de servidor.

---

## Visão de alto nível

```
┌──────────────────────────────────────────────┐
│  WAKE RUNTIME                                │
│                                              │
│  ┌──────────────────┐  ┌──────────────────┐ │
│  │  Event Log       │  │  Tool Registry   │ │
│  └──────────────────┘  └──────────────────┘ │
│                                              │
│  ┌──────────────────────────────────────┐   │
│  │  Session Context                      │   │
│  │  - session_id, agent_config           │   │
│  │  - vault handle, sandbox handle       │   │
│  └──────────────────────────────────────┘   │
│                       ▲                      │
└───────────────────────┼──────────────────────┘
                        │
                        │ HarnessAdapter.step(...)
                        │
       ┌────────────────┼────────────────┐
       │                │                │
   LangGraph        Pydantic AI      Claude SDK
   Adapter          Adapter          Adapter
       │                │                │
   StateGraph       Agent            Anthropic
   (user code)      (user code)      (user code)
```

---

## A interface (Python)

```python
from typing import Protocol, AsyncIterator
from wake.types import SessionContext, EventStream, ToolRegistry, Event

class HarnessAdapter(Protocol):
    """
    Implementado por quem quer expor um harness ao runtime Wake.
    """

    name: str
    """Identificador único do adapter (ex: 'langgraph', 'crewai')."""

    version: str
    """Versão semver do adapter."""

    async def step(
        self,
        ctx: SessionContext,
        events: EventStream,
        tools: ToolRegistry,
    ) -> AsyncIterator[Event]:
        """
        Executa um passo de raciocínio.

        Recebe:
          - ctx: contexto da sessão (id, agent config, sandbox handle, vault handle)
          - events: stream read-only de eventos já gravados na sessão
          - tools: registro de tools disponíveis para esta sessão

        Emite:
          - eventos novos a serem gravados no log

        Garantias do runtime:
          - events é o log COMPLETO da sessão até este ponto
          - tools já estão filtradas por permission policy
          - ctx.sandbox e ctx.vault podem ser None se não provisionados
          - eventos emitidos são gravados ANTES de serem visíveis ao próximo step

        Garantias do adapter:
          - step() pode ser interrompido (asyncio.CancelledError) e deve limpar
          - step() pode ser chamado múltiplas vezes para a mesma sessão
          - eventos emitidos têm seq monotonicamente crescente (runtime atribui se omitido)
          - tools são invocadas via tools.execute(name, input) — adapter NÃO chama
            funções diretamente
        """
        ...

    async def on_lifecycle(
        self,
        ctx: SessionContext,
        event: LifecycleEvent,
    ) -> None:
        """
        Notificação opcional de eventos do lifecycle da sessão.

        LifecycleEvent ∈ {created, resumed, interrupted, terminated}.

        Adapter pode usar para inicializar/limpar state interno do framework
        (ex: criar Crew, fechar conexões).

        Default: no-op.
        """
        ...
```

---

## A interface (TypeScript)

```typescript
import type {
  SessionContext,
  EventStream,
  ToolRegistry,
  Event,
  LifecycleEvent,
} from "@wake/types";

export interface HarnessAdapter {
  readonly name: string;
  readonly version: string;

  step(
    ctx: SessionContext,
    events: EventStream,
    tools: ToolRegistry,
  ): AsyncIterableIterator<Event>;

  onLifecycle?(
    ctx: SessionContext,
    event: LifecycleEvent,
  ): Promise<void>;
}
```

Semântica idêntica à Python. Wake mantém parity entre as duas linguagens.

---

## SessionContext

```python
@dataclass
class SessionContext:
    session_id: str
    agent_id: str
    agent_version: int
    agent_config: AgentConfig         # model, system, tools, mcp_servers
    environment_id: str | None
    sandbox: SandboxHandle | None     # None se não provisionado
    vault: VaultHandle | None         # None se sessão sem vault
    metadata: dict[str, str]          # user metadata
```

`SandboxHandle` e `VaultHandle` são tokens opacos. Adapter não opera sobre eles diretamente — passa para `tools.execute()` que sabe como usar.

---

## EventStream

```python
class EventStream:
    async def all(self) -> list[Event]: ...
    async def since(self, seq: int) -> list[Event]: ...
    async def latest(self, type: EventType | None = None) -> Event | None: ...
    async def count(self) -> int: ...
```

Read-only. Mutação só via emissão pela própria `step()`.

---

## ToolRegistry

```python
class ToolRegistry:
    def list(self) -> list[ToolDescriptor]: ...
    def get(self, name: str) -> ToolDescriptor: ...
    async def execute(self, name: str, input: dict, *, tool_use_id: str) -> ToolResult: ...
```

Adapter chama `tools.execute()` em vez de chamar implementações diretamente. Isso permite:

- Permission policy enforcement
- Sandbox routing transparente
- Vault credential injection
- Tool call logging automático
- Idempotência via tool_use_id

---

## Event emission (o que o adapter pode emitir)

| Event type | Quando usar |
|---|---|
| `assistant.message` | Resposta final do agente |
| `assistant.thinking` | Conteúdo de extended thinking (opcional) |
| `assistant.delta` | Chunk parcial em streaming |
| `tool_use` | Antes de executar tool (necessário para audit) |
| `tool_result` | Após executar tool (idem) |
| `pause_turn` | Indicação que turno está pausado (long-running) |
| `status` | Mudança de status (idle/running/...) |
| `error` | Erro recuperável; harness continua |
| `artifact` | Arquivo gerado, blob, URL, etc. |

Spec completa em [SPEC-EVENT-SCHEMA.md](./SPEC-EVENT-SCHEMA.md).

Eventos NÃO permitidos do adapter:

- `user.message` — só clients criam
- `interrupt` — só clients criam

---

## Exemplo: Claude SDK adapter (referência)

```python
from anthropic import AsyncAnthropic
from wake.adapters import HarnessAdapter
from wake.types import SessionContext, EventStream, ToolRegistry, Event

class ClaudeSDKAdapter:
    name = "claude-sdk"
    version = "0.1.0"

    def __init__(self, client: AsyncAnthropic | None = None):
        self.client = client or AsyncAnthropic()

    async def step(self, ctx, events, tools):
        messages = self._events_to_messages(await events.all())

        response = await self.client.messages.create(
            model=ctx.agent_config.model,
            system=ctx.agent_config.system,
            messages=messages,
            tools=[t.to_anthropic_schema() for t in tools.list()],
            stream=True,
        )

        tool_uses_in_progress = []

        async for chunk in response:
            if chunk.type == "content_block_delta":
                if chunk.delta.type == "text_delta":
                    yield Event(type="assistant.delta",
                                payload={"text": chunk.delta.text})
                elif chunk.delta.type == "input_json_delta":
                    # acumula tool_use input
                    ...

            elif chunk.type == "content_block_stop":
                block = chunk.content_block
                if block.type == "tool_use":
                    yield Event(type="tool_use",
                                payload={"name": block.name,
                                         "input": block.input,
                                         "tool_use_id": block.id})
                    tool_uses_in_progress.append(block)

            elif chunk.type == "message_stop":
                if chunk.stop_reason == "end_turn":
                    yield Event(type="assistant.message",
                                payload={"content": self._collect_blocks()})
                    return
                elif chunk.stop_reason == "tool_use":
                    # executa todas tools, emite tool_results, recursão
                    for tu in tool_uses_in_progress:
                        result = await tools.execute(
                            tu.name, tu.input,
                            tool_use_id=tu.id,
                        )
                        yield Event(type="tool_result",
                                    payload={"tool_use_id": tu.id,
                                             "content": result.content,
                                             "is_error": result.is_error})
                    # continua o step (recursão lógica, mesmo step())
                    async for ev in self.step(ctx, events, tools):
                        yield ev
                    return
```

---

## Exemplo: LangGraph adapter (esboço)

```python
from langgraph.graph import StateGraph
from wake.adapters import HarnessAdapter

class LangGraphAdapter:
    name = "langgraph"
    version = "0.1.0"

    def __init__(self, graph: StateGraph, state_key: str = "messages"):
        self.graph = graph
        self.state_key = state_key

    async def step(self, ctx, events, tools):
        # converte eventos Wake → state inicial do graph
        initial_state = self._events_to_state(await events.all())

        # injeta tools do registry no node de tool execution
        runtime_graph = self._inject_tool_executor(self.graph, tools)

        # roda um superstep
        async for new_state in runtime_graph.astream(initial_state):
            # converte mudanças de state → eventos Wake
            for ev in self._state_diff_to_events(new_state):
                yield ev

    def _events_to_state(self, events):
        # mapeia user.message/assistant.message/tool_use/tool_result
        # para o formato LangChain Messages
        ...

    def _inject_tool_executor(self, graph, tools):
        # substitui o tool node do graph por um proxy que chama tools.execute()
        ...

    def _state_diff_to_events(self, new_state):
        # detecta novas mensagens no state.messages e emite eventos
        ...
```

---

## Exemplo: CrewAI adapter (esboço)

```python
from crewai import Crew
from wake.adapters import HarnessAdapter

class CrewAIAdapter:
    name = "crewai"
    version = "0.1.0"

    def __init__(self, crew_factory):
        """crew_factory: callable that returns a Crew given user input."""
        self.crew_factory = crew_factory

    async def step(self, ctx, events, tools):
        latest_user_msg = await events.latest(type="user.message")

        if not latest_user_msg:
            return

        crew = self.crew_factory(input=latest_user_msg.payload["content"])

        # CrewAI usa callbacks; conectamos pra emitir eventos
        crew.on_agent_thought = lambda agent, thought: \
            self._emit(Event(type="assistant.thinking",
                             payload={"agent": agent.role, "text": thought}))
        crew.on_tool_call = lambda agent, tool_name, tool_input: \
            self._emit(Event(type="tool_use",
                             payload={"agent": agent.role,
                                      "name": tool_name,
                                      "input": tool_input}))

        result = await crew.kickoff_async()

        yield Event(type="assistant.message",
                    payload={"content": result.raw})
```

(Detalhes de callback CrewAI dependem da versão; esboço apenas.)

---

## Requisitos de conformidade

Para um adapter ser **Wake-conformant v0.1.0**:

1. Implementa a interface `HarnessAdapter` (Python ou TS)
2. `step()` é resiliente a cancelamento (cleanup correto)
3. `step()` chama tools EXCLUSIVAMENTE via `tools.execute()`
4. Eventos emitidos seguem o schema canônico (SPEC-EVENT-SCHEMA.md)
5. Adapter é idempotente: chamar `step()` duas vezes na mesma sessão produz comportamento sensato (re-emite ou termina cedo)
6. Adapter publica testes contra a test suite de conformância (`wake-test-conformance`)

Adapters não-conformes podem rodar mas levam o tag `unverified` no registry.

---

## Tabela de adapters de referência

Mantidos no monorepo de Wake:

| Adapter | Framework | Status | Versão suportada |
|---|---|---|---|
| `wake-adapter-claude-sdk` | Anthropic SDK | planned v0.1.0 | anthropic >= 0.50 |
| `wake-adapter-langgraph` | LangGraph | planned v0.1.0 | langgraph >= 1.0 |
| `wake-adapter-crewai` | CrewAI | planned v0.1.0 | crewai >= 1.0 |
| `wake-adapter-pydantic-ai` | Pydantic AI | planned v0.1.0 | pydantic-ai >= 1.0 |
| `wake-adapter-autogen` | Microsoft Agent Framework | planned v0.2.0 | agent-framework >= 1.0 |
| `wake-adapter-openai-sdk` | OpenAI Agents SDK | planned v0.2.0 | openai-agents >= 1.0 |

Adapters de terceiros são bem-vindos. Registry pública (estilo PyPI mas para adapters).

---

## Versionamento

- Spec versionada como `wake-harness-adapter@x.y.z`
- Breaking changes só em major bumps
- Compatibilidade: runtime Wake aceita adapters de versão MAJOR igual; emite warning para minor mais novo
- Adapters declaram versão da spec que implementam no campo `compatibility`

```python
class MyAdapter:
    name = "my-adapter"
    version = "0.1.0"
    compatibility = "wake-harness-adapter@^0.1"
```

---

## Open questions (resolver antes de v1.0)

- **Q1:** Adapters podem ser stateful entre `step()` calls? Default: não (forçar stateless igual harness Wake-nativo). Mas alguns frameworks (CrewAI Crew, LangGraph compiled graph) têm setup caro. Permitir state-via-init?
- **Q2:** Como adapter sinaliza "preciso de tool fora do registry"? `tools.list()` é fixo na sessão ou pode crescer?
- **Q3:** Multi-step interno do adapter — adapter pode chamar `step()` recursivamente sem emitir eventos intermediários? Default: não, mas pode haver casos.
- **Q4:** Pause/resume mid-step — adapter deve checar `ctx.is_cancelled` periodicamente? Como?

Issues serão abertos para cada uma na governance pública.

---

## Próximos passos

1. Implementação de referência `wake-adapter-claude-sdk` como primeiro
2. Test suite de conformância
3. RFC público para revisão da spec antes de v0.1.0 lock
4. Adapters LangGraph e CrewAI para provar generalidade
