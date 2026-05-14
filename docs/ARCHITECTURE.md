# ARCHITECTURE

Como Wake funciona tecnicamente. Este doc cobre as primitivas, o fluxo de execução, os componentes e os pontos de extensão.

---

## Modelo de quatro primitivas

Igual ao Managed Agents:

| Primitiva | O que é |
|---|---|
| **Agent** | Configuração reusável: modelo + system prompt + tools + MCP servers + skills |
| **Environment** | Template de container: imagem base + pacotes + network policy |
| **Session** | Execução de um Agent num Environment, rastreada como state machine |
| **Event** | Mensagem imutável no log (user message, assistant response, tool call, etc.) |

Esses quatro são os endpoints públicos da API REST.

---

## Diagrama de blocos

```
                              ┌───────────────────────┐
                              │      CLIENT           │
                              │  CLI / SDK / HTTP     │
                              └───────────┬───────────┘
                                          │
                                          ▼
                              ┌───────────────────────┐
                              │     API Server        │
                              │  /v1/agents           │
                              │  /v1/environments     │
                              │  /v1/sessions         │
                              │  /v1/sessions/:id/    │
                              │      events           │
                              │      stream           │
                              └───────────┬───────────┘
                                          │
            ┌─────────────────────────────┼─────────────────────────────┐
            ▼                             ▼                             ▼
   ┌────────────────┐         ┌────────────────────┐         ┌────────────────┐
   │  Postgres      │         │   Event Log        │         │  Pub/Sub       │
   │  (catalog)     │         │   (append-only)    │         │  (SSE fanout)  │
   │  agents,       │         │   per-session      │         │  Redis/NATS    │
   │  environments  │         │   ordered          │         │                │
   └────────────────┘         └────────────────────┘         └────────────────┘
                                          │
                                          ▼
                              ┌───────────────────────┐
                              │   Harness Worker      │
                              │   stateless           │
                              │   wake/step/emit      │
                              └───────────┬───────────┘
                                          │
              ┌───────────────────────────┼───────────────────────────┐
              ▼                           ▼                           ▼
    ┌──────────────────┐        ┌──────────────────┐        ┌──────────────────┐
    │ LLM Provider     │        │  Tool Router     │        │  Vault + Proxy   │
    │ via LiteLLM      │        │  built-in,       │        │  egress filter   │
    │ Claude/OpenAI/   │        │  MCP, custom     │        │  cred injection  │
    │ local/etc.       │        │                  │        │                  │
    └──────────────────┘        └────────┬─────────┘        └──────────────────┘
                                         │
                                         ▼
                               ┌────────────────────┐
                               │  Sandbox Runtime   │
                               │  - sandbox-runtime │
                               │  - Docker          │
                               │  - Firecracker     │
                               │  - gVisor          │
                               └────────────────────┘
```

---

## O insight central: brain/hands decoupling

