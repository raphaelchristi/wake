# Phase 1 Execution Contract

> Interface contract entre os 3 agents trabalhando Phase 1 em paralelo.
> Cada agent owns paths disjoint. Compartilham apenas types via `src/wake/types.py`.

---

## Divisão de slices

| Agent | Owns | Não toca |
|---|---|---|
| `wake-foundation` | tipos + store + core + lifecycle | api/, tools/, sandbox/, harness/, cli/, examples/ |
| `wake-runtime` | api/ + tools/ + sandbox/ + harness/ | types.py (read-only), store/, core/, cli/, examples/ |
| `wake-cli` | cli/ + examples/ + tests/integration + CI + Dockerfile | tudo de src/wake/ EXCETO importar |

---

## Files ownership

### wake-foundation owns

```
pyproject.toml
src/wake/__init__.py
src/wake/types.py                   ← SHARED, written by foundation
src/wake/store/__init__.py
src/wake/store/base.py              ← interface EventStore, AgentStore, EnvironmentStore, SessionStore
src/wake/store/sqlite.py            ← implementação default
src/wake/core/__init__.py
src/wake/core/agent.py              ← Agent domain object + CRUD logic
src/wake/core/environment.py
src/wake/core/session.py            ← Session domain + state machine
src/wake/core/event_log.py          ← append, get, subscribe (in-process)
tests/unit/test_types.py
tests/unit/test_store.py
tests/unit/test_session.py
tests/unit/test_event_log.py
.gitignore (já existe, pode estender)
```

### wake-runtime owns

```
src/wake/api/__init__.py
src/wake/api/app.py                 ← FastAPI instance
src/wake/api/routes/__init__.py
src/wake/api/routes/agents.py
src/wake/api/routes/environments.py
src/wake/api/routes/sessions.py
src/wake/api/routes/events.py
src/wake/api/sse.py                 ← SSE endpoint
src/wake/tools/__init__.py
src/wake/tools/base.py              ← Tool ABI
src/wake/tools/registry.py
src/wake/tools/builtin/__init__.py
src/wake/tools/builtin/bash.py
src/wake/tools/builtin/file_ops.py  ← file_read + file_write + file_edit
src/wake/sandbox/__init__.py
src/wake/sandbox/base.py            ← SandboxAdapter interface
src/wake/sandbox/docker.py          ← Docker backend default
src/wake/harness/__init__.py
src/wake/harness/anthropic.py       ← hardcoded Anthropic loop (Phase 1 only)
tests/unit/test_api_*.py
tests/unit/test_tools.py
tests/unit/test_sandbox.py
tests/unit/test_harness.py
```

### wake-cli owns

```
src/wake/cli/__init__.py
src/wake/cli/main.py                ← typer app
examples/01-hello-world/README.md
examples/01-hello-world/run.sh
examples/02-coding-refactor/README.md
examples/02-coding-refactor/wake.yaml
examples/02-coding-refactor/run.sh
examples/02-coding-refactor/test_repo/...
tests/integration/__init__.py
tests/integration/test_hello_world.py
tests/integration/test_coding_refactor.py
.github/workflows/ci.yml
Dockerfile
```

---

## SHARED TYPES (autoritativos — wake-foundation define, outros consomem read-only)

Coloque em `src/wake/types.py`. Pydantic v2 ou dataclasses (escolha do foundation, mas consistente).

