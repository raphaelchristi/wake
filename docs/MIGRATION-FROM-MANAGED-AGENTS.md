# Migration: Anthropic Managed Agents → Wake

Guia pra migrar agentes do Anthropic Managed Agents pra Wake (OSS self-host substrate). Wake foi desenhado consciously pra mapear 1:1 com a arquitetura Managed Agents, então migration é direta.

> Wake nasceu inspirado nos primitives do Managed Agents. Esta migration é "lift-and-shift" arquiteturalmente.

---

## Por que migrar?

Você está em Managed Agents e considera migrar quando:
- **Soberania de dados** — exigência regulatória / compliance (HIPAA, GDPR rígido) exige self-host
- **Custom adapters** — você precisa de framework não suportado por Managed Agents (LangGraph, CrewAI, Pydantic AI)
- **Custo previsível** — alto volume, infra fixa > usage-based
- **Vendor neutrality** — flexibilidade de mudar LLM provider (Wake usa LiteLLM)
- **Customização profunda** — modificar event schema, dispatcher, replay engine

Você NÃO deve migrar se:
- Volume é baixo (Managed Agents hosted é mais barato)
- Time de ops é pequeno (Wake exige Helm + Postgres + monitoring stack)
- Você precisa de feature exclusive do Managed Agents que Wake ainda não shipou (memory primitives Phase 11A, computer-use Phase 11E)

---

## Mapeamento de conceitos

| Anthropic Managed Agents | Wake equivalente |
|---|---|
| `Agent` (config) | `AgentConfig` (mesma shape) |
| `Session` | `Session` (compatible schema) |
| `Event` | `Event` (mesma schema; `docs/SPEC-EVENT-SCHEMA.md`) |
| `Environment` | `EnvironmentConfig` (mesma shape) |
| `wake()` SDK call | `client.sessions.create() + stream()` (SDK Phase 8) |
| Built-in tools (bash, file_read, etc.) | Wake `ToolRegistry` + sandbox-runtime |
| Skills | `agent.skills` (mesmo formato dict) |
| Memory primitives | Phase 11A (not yet — gap conhecido) |
| Artifacts | Phase 11B (not yet) |
| Multi-agent delegation | Phase 11C (not yet) |
| Scheduled triggers | Phase 11D (not yet) |
| Computer use | Phase 11E (not yet) |
| Cost tracking | LiteLLM callbacks → `event.metadata.cost_usd` (Phase 7) |
| Workspaces | Wake `organization_id` / `workspace_id` (Phase 6) |
| API keys | `X-Wake-API-Key` + RBAC user_id (Phase 6) |
| Dashboard | Wake Dashboard (Phase 5) |

---

## SDK migration

### Antes (Anthropic SDK)

```python
import anthropic

client = anthropic.Anthropic(api_key="...")

agent = client.agents.create(
    name="My Agent",
    model="claude-opus-4-7",
    system="...",
)

session = client.sessions.create(agent_id=agent.id)
for event in client.sessions.stream(session.id):
    print(event.type, event.content)
```

### Depois (Wake SDK)

```python
from wake_ai_client import WakeClient

client = WakeClient(base_url="http://wake:8080", api_key="...")

agent = await client.agents.create(
    name="My Agent",
    model={"id": "claude-opus-4-7"},
    system="...",
)

session = await client.sessions.create(agent_id=agent.id)
async for event in client.sessions.stream(session.id):
    print(event.type, event.payload)  # nota: payload, não content
```

Diferenças notáveis:
- Wake SDK é **async-first** (Anthropic SDK também tem async; usar `client.beta.agents.create` async no MA)
- `event.content` (Anthropic) → `event.payload` (Wake) — JSON estruturado, não só text
- `model="..."` (Anthropic) → `model={"id": "..."}` (Wake — ModelConfig com provider + speed)

---

## Event schema compat

Wake event schema é **superset** do Managed Agents. Campos extras Wake:
- `organization_id` / `workspace_id` (tenant scope)
- `parent_id` (event causation chain — usado para tool_use → tool_result links)
- `metadata.idempotency_key` (Phase 7 retry-safe append)
- `metadata.cost_usd` (LiteLLM callback)

Migration de events MA → Wake = adicionar `default/default` tenant scope se faltante.

Script auxiliar:
```python
async def migrate_event_log(source_session_id, dest_session_id):
    # Pull events MA via Anthropic API
    ma_events = await ma_client.sessions.events(source_session_id)
    for e in ma_events:
        await wake_client.sessions.append_event(
            dest_session_id,
            type=e.type,
            payload=e.content if isinstance(e.content, dict) else {"text": e.content},
            metadata={
                **(e.metadata or {}),
                "migrated_from_ma": True,
                "ma_event_id": e.id,
            },
            idempotency_key=f"ma-{e.id}",  # dedupe se script roda 2×
        )
```

---

## Tools

### Anthropic built-in tools

Wake replica via `wake.tools.registry`:

| MA tool | Wake | Status |
|---|---|---|
| `bash_20251022` | `wake.tools.bash` | ✅ |
| `text_editor_20250728` | `wake.tools.file_edit` | ✅ |
| `web_search` | DIY via MCP server (agentgateway) | ⚠️ via plugin |
| `web_fetch` | DIY via vault HTTPS proxy | ⚠️ |
| `code_execution_20250825` | sandbox-runtime + custom tool | ✅ |
| `computer_use_20250827` | Phase 11E | ❌ not yet |

### Custom tools

