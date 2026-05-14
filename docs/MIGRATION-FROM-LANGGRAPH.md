# Migration: LangGraph → Wake

Guia pragmático pra migrar agente LangGraph standalone (sem Wake) pra Wake substrate. Reuso máximo via `wake-adapter-langgraph` — você NÃO reescreve seu graph.

> **Phase 8 deliverable** (Tier 3 doc, antecipado aqui). Wake adapter ABI já está locked desde Phase 2 (`v0.1.0-frozen`).

---

## Tese

Você TEM:
- Graph LangGraph (StateGraph, nodes, edges, conditional routing)
- Tools (Python functions + JSON schemas)
- LLM client (Anthropic, OpenAI, Bedrock, etc.)
- Storage ad-hoc (talvez Postgres, talvez Redis, talvez nada)

Você QUER:
- Event log durable (replay, audit, debug)
- Sandbox isolation (cada session em container)
- Vault pra credentials (sem expor tokens em logs)
- Dashboard (sessions list, replay scrubber, metrics)
- Multi-tenancy (org/workspace isolation)
- Kill-and-resume (worker died ≠ session lost)

Wake provê esses 6 sem você tocar no graph.

---

## Antes (LangGraph standalone)

```python
# my_agent/graph.py
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import create_react_agent
from langchain_anthropic import ChatAnthropic

graph = StateGraph(state_schema=AgentState)
graph.add_node("agent", agent_node)
graph.add_node("tools", tool_node)
graph.add_edge("__start__", "agent")
graph.add_conditional_edges("agent", route)
graph.add_edge("tools", "agent")
compiled = graph.compile()

# server.py (your own)
@app.post("/chat")
async def chat(req):
    async for chunk in compiled.astream(req.messages):
        yield format(chunk)
```

Problemas:
- Sem event log: re-rodar não é determinístico (estado perdido entre requests)
- Sem sandbox: tool `run_bash` roda no mesmo host do server (security hole)
- Sem vault: API keys em env vars / logs
- Sem dashboard: debug = `print()` + grep

---

## Depois (Wake substrate)

```python
# my_agent/adapter.py — implementa HarnessAdapter Protocol
from wake.adapters import HarnessAdapter
from wake_adapter_langgraph import LangGraphAdapter  # reference impl

# Opção 1: usa adapter pronto
adapter = LangGraphAdapter(graph=compiled)

# Opção 2: estende pra customizar
class MyAdapter(LangGraphAdapter):
    async def on_lifecycle(self, ctx, lifecycle):
        # custom hook
        await super().on_lifecycle(ctx, lifecycle)

# wake.toml ou entrypoint
[adapters.my-agent]
class = "my_agent.adapter.MyAdapter"
```

```python
# Cliente (server.py vai embora — Wake provê)
from wake_ai_client import WakeClient

client = WakeClient(base_url="http://wake:8080", api_key="...")
agent = await client.agents.create(
    name="My Agent",
    model={"id": "claude-opus-4-7"},
    metadata={"harness": "my-agent"},  # nome do adapter
)
session = await client.sessions.create(agent_id=agent.id)
async for event in client.sessions.stream(session.id):
    handle(event)
```

---

## Mapeamento

| LangGraph concept | Wake equivalente |
|---|---|
| `StateGraph` | seu graph fica intacto; LangGraphAdapter wrapa |
| `compiled.astream()` | Wake dispatcher chama via `adapter.step()` |
| `ToolNode` | Wake `ToolRegistry` + sandbox runtime executa tools |
| `MemorySaver` / `PostgresSaver` (checkpointer) | Wake event log + `wake.store.EventStore` substituem |
| `StateGraph` interrupts (HITL) | Wake `session.status = "interrupted"` + retomada via `wake() {{ resume }}` |
| Tool side-effects | Wake sandbox runtime (Docker/Bubblewrap/sandbox-exec) |
| Tool credentials | Wake Vault (Infisical) com proxy HTTPS substitution |
| Multi-tenant | Wake `organization_id` / `workspace_id` (Phase 6) |
| Observability | Wake dashboard `/sessions/[id]/replay` + Prometheus (Phase 7) |

---

## Step-by-step

### 1. Install Wake + LangGraph adapter

```bash
pip install wake-ai wake-adapter-langgraph
```

### 2. Configure adapter pro seu graph

```python
# my_agent/__init__.py
from wake.adapters import register_adapter
from wake_adapter_langgraph import LangGraphAdapter
from .graph import compiled

register_adapter("my-agent", LangGraphAdapter(graph=compiled))
```

Discovery via entry_points em `pyproject.toml`:
```toml
[project.entry-points."wake.adapters"]
my-agent = "my_agent:LangGraphAdapter"
```

### 3. Subir Wake

```bash
docker compose -f deploy/docker-compose.yml up
```

Ou Helm:
```bash
helm install wake oci://ghcr.io/wake-ai/wake \
  --set adapters.image=my-agent:0.1.0 \
  --set auth.apiKey=$(openssl rand -hex 32)
```

### 4. Migrar tools pra sandbox

