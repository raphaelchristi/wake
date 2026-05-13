# Phase 1 — Skeleton

> **Objetivo:** `wake server --local` roda hello-world end-to-end. Persistência em SQLite. Sandbox Docker. Único harness (Anthropic SDK direto, ainda sem HarnessAdapter ABI).

| | |
|---|---|
| **Status** | ⚪ not_started |
| **Duração estimada** | 2 semanas (10 working days) |
| **Dependências** | Phase 0 done (specs locked) |

---

## Por que essa fase existe

Antes de validar a HarnessAdapter ABI (Phase 2) precisamos provar que o substrato base funciona: event log durável, SSE streaming, tool execution em sandbox, lifecycle de sessão. Sem isso, não tem o que adapter plugar.

A regra: **uma coisa de cada vez**. Phase 1 prova substrato. Phase 2 prova abstração.

---

## Entry criteria

- ✅ Phase 0 done (todos os gates cumpridos)
- ✅ Linguagem do runtime decidida (`phases/decisions/runtime-language.md`)
- ✅ Specs frozen em v0.1.0

(Este doc assume **Python** como linguagem default. Se decisão da Phase 0 for diferente, reescrever effort estimates.)

---

## Exit criteria (gates)

Todos verificadamente cumpridos:

- [ ] `pip install -e .` instala o pacote
- [ ] `wake --help` mostra subcomandos
- [ ] `wake server --local` sobe e escuta em :8080
- [ ] API endpoints retornando JSON válido:
  - [ ] POST/GET `/v1/agents`
  - [ ] POST/GET `/v1/environments`
  - [ ] POST/GET `/v1/sessions`
  - [ ] POST `/v1/sessions/:id/events`
  - [ ] GET `/v1/sessions/:id/events`
  - [ ] GET `/v1/sessions/:id/stream` (SSE)
  - [ ] POST `/v1/sessions/:id/interrupt`
- [ ] SQLite event store cria DB e tabelas automaticamente
- [ ] Event log respeita schema canônico de v0.1.0
- [ ] Tools built-in funcionando dentro de container Docker:
  - [ ] `bash`
  - [ ] `file_read`
  - [ ] `file_write`
  - [ ] `file_edit`
- [ ] CLI commands:
  - [ ] `wake server`
  - [ ] `wake agent create/list/get/archive`
  - [ ] `wake environment create/list/get`
  - [ ] `wake session create/send/stream/events/list`
  - [ ] `wake run "<message>"` (atalho one-shot)
- [ ] Anthropic SDK harness loop (não-genérico, hardcoded Anthropic API)
- [ ] Exemplo `01-hello-world/` roda em <2min após `pip install`
- [ ] Exemplo `02-coding-refactor/` roda com bash em container Docker
- [ ] 2 testes de integração passando em CI
- [ ] README quickstart atualizado refletindo realidade

---

## Deliverables

### Estrutura do código

```
src/wake/
├── __init__.py
├── api/                          # FastAPI app
│   ├── __init__.py
│   ├── app.py                    # FastAPI instance
│   ├── routes/
│   │   ├── agents.py
│   │   ├── environments.py
│   │   ├── sessions.py
│   │   └── events.py
│   └── sse.py                    # streaming
├── core/
│   ├── event_log.py              # append-only store
│   ├── session.py                # state machine
│   ├── agent.py
│   └── environment.py
├── store/
│   ├── __init__.py
│   ├── base.py                   # backend interface
│   └── sqlite.py                 # default backend
├── sandbox/
│   ├── __init__.py
│   ├── base.py                   # backend interface
│   └── docker.py                 # default backend
├── tools/
│   ├── __init__.py
│   ├── registry.py
│   ├── builtin/
│   │   ├── bash.py
│   │   ├── file_ops.py
│   │   └── grep.py
│   └── base.py
├── harness/
│   ├── __init__.py
│   └── anthropic.py              # hardcoded Claude loop
├── cli/
│   ├── __init__.py
│   └── main.py                   # typer-based
└── types.py                      # shared types

tests/
├── integration/
│   ├── test_hello_world.py
│   └── test_coding_refactor.py
└── unit/
    └── ...

examples/
├── 01-hello-world/
│   ├── README.md
│   └── run.sh
└── 02-coding-refactor/
    ├── README.md
    ├── wake.yaml
    └── run.sh

pyproject.toml
Dockerfile                         # imagem do server
.github/workflows/
└── ci.yml                         # tests + lint
```