Direto port:
```python
# MA tool
{"name": "my_tool", "description": "...", "input_schema": {...}}

# Wake tool
@wake_tool(name="my_tool", description="...", requires_sandbox=False)
def my_tool(arg1: str, arg2: int) -> dict:
    return {"result": ...}
```

Wake re-usa JSON Schema. `requires_sandbox=True` força sandbox provisioning.

---

## Skills

Wake `agent.skills` aceita mesmo shape:
```python
agent = await client.agents.create(
    ...,
    skills=[
        {"id": "pdf-extract", "type": "anthropic.skills.v1", "config": {...}},
    ],
)
```

⚠️ Skills runtime ainda é Phase 11+ pra paridade completa. Por agora, skills são metadata; execução custom via adapter.

---

## Multi-agent

Managed Agents permite `agent.delegate(other)` first-class (na beta API). Wake Phase 11C trará isso. Por agora:

**Workaround:** rodar agent secundário como session separada, agent primário escreve `delegate` events com session_id da chamada filha.

```python
@wake_tool(name="delegate_to_research", requires_sandbox=False)
async def delegate_to_research(prompt: str) -> str:
    sub_session = await client.sessions.create(
        agent_id="agent_research_specialist",
    )
    await client.sessions.append_event(
        sub_session.id,
        type="user.message",
        payload={"text": prompt},
    )
    # Wait for completion
    final = None
    async for e in client.sessions.stream(sub_session.id):
        if e.type == "assistant.message":
            final = e.payload.get("text")
        if e.type == "status" and e.payload.get("to") == "terminated":
            break
    return final or "(no response)"
```

Dashboard mostrará session pai → child link via `parent_id` em events.

---

## Memory

Managed Agents tem memory primitives (semantic search across sessions). Wake Phase 11A adicionará `MemoryAdapter` ABI; por agora:

**Workaround:** plugar Mem0 / Letta / Phoenix como tool externo via MCP. Não é first-class mas funciona.

```python
@wake_tool(name="memory_recall", requires_sandbox=False)
async def memory_recall(query: str) -> list[dict]:
    return await mem0_client.search(query, agent_id="...")
```

---

## Artifacts

Managed Agents tem `artifact.created` event canônico. Wake Phase 11B adicionará equivalent. Por agora:

**Workaround:** sandbox write em `/workspace/artifacts/` + sandbox-runtime expose via `GET /v1/sessions/{id}/artifacts/{path}` (não wireado em todos os adapters; PR welcome).

---

## Cost tracking

Managed Agents reporta `usage` em response. Wake usa LiteLLM callbacks que stampam `event.metadata.cost_usd`. Dashboard agrega via `/v1/metrics/summary?window=24h`.

```python
metrics = await client.metrics.summary(window="24h")
print(f"Total cost: ${metrics.cost_total_usd}")
```

Cost-budget enforcement opt-in via `agent.metadata.max_cost_usd` (Phase 7 gap #7).

---

## Storage

Managed Agents é fully hosted (zero infra). Wake exige:
- Postgres (events + agents + sessions + users) — Helm chart provê
- Object storage S3-compatible (vault state + backup) — AWS/MinIO/R2
- Optional Redis (rate-limit + SSE fan-out scale)

Hardware budget mínimo (dev):
- 1 vCPU + 2GB RAM por replica (Wake API)
- 1 vCPU + 1GB RAM por worker
- Postgres 16 com 4GB RAM (PG buffer pool)

Produção (1000 concurrent sessions): ver `docs/BENCHMARKS.md`.

---

## Migration timeline (realistic)

| Step | Time |
|---|---|
| 1. Stand up Wake local (Compose) | 1-2 hours |
| 2. Create test agent + session via Wake SDK | 1 hour |
| 3. Run 1 session end-to-end (compare output vs MA) | 2-4 hours |
| 4. Port custom tools (per tool) | 1-2 hours each |
| 5. Setup Vault credentials | 2 hours |
| 6. Migrate event log (script + verify) | 1 day per 10k sessions |
| 7. Deploy Helm prod | 1-2 days |
| 8. Cut traffic | gradual (10% canary first) |

**Total realistic:** 1-2 weeks pra pilot + 1-2 weeks pra production cutover.

---

## What you LOSE migrating to Wake

- **Managed scaling** — você vira responsável pelo HPA, Postgres tuning, backup ops
- **First-class memory/artifacts/multi-agent** (até Phase 11+)
- **Anthropic-specific optimizations** — Anthropic SDK pode ter latência menor pra modelos Anthropic
- **Computer-use / voice / TTS** — Wake Phase 11E/F pendente

## What you GAIN

- **Self-host** — dados nunca saem do seu cluster
- **Framework neutrality** — LangGraph + CrewAI + Pydantic AI + Claude SDK lado a lado
- **Custom adapter** — vendor lock-in zero
- **Audit log completo** — every event in your Postgres
- **Cost predictability** — fixed infra vs usage-based

---

## Decision checklist

Migra pra Wake se:
- [x] Compliance / data sovereignty exige self-host
- [x] Você roda >1 framework (LangGraph + LiteLLM + custom)
- [x] Volume mensal > $10k em Managed Agents
- [x] Time de ops aceita gerenciar Postgres + Helm

Fica em Managed Agents se:
- [ ] Time de ops é 1-2 pessoas
- [ ] Precisa de memory/artifacts/multi-agent já
- [ ] Volume baixo (<$1k/mês)
- [ ] Quer Anthropic SDK exclusively