Tools que executam código (bash, file_write, etc.) movam pra `ToolRegistry`:

```python
# antes (LangGraph)
@tool
def run_bash(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, capture_output=True).stdout

# depois (Wake-aware)
@wake_tool(name="bash", requires_sandbox=True)
def run_bash(cmd: str, sandbox: SandboxHandle) -> str:
    # cmd executa DENTRO do sandbox, não no host
    return sandbox.exec(cmd).stdout
```

`requires_sandbox=True` força Wake a provisionar container antes de chamar a tool.

### 5. Migrar credentials pro Vault

```python
# antes
github_token = os.environ["GITHUB_TOKEN"]
gh.set_token(github_token)

# depois
async with client.vault.proxy("github") as proxy_token:
    # proxy_token é um placeholder; vault substitui em HTTPS request
    gh.set_token(proxy_token)
```

Configurar:
```bash
wake vault add github --provider github --oauth
# segue prompt OAuth
```

### 6. Test replay determinism

```python
# Cria session, roda, salva session_id
session = await client.sessions.create(agent_id=agent.id)
# ... aguarda completion ...

# Replay (Phase 8)
replayed = await client.sessions.replay(session.id, preserve_seeds=True)
# Compare events: original vs replayed
```

---

## Gotchas

### Stateful nodes em graph

LangGraph permite nodes que mutam `state` in-place. Wake event log é append-only — state vive nos events, não em RAM compartilhada.

**Fix:** garanta que cada node retorna delta explícito ao `state`, não muta dict. `LangGraphAdapter` já assume isso.

### Tools que chamam APIs externas

Wake sandbox bloqueia network egress por default. Tools que precisam de network (search, scrape):

```toml
[tools.search]
allow_egress = ["api.serpapi.com", "*.brave-search.com"]
```

Ou use agentgateway (Phase 4 already deployed) pra controlar MCP/A2A traffic.

### MemorySaver / checkpointer

Você NÃO precisa mais. Wake event log é o checkpointer canônico. Remover `compiled = graph.compile(checkpointer=MemorySaver())` — passar só `graph.compile()`.

### Streaming format

LangGraph `astream()` emite chunks por convenção (per-node, per-token). Wake events são per-step normalizados. `LangGraphAdapter` faz o translation.

Se você consumia `astream()` direto, agora consume `client.sessions.stream(id)` — shape é `Event` pydantic com type/payload/metadata.

### Multi-agent (graph-of-graphs)

LangGraph supports nested graphs (sub-graph as node). Wake Phase 11C trará `agent.delegate(other)` primitive. Por agora, achatar o graph ou rodar cada sub-agent como session separada coordenada externamente.

---

## Cost comparison

| Aspecto | Standalone LangGraph | Wake substrate |
|---|---|---|
| Dev time setup | 0 dias | 1-2 dias (Wake install + adapter config) |
| Sandbox infra | DIY (Docker/firejail) | included (sandbox-runtime) |
| Vault infra | DIY ou Vault separate service | included (Infisical adapter) |
| Dashboard | DIY | included (Next.js 15) |
| Multi-tenancy | DIY | included (Phase 6) |
| Ops hardening (rate-limit, retention, etc.) | DIY | included (Phase 7) |
| Storage Postgres | DIY | included (alembic-managed) |
| **Total infra DIY** | ~3-4 semanas | ~1 dia de config |

ROI: Wake faz sentido quando você roda >1 agent OR precisa de >1 desses items.

---

## Migration FAQ

**Q: Posso migrar gradualmente?**
A: Sim. Wake e LangGraph standalone podem coexistir (Wake dispatcha pra adapter; standalone roda à parte). Migrar agent-por-agent.

**Q: Wake suporta meus modelos não-Anthropic?**
A: Sim via `wake-llm-litellm` (Phase 4). Suporta OpenAI, Bedrock, Vertex, Ollama, etc.

**Q: Posso usar meu Postgres existente?**
A: Sim. `wake-store-postgres` aceita DSN existente; migrations Alembic adicionam só tables `agents/sessions/events/users` etc — não toca tables suas.

**Q: E LangSmith / Phoenix observability?**
A: Adapters Wake-eval (Phase 8) podem pull dataset + push results pra LangSmith / Phoenix. Não precisa abandonar tooling.

**Q: HITL (human-in-the-loop)?**
A: Wake `session.interrupt()` + `session.resume()` cobrem HITL. Dashboard mostra sessions interrompidas pra ação humana.

---

## Reference projects

- `examples/05-resume-after-kill/` — kill worker mid-step, resume seamlessly
- `examples/08-vault-credentials/` — Vault proxy com OAuth providers
- `adapters/langgraph/examples/` — graph examples wrapped em LangGraphAdapter

---

## Next steps

1. Identifica 1 agent piloto (mais simples, sem stateful nodes ad-hoc)
2. Roda Wake local via Compose
3. Wrapa graph em LangGraphAdapter
4. Test replay com session real
5. Migra credentials pra Vault
6. Avalia ROI antes de migrar resto