A Anthropic descreve isso em [Scaling Managed Agents](https://www.anthropic.com/engineering/managed-agents). Wake adota integralmente.

### Tentativa ingênua (rejeitada)

Tudo num container só: harness + sandbox + state. Simples no diagrama, péssimo na prática:

- Container morre → sessão morre
- Debugar exige shell no container, expõe dados
- Cliente em VPC privada exige peering ou self-host inteiro

### Arquitetura correta

Três abstrações separadas:

```
Session  = event log durável  (FORA do container)
Harness  = loop stateless     (FORA do container)
Sandbox  = container/runtime  (efêmero, é uma tool)
```

O harness invoca o sandbox por uma interface unificada: `execute(name, input) → string`. O sandbox pode ser:

- Container Docker
- Sandbox-runtime do anthropic-experimental
- Firecracker microVM
- gVisor
- Máquina remota via SSH
- Outro sistema entirely

O harness não sabe. Não precisa saber.

---

## Ciclo de vida de uma sessão

### Estados possíveis (idêntico ao Managed Agents)

```
idle         — esperando input (criada, ou após responder)
running      — harness ativo
rescheduling — erro transiente, retry automático
terminated   — encerrada (sucesso, erro irrecuperável ou interrupt)
```

### Fluxo end-to-end

```
1. cliente: POST /v1/sessions
   → session criada em estado `idle`
   → nenhum container provisionado ainda

2. cliente: POST /v1/sessions/:id/events
   body: { type: "user.message", content: [...] }
   → evento anexado ao log
   → session passa pra `running`
   → harness worker recebe wake(sessionId)

3. harness:
   - getEvents(sessionId)
   - construir mensagens pro LLM
   - chamar LLM via LiteLLM
   - stream da resposta → emitEvent(assistant.delta) × N
   - se tool_use:
     - resolve tool pelo Tool Router
     - se precisa sandbox e não existe → provision()
     - executa
     - emitEvent(tool_result)
     - volta pro step do LLM
   - se stop_reason == "end_turn":
     - emitEvent(assistant.message final)
     - session volta pra `idle`

4. cliente: GET /v1/sessions/:id/stream
   → SSE conectado ao Pub/Sub
   → recebe eventos em tempo real

5. (opcional) cliente: POST /v1/sessions/:id/events
   body: { type: "user.message", content: "continue X" }
   → loop reinicia
```

---

## Provisionamento preguiçoso de container

Sessão criada não significa container existente. Container existe quando uma tool sandboxed é chamada pela primeira vez:

```python
# pseudocódigo no Tool Router
async def execute(tool_name, input, session):
    tool = registry.get(tool_name)

    if tool.requires_sandbox:
        if session.sandbox is None:
            session.sandbox = await provision_sandbox(session.environment)
        return await session.sandbox.execute(tool_name, input)
    else:
        # tools sem sandbox (web_search, MCP HTTP, etc.) rodam fora
        return await tool.execute(input)
```

**Consequência:** sessões que só fazem web_search ou conversação nunca ganham container. Custo = zero.

**Métrica que isso desbloqueia:** TTFT (time-to-first-token) idêntico à API Messages crua, mesmo em sessões "longas." Anthropic reportou redução de 60% no p50 e >90% no p95.

---

## Resume após morte do harness

Cenário: harness está no meio de um step. Container provisionado. LLM em streaming. De repente, harness OOM.

```
T+0  harness worker dies
T+1  watchdog detecta (heartbeat lost)
T+2  novo harness worker pega o lock da sessão
T+3  new_harness.wake(sessionId)
T+4  events = getEvents(sessionId)  # tudo até onde tinha sido gravado
T+5  reconstroi contexto
T+6  decide próximo passo:
     - se último evento é tool_result completo → continua step do LLM
     - se último evento é tool_call sem result → re-executa tool (idempotência)
     - se último evento é assistant.delta parcial → re-pede ao LLM
T+7  sessão continua
```

**Crítico:** tools precisam ser idempotentes onde possível. Tools com side effects (POST, write_file) precisam de tool_call_id para deduplificação no nível do Tool Router.

---

## Tool Router e Tool ABI

Tools são primeira classe. Toda tool implementa:

```python
class Tool(Protocol):
    name: str
    schema: JSONSchema  # spec do input
    requires_sandbox: bool
    permission: PermissionPolicy

    async def execute(self, input: dict, ctx: ToolContext) -> ToolResult: ...
```

Origens de tools:

| Tipo | Origem | Roda onde |
|---|---|---|
| Built-in | Wake | Sandbox (bash, file_ops) ou host (web_search) |
| MCP stdio | `mcp_servers` no Agent | Inside sandbox, communication via stdio |
| MCP HTTP | `mcp_servers` no Agent | Externamente, via agentgateway |
| Custom | Definida pelo usuário | Host por default, opt-in sandbox |

O **agentgateway** (Linux Foundation) faz a ponte para MCP HTTP/SSE com autenticação via vault.

---

## Vault + proxy de credenciais

O harness nunca toca em credencial. O fluxo é:

```
1. user cria vault entry:
   wake vault add github_token --provider github --oauth
   → OAuth flow no browser
   → token armazenado no Infisical Agent Vault

2. user cria sessão referenciando vault:
   wake session create --agent X --vault github_token

3. harness chama tool autenticada:
   await tools.execute("github.create_pr", {...})

4. tool resolve via egress proxy:
   - proxy recebe request com placeholder no Authorization header
   - proxy busca token real no vault
   - proxy injeta no header
   - proxy faz a chamada externa

5. response volta pelo proxy:
   - tokens removidos de qualquer eco (defensivo)
   - response retornada ao tool
   - tool retorna ao harness
```

O harness emite o evento `tool_result` sem nunca ter visto o token. Mesmo se o log for vazado, não há credencial nele.

---

## Event log: formato e durabilidade

Cada sessão tem um event log próprio. Append-only. Eventos têm:

```typescript
type Event = {
  id: string;            // ULID, monotonic
  session_id: string;
  seq: number;           // posição na sessão (0, 1, 2, ...)
  type: EventType;
  payload: object;       // depende do type
  created_at: string;    // ISO 8601
  parent_id?: string;    // para hierarquia (tool_result aponta pra tool_use)
}
```

Storage: Postgres (Day-1), com flag para alternativas (SQLite local, Kafka, S3 + index).

Garantias:

- **Ordenação total por sessão** (não global)
- **Imutabilidade** (eventos não atualizam, apenas append)
- **Durabilidade** (fsync antes de ACK ao harness)
- **Idempotência via tool_call_id** (dedupe se harness re-emite)

Schema completo em [SPEC-EVENT-SCHEMA.md](./SPEC-EVENT-SCHEMA.md).

---

## HarnessAdapter — o ponto de extensão central

Tudo descrito até aqui assume um harness Wake-nativo. Mas o ponto da arquitetura é que **qualquer harness conforme a interface roda**.

```python
class HarnessAdapter(Protocol):
    async def step(
        self,
        ctx: SessionContext,
        events: EventStream,
        tools: ToolRegistry,
    ) -> AsyncIterator[Event]:
        """
        Roda um step da sessão.

        Recebe: contexto da sessão, stream de eventos (já gravados),
                registro de tools disponíveis.
        Retorna: stream de novos eventos a serem gravados.
        Pode encerrar a qualquer momento; será chamado novamente.
        """
        ...
```

Adapters de referência:

- `wake.adapters.claude_sdk` — wrapper sobre `anthropic.Anthropic` direto
- `wake.adapters.langgraph` — wrapper sobre `langgraph.graph.StateGraph`
- `wake.adapters.crewai` — wrapper sobre `crewai.Crew`
- `wake.adapters.pydantic_ai` — wrapper sobre `pydantic_ai.Agent`

Spec completa em [SPEC-HARNESS-ADAPTER.md](./SPEC-HARNESS-ADAPTER.md).

---

## Replay e fork

Replay determinístico:

```bash
wake session replay session_xyz \
  --from-event 47 \
  --to-fork-as session_debug001
```

Como funciona:

1. Lê events 0..47 do source
2. Cria nova session com os mesmos events
3. Reprovisiona container (lazy)
4. Chama harness com o mesmo HarnessAdapter, mesmo modelo, mesma seed (se snapshotada)
5. A partir do event 47, harness segue normalmente — mas é uma nova trilha

LLM amostragem é estocástica. Para determinismo total:

- Wake pode (opcionalmente) snapshotar a resposta original e replayar — útil pra debug puro
- Ou pode pedir nova amostragem — útil pra explorar alternativas

CLI:

```bash
wake session replay XYZ --from 47 --use-snapshots  # determinístico
wake session replay XYZ --from 47 --resample       # nova amostragem
```

---

## Sandbox layer

Wake suporta múltiplos backends de sandbox via adapter:

```python
class SandboxAdapter(Protocol):
    async def provision(self, env: Environment) -> SandboxHandle: ...
    async def execute(self, handle: SandboxHandle, tool: str, input: dict) -> ToolResult: ...
    async def destroy(self, handle: SandboxHandle) -> None: ...
```

Backends planejados:

- `wake.sandbox.docker` — Day-1, Docker simples (baixa segurança, alta compat)
- `wake.sandbox.sandbox_runtime` — sandbox-runtime do anthropic-experimental (bubblewrap+seccomp+proxy)
- `wake.sandbox.firecracker` — microVMs (futuro, alta segurança)
- `wake.sandbox.gvisor` — kernel userspace (futuro, alta segurança)

User escolhe via Environment config:

```yaml
environment:
  name: my-env
  sandbox:
    backend: sandbox-runtime  # default; alternativas: docker, firecracker, gvisor
    network:
      mode: limited
      allowed_hosts: [github.com, pypi.org]
```

---

## Multi-tenant e concorrência

Workspace = fronteira de isolamento de dados. `organization_id` agrupa
workspaces; `workspace_id` escopa agents, environments, sessions, events,
SSE, replay e métricas. Adaptadores de produto podem mapear customer,
projeto, conta ou tenant para esses campos sem depender de metadata.

Sessão = unidade de execução dentro do workspace. Cada sessão tem:

- Event log próprio (por session_id)
- Container próprio (se provisionado)
- Vault scope próprio
- Permission policy própria

Múltiplos harness workers podem rodar concorrente, cada um pegando um session_id por vez via lock advisory (Postgres `pg_try_advisory_lock`).

Para escala alta: harness workers em FaaS / Kubernetes Jobs / qualquer scheduler.

---

## Observabilidade

Wake **não embute** observability. Mas garante que o event log é um stream OpenTelemetry-compatível:

- Cada event emite um span
- Tool calls têm child spans
- LLM calls têm input_tokens / output_tokens / cost
- Erros têm exception attributes

Consumidores plugáveis:

- Langfuse, Phoenix, Helicone, Braintrust — consomem via OTel
- LangSmith — via adapter custom
- Datadog/NewRelic — via OTel collector

---

## Compatibilidade superficial com Managed Agents API

A API REST de Wake tem endpoints idênticos onde semanticamente possível:

| Endpoint Managed Agents | Endpoint Wake |
|---|---|
| `POST /v1/agents` | `POST /v1/agents` |
| `POST /v1/environments` | `POST /v1/environments` |
| `POST /v1/sessions` | `POST /v1/sessions` |
| `POST /v1/sessions/:id/events` | `POST /v1/sessions/:id/events` |
| `GET /v1/sessions/:id/stream` | `GET /v1/sessions/:id/stream` |

Beta header `managed-agents-2026-04-01` é aceito mas não exigido (compatibilidade superficial; Wake é GA-stable na sua própria versão).

Diferenças deliberadas (documentadas em [COMPARISON.md](./COMPARISON.md)):

- Wake suporta `harness_adapter` na criação de Agent (Managed Agents só Claude)
- Wake suporta múltiplos backends de sandbox
- Wake é self-host

---

## Resumo: as 5 peças que Wake constrói

1. **API Server** (REST + SSE) — Postgres + harness workers
2. **Event log** — store apenas Wake, schema canônico
3. **Tool Router** — interface unificada para tools
4. **HarnessAdapter ABI** — spec aberta + adapters de referência
5. **CLI + SDKs** — UX para dev local e cliente programático

Tudo o resto pluga: sandbox-runtime, Infisical Vault, LiteLLM, MCP, agentgateway.