### Distribuição

- Pacote PyPI: `wake-ai` (claim do nome em PyPI cedo)
- Docker image: `wake-ai/wake:0.1.0` (pode esperar Phase 4)

---

## Tasks detalhadas

### T1.1 — Project skeleton + dependencies (2h)

- `pyproject.toml` com deps: fastapi, uvicorn, sqlalchemy, anthropic, typer, docker, sse-starlette, pydantic
- `.gitignore` extras
- `src/wake/__init__.py` com version
- `pytest.ini`, `ruff.toml`, `mypy.ini`

### T1.2 — FastAPI app com stub endpoints (4h)

Cada endpoint retorna 501 inicialmente, mas roteamento + validação Pydantic funcionando.

### T1.3 — SQLite schema + migrations (4h)

```sql
CREATE TABLE agents (...);
CREATE TABLE agent_versions (...);
CREATE TABLE environments (...);
CREATE TABLE sessions (...);
CREATE TABLE events (...);
```

Usar Alembic ou SQLAlchemy direto.

### T1.4 — Event log: append, get, stream (1d)

API interna:

```python
class EventStore:
    async def append(self, session_id, event) -> Event
    async def get_events(self, session_id, *, since: int = 0) -> list[Event]
    async def subscribe(self, session_id) -> AsyncIterator[Event]
```

- `append` é transacional, retorna evento com seq atribuído
- `subscribe` usa Postgres LISTEN/NOTIFY (Phase 4) ou polling SQLite (Phase 1)

### T1.5 — Agent registry (1d)

CRUD + versionamento. Comportamento copia da doc Anthropic:
- update gera nova versão se mudou
- list versions
- archive

### T1.6 — Environment registry (4h)

CRUD simples. Sem versionamento (decisão deliberada matching Anthropic).

### T1.7 — Session state machine (1d)

States: `idle | running | rescheduling | terminated`. Transições atômicas via DB.

```python
class SessionStateMachine:
    async def create(self, agent_id, env_id) -> Session  # → idle
    async def start(self, session_id)                    # idle → running
    async def complete(self, session_id)                 # running → idle
    async def fail(self, session_id, reason)             # → rescheduling/terminated
```

### T1.8 — Tool router com 3 built-ins (1d)

```python
class ToolRegistry:
    def register(self, tool: Tool) -> None
    async def execute(self, name, input, ctx) -> ToolResult
```

Built-ins inicial: `bash`, `file_read`, `file_write`. Cada um roda no sandbox.

### T1.9 — Sandbox adapter Docker (1d)

```python
class DockerSandbox:
    async def provision(self, env: Environment) -> SandboxHandle
    async def execute(self, handle, tool, input) -> ToolResult
    async def destroy(self, handle) -> None
```

Usar `docker` SDK Python. Limitar CPU/memory por session.

### T1.10 — Anthropic harness loop (1d)

Hardcoded loop chamando `client.messages.create`. Lê events → constrói messages → chama LLM → emite events.

Não generalizar ainda (Phase 2). Manter simples.

### T1.11 — CLI com typer (1d)

```python
@app.command()
def server(local: bool = False, port: int = 8080): ...

@app.command()
def run(message: str, agent: str = "default"): ...
```

Tab completion bem-vinda.

### T1.12 — SSE streaming endpoint (4h)

Via `sse-starlette` ou implementação manual. Suportar `Last-Event-ID` para reconnect.

### T1.13 — Exemplo 01: hello world (4h)

```bash
#!/bin/bash
# examples/01-hello-world/run.sh

wake server --local &
SERVER_PID=$!
sleep 2

wake run "Say hello in 3 languages"

kill $SERVER_PID
```

Deve retornar `assistant.message` com 3 idiomas.

### T1.14 — Exemplo 02: coding refactor (4h)

`examples/02-coding-refactor/wake.yaml`:

```yaml
agent:
  name: refactor-bot
  model: claude-opus-4-7
  system: "You refactor code using tools."
  tools: [bash, file_read, file_write]
```

Roda contra um repo de exemplo (também no diretório), verifica que arquivo foi modificado.

### T1.15 — CI básico (2h)

`.github/workflows/ci.yml`:

```yaml
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: pip install -e ".[dev]"
      - run: pytest tests/
      - run: ruff check src/
      - run: mypy src/
```

### T1.16 — README quickstart real (2h)

Substituir o pitch atual por quickstart funcionando:

```bash
pip install wake-ai
wake server --local
wake run "hello world"
```

Com gif/asciinema gravado.

---

## Riscos e mitigações

### R1.1 — SSE + asyncio + harness lifecycle é mais complexo que parece
**Probabilidade:** alta
**Impacto:** médio (atraso 2-3 dias)
**Mitigação:**
- Reservar 2 dias buffer no estimate
- Estudar implementações de referência (FastAPI SSE examples)
- Usar `sse-starlette` em vez de implementar do zero

### R1.2 — Docker como dependência complica onboarding
**Probabilidade:** alta
**Impacto:** baixo (UX, não funcionalidade)
**Mitigação:**
- `wake server --local --no-sandbox` permite rodar sem Docker (modo trusted code)
- Documentar claramente: sandbox é opcional em dev

### R1.3 — Anthropic SDK breaking changes durante Phase 1
**Probabilidade:** baixa
**Impacto:** baixo
**Mitigação:**
- Pin versão do SDK no pyproject
- Testar contra latest a cada PR

### R1.4 — Premature abstraction (criar interfaces antes de ter caso de uso)
**Probabilidade:** média
**Impacto:** médio (refactor em Phase 2)
**Mitigação:**
- **Explicitamente** hardcoded Anthropic harness nesta fase
- Refactor pra HarnessAdapter é Phase 2 (e é tudo bem ter refactor)

### R1.5 — Postgres LISTEN/NOTIFY vs SQLite polling
**Probabilidade:** N/A
**Impacto:** UX (latência de stream)
**Mitigação:**
- SQLite polling com interval 100ms é aceitável em dev
- Postgres LISTEN/NOTIFY entra na Phase 4

### R1.6 — Effort estimates errados (subestimação)
**Probabilidade:** alta (sempre)
**Impacto:** médio
**Mitigação:**
- Buffer de 30% built into 2 semanas (10 working days, 13 reais)
- Se passar do prazo, **não** trabalhar fim de semana; reavaliar escopo

---

## Decisões adiadas (NÃO fazer nesta fase)

- ❌ HarnessAdapter ABI (Phase 2)
- ❌ Adapters para frameworks externos (Phase 3)
- ❌ Postgres backend (Phase 4)
- ❌ sandbox-runtime backend (Phase 4)
- ❌ Vault (Phase 4)
- ❌ LiteLLM (Phase 4)
- ❌ MCP servers (Phase 4)
- ❌ Multi-worker / cluster (Phase 4)
- ❌ Web UI (Day-90 / pacote separado)
- ❌ Memory primitives
- ❌ Multiagent
- ❌ Outcomes

Lista anti-features explícita pra resistir scope creep.

---

## Definition of Done

- [ ] Todos os Exit Criteria checkados
- [ ] CI green
- [ ] Pelo menos 1 outsider rodou `wake run "hello"` com sucesso
- [ ] README atualizado com quickstart real
- [ ] Tag `v0.0.1-skeleton` em git
- [ ] Status em `phases/README.md` atualizado

---

## Métricas de sucesso

| Métrica | Mínimo | Meta |
|---|---|---|
| Tempo para hello-world após `pip install` | <5min | <2min |
| Linhas de código no `src/` | n/a | <3000 LoC |
| Test coverage | ≥70% | ≥85% |
| Stars (orgânicos sem promoção) | n/a | +50 vs Phase 0 |

---

## After this phase

→ [Phase 2: First Adapter](./PHASE-2-first-adapter.md) — abstrair o harness em HarnessAdapter ABI, refatorar o harness Anthropic pra usar a interface, criar test suite de conformância.