```python
from __future__ import annotations
from typing import Literal, Any
from datetime import datetime
from pydantic import BaseModel, Field

# ============================================================================
# Event types
# ============================================================================

EventType = Literal[
    "user.message",
    "assistant.message",
    "assistant.thinking",
    "assistant.delta",
    "tool_use",
    "tool_result",
    "pause_turn",
    "status",
    "error",
    "artifact",
    "interrupt",
    "provision",
    "vault.access",
]

class Event(BaseModel):
    id: str                              # ULID 26 chars
    session_id: str
    seq: int                             # monotonic per session
    type: EventType
    payload: dict[str, Any]
    parent_id: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime

# ============================================================================
# Content blocks (matching Anthropic Messages API)
# ============================================================================

class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str

class ToolUseBlock(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any]

class ToolResultBlock(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: list[TextBlock]
    is_error: bool = False

ContentBlock = TextBlock | ToolUseBlock | ToolResultBlock

# ============================================================================
# Agent / Environment / Session
# ============================================================================

SessionStatus = Literal["idle", "running", "rescheduling", "terminated"]

class ModelConfig(BaseModel):
    id: str                              # e.g., "claude-opus-4-7"
    speed: Literal["standard", "fast"] = "standard"
    provider: str = "anthropic"

class ToolConfig(BaseModel):
    type: str                            # "bash" | "file_ops" | "agent_toolset_20260401"
    # additional fields per tool type

class AgentConfig(BaseModel):
    id: str
    name: str
    model: ModelConfig
    system: str | None = None
    tools: list[ToolConfig] = Field(default_factory=list)
    mcp_servers: list[dict] = Field(default_factory=list)
    skills: list[dict] = Field(default_factory=list)
    description: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    version: int = 1
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None

class EnvironmentConfig(BaseModel):
    id: str
    name: str
    config: dict[str, Any]               # type, packages, networking, etc.
    created_at: datetime
    archived_at: datetime | None = None

class Session(BaseModel):
    id: str
    agent_id: str
    agent_version: int
    environment_id: str | None = None
    status: SessionStatus = "idle"
    container_id: str | None = None
    workspace_path: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

# ============================================================================
# Tool ABI (Phase 1 minimal — full version Phase 2)
# ============================================================================

class ToolDescriptor(BaseModel):
    name: str
    description: str
    schema: dict[str, Any]               # JSON Schema for input
    requires_sandbox: bool

class ToolResult(BaseModel):
    content: list[TextBlock]
    is_error: bool = False
    error_code: str | None = None

# ============================================================================
# Sandbox handle (opaque to caller)
# ============================================================================

class SandboxHandle(BaseModel):
    backend: str                         # "docker" | "sandbox-runtime" | ...
    container_id: str
    workspace_path: str
    created_at: datetime
```

---

## INTERFACES (wake-foundation define, outros implementam/consomem)

### EventStore interface (`wake/store/base.py`)

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator
from wake.types import Event, EventType

class EventStore(ABC):
    @abstractmethod
    async def append(
        self,
        session_id: str,
        event_type: EventType,
        payload: dict,
        parent_id: str | None = None,
        metadata: dict | None = None,
    ) -> Event: ...

    @abstractmethod
    async def get(self, session_id: str, since: int = 0) -> list[Event]: ...

    @abstractmethod
    async def get_one(self, event_id: str) -> Event | None: ...

    @abstractmethod
    async def subscribe(self, session_id: str) -> AsyncIterator[Event]: ...

    @abstractmethod
    async def count(self, session_id: str) -> int: ...
```

### AgentStore / EnvironmentStore / SessionStore

Similar pattern: CRUD methods. wake-foundation define interface + sqlite impl.

```python
class AgentStore(ABC):
    @abstractmethod
    async def create(self, name: str, model: ModelConfig, **kwargs) -> AgentConfig: ...

    @abstractmethod
    async def get(self, id: str, version: int | None = None) -> AgentConfig | None: ...

    @abstractmethod
    async def update(self, id: str, version: int, **changes) -> AgentConfig: ...

    @abstractmethod
    async def list(self) -> list[AgentConfig]: ...

    @abstractmethod
    async def archive(self, id: str) -> AgentConfig: ...
```

### SessionStateMachine (`wake/core/session.py`)

```python
class SessionStateMachine:
    def __init__(self, store: SessionStore, event_store: EventStore): ...

    async def create(self, agent_id: str, environment_id: str | None) -> Session:
        """Create session in idle state."""

    async def start(self, session_id: str) -> None:
        """idle → running. Idempotent."""

    async def complete(self, session_id: str) -> None:
        """running → idle. Emits status event."""

    async def fail(self, session_id: str, reason: str, transient: bool = True) -> None:
        """running → rescheduling (if transient) or terminated."""

    async def terminate(self, session_id: str) -> None:
        """* → terminated."""

    async def get(self, session_id: str) -> Session: ...
```

### Tool ABI (`wake/tools/base.py`) — owned by wake-runtime

```python
from abc import ABC, abstractmethod
from wake.types import ToolDescriptor, ToolResult

class Tool(ABC):
    @property
    @abstractmethod
    def descriptor(self) -> ToolDescriptor: ...

    @abstractmethod
    async def execute(
        self,
        input: dict,
        sandbox: SandboxHandle | None,
    ) -> ToolResult: ...
```

### SandboxAdapter (`wake/sandbox/base.py`) — owned by wake-runtime

```python
class SandboxAdapter(ABC):
    @abstractmethod
    async def provision(self, env: EnvironmentConfig) -> SandboxHandle: ...

    @abstractmethod
    async def execute(
        self,
        handle: SandboxHandle,
        tool_name: str,
        input: dict,
    ) -> ToolResult: ...

    @abstractmethod
    async def destroy(self, handle: SandboxHandle) -> None: ...
```

### Harness loop (`wake/harness/anthropic.py`) — owned by wake-runtime

```python
class AnthropicHarness:
    def __init__(
        self,
        event_store: EventStore,
        tool_registry: "ToolRegistry",
        sandbox: SandboxAdapter | None = None,
        client: AsyncAnthropic | None = None,
    ): ...

    async def run_step(self, session: Session, agent: AgentConfig) -> None:
        """
        One step of the agentic loop:
        - read events from event_store
        - build messages for Anthropic API
        - stream response
        - emit events (assistant.delta, tool_use, tool_result, assistant.message)
        - on tool_use: execute via tool_registry
        - recurse until end_turn
        """
```

---

## API ENDPOINTS (wake-runtime implements)

Match Managed Agents API superficially. Pydantic models in `wake/api/routes/*.py`.

```
POST   /v1/agents                       create
GET    /v1/agents                       list
GET    /v1/agents/{id}                  retrieve
PATCH  /v1/agents/{id}                  update
POST   /v1/agents/{id}/archive          archive
GET    /v1/agents/{id}/versions         list versions

POST   /v1/environments
GET    /v1/environments
GET    /v1/environments/{id}
POST   /v1/environments/{id}/archive
DELETE /v1/environments/{id}

POST   /v1/sessions
GET    /v1/sessions
GET    /v1/sessions/{id}
DELETE /v1/sessions/{id}
POST   /v1/sessions/{id}/events         (send event, returns immediately)
GET    /v1/sessions/{id}/events         (list events)
GET    /v1/sessions/{id}/stream         (SSE stream of events)
POST   /v1/sessions/{id}/interrupt
POST   /v1/sessions/{id}/archive
```

---

## CLI COMMANDS (wake-cli implements)

```bash
wake server [--local] [--port 8080] [--host 0.0.0.0]
wake agent create --name NAME --model MODEL [--system TEXT] [--tools TOOL,TOOL]
wake agent list
wake agent get ID
wake agent archive ID

wake environment create --name NAME [--config FILE]
wake environment list
wake environment get ID

wake session create --agent ID [--environment ID]
wake session list
wake session send SESSION_ID "message"
wake session stream SESSION_ID
wake session events SESSION_ID [--type TYPE] [--tool-only]
wake session interrupt SESSION_ID

wake run "message" [--agent NAME] [--model MODEL]
    # one-shot: creates ephemeral agent + session, sends message, streams, exits
```

CLI deve falar HTTP com server local (default http://localhost:8080, override via `WAKE_SERVER` env var).

---

## DEPS (pyproject.toml — wake-foundation define)

```toml
[project]
name = "wake-ai"
version = "0.0.1"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "sse-starlette>=2.1",
    "pydantic>=2.9",
    "typer>=0.12",
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "aiosqlite>=0.20",
    "httpx>=0.27",
    "anthropic>=0.50",
    "docker>=7.1",
    "python-statemachine>=2.3",
    "python-ulid>=3.0",
    "structlog>=24.4",
    "click>=8.1",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "pytest-cov>=5.0",
    "ruff>=0.7",
    "mypy>=1.13",
    "httpx[testing]",
]

[project.scripts]
wake = "wake.cli.main:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

---

## CONVENÇÕES

- **Python 3.11+** (match-case, exceptiongroup, etc.)
- **async/await everywhere** no I/O code
- **Type hints strict** — mypy passa
- **ruff** para lint + format
- **pytest-asyncio** para testes async
- **structlog** para logging estruturado
- **Logging format JSON** em produção, pretty em dev
- **NO print()** — usar logger sempre

---

## TESTS

Cada agent escreve seus testes em `tests/unit/test_<module>.py`. Integration tests em `tests/integration/` são do wake-cli.

Target: ≥70% coverage no slice de cada agent.

```bash
pytest tests/                       # roda todos
pytest tests/unit/                  # só unitários
pytest --cov=wake --cov-report=term # com coverage
```

---

## COMMIT MESSAGE CONVENTION

Cada agent commita no seu worktree com mensagens claras:

```
foundation: implement EventStore + SQLite backend
runtime: add /v1/sessions/:id/stream SSE endpoint
cli: add `wake run` one-shot command
```

---

## INTEGRATION POINT

Quando todos terminarem, merge será feito na seguinte ordem (deps):

1. `wake-foundation` → main (provides types + store + core)
2. `wake-runtime` → main (consumes foundation, adds API/tools/sandbox/harness)
3. `wake-cli` → main (consumes both, adds CLI/examples/tests)

Conflitos esperados em: `src/wake/__init__.py` (cada agent adiciona seu submodule), `pyproject.toml` (cada agent pode adicionar dep). Resolve manualmente.

---

## DEFINITION OF "DONE" PARA CADA SLICE

### wake-foundation done quando:

- [ ] `pip install -e .` instala sem erro
- [ ] `from wake.types import Event, Session, AgentConfig` funciona
- [ ] SQLite store CRUD funcionando, testado
- [ ] Event log append/get/subscribe testado
- [ ] Session state machine testada (4 estados, transições válidas/inválidas)
- [ ] 70%+ coverage no slice
- [ ] Commit'ed na worktree

### wake-runtime done quando:

- [ ] `uvicorn wake.api.app:app` sobe
- [ ] Todos endpoints respondem (mesmo que stubs)
- [ ] Tool router executa `bash` em sandbox Docker
- [ ] AnthropicHarness completa um ciclo simples (user → assistant)
- [ ] SSE stream emite eventos
- [ ] 70%+ coverage no slice
- [ ] Commit'ed na worktree

### wake-cli done quando:

- [ ] `wake --help` funciona
- [ ] `wake server --local` sobe (chamando wake-runtime's app)
- [ ] `wake run "hello"` completa fluxo end-to-end (PRECISA dos outros 2)
- [ ] Example 01 roda
- [ ] CI configurado
- [ ] Commit'ed na worktree

---

## REGRA DE OURO

Se você é um dos 3 agents:

1. **Leia este contrato inteiro antes de codar.**
2. **Trabalhe APENAS nos files listados em "owns" do seu slice.**
3. **Use os types de `wake/types.py` EXATAMENTE como especificados.**
4. **Não invente interfaces — siga os ABCs deste contrato.**
5. **Se precisar de algo fora do seu slice, deixa TODO comment e segue.**
6. **Commit no SEU worktree, não na main.**
7. **Sua duração: completa o slice o mais rápido possível com qualidade.**
