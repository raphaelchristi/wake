# EXAMPLES

14 cenários concretos de uso. Cada um mostra: problema, comandos/código, resultado esperado.

Examples organizados em pastas no repo final: `examples/01-hello-world/`, etc. Aqui é o índice + esboço.

---

## 01 — Hello World

**Problema:** validar que Wake funciona end-to-end.

```bash
$ wake server --local
[wake] starting local runtime at http://localhost:8080
[wake] sqlite event store at ~/.wake/wake.db
[wake] ready

$ wake run "Say hello in 3 languages"
[10:02:01] session created: sess_01HQR2K7VXBZ9MNPL
[10:02:01] status: running
[10:02:02] assistant.message: "Hello! Bonjour! Olá!"
[10:02:02] status: idle

$ wake session events sess_01HQR2K7VXBZ9MNPL
seq 0  user.message       "Say hello in 3 languages"
seq 1  status             idle → running
seq 2  assistant.message  "Hello! Bonjour! Olá!"
seq 3  status             running → idle
```

Tudo persistido. Mata o server, sobe de novo, eventos ainda lá.

---

## 02 — Coding refactor com sandbox

**Problema:** agente refatora código real com filesystem + bash isolados.

```yaml
# wake.yaml
agent:
  name: refactor-bot
  model: claude-opus-4-7
  system: "You refactor code. Use tools to read/modify files."
  tools: [bash, file_read, file_write, file_edit, grep]

environment:
  sandbox:
    backend: sandbox-runtime
    network:
      mode: limited
      allowed_hosts: []  # zero network
    filesystem:
      allow_write: [./workspace]
      deny_read: [~/.ssh, ~/.aws, .env]
```

```bash
$ wake agent create -f wake.yaml
$ wake session create --agent refactor-bot --workdir ./my-repo
session_xyz created

$ wake session send sess_xyz "Convert all class components in src/ to hooks"
$ wake session stream sess_xyz
[stream]
assistant.thinking: "First, I'll find all class components..."
tool_use bash: rg -l "extends React.Component" src/
tool_result: src/UserCard.tsx, src/Header.tsx, src/Footer.tsx
tool_use file_read: src/UserCard.tsx
tool_result: <content>
tool_use file_write: src/UserCard.tsx <hooks version>
...
assistant.message: "Done. Refactored 3 components. Tests pass."
```

Verifica que o sandbox bloqueou:

```bash
$ wake session send sess_xyz "Try to read ~/.ssh/id_rsa"
[stream]
tool_use bash: cat ~/.ssh/id_rsa
tool_result (is_error=true, error_code=permission_denied):
  cat: /Users/raphael/.ssh/id_rsa: Operation not permitted
```

---

## 03 — Rodando LangGraph no Wake

**Problema:** você tem um StateGraph existente. Quer durabilidade, sandbox, replay sem reescrever nada.

```python
# my_agent.py — código LangGraph normal
from langgraph.graph import StateGraph, END
from typing_extensions import TypedDict

class State(TypedDict):
    messages: list
    iteration: int

def call_model(state):
    # ... lógica normal LangGraph
    return {"messages": [...], "iteration": state["iteration"] + 1}

def should_continue(state):
    return END if state["iteration"] >= 3 else "model"

graph = StateGraph(State)
graph.add_node("model", call_model)
graph.add_conditional_edges("model", should_continue)
graph.set_entry_point("model")
compiled = graph.compile()
```

```python
# rodando no Wake
from wake import Wake
from wake.adapters.langgraph import LangGraphAdapter

wake = Wake(server="http://localhost:8080")
adapter = LangGraphAdapter(compiled, state_key="messages")

session = wake.sessions.create(
    harness=adapter,
    environment="python-dev",
)
session.send("analyze this dataset")

for event in session.stream():
    print(event)
```

Resultado: LangGraph roda normal, mas tudo grava no event log do Wake. Mata processo, sobe outro, retoma do último evento.

---

## 04 — Rodando CrewAI no Wake

```python
from crewai import Crew, Agent, Task
from wake.adapters.crewai import CrewAIAdapter

researcher = Agent(role="Researcher", goal="Find info")
writer = Agent(role="Writer", goal="Write article")

crew_factory = lambda input: Crew(
    agents=[researcher, writer],
    tasks=[
        Task(description=f"Research: {input}", agent=researcher),
        Task(description="Write article from research", agent=writer),
    ],
)

adapter = CrewAIAdapter(crew_factory)
session = wake.sessions.create(harness=adapter)
session.send("AI safety alignment in 2026")
```

Cada `tool_use` dos agents da Crew vira evento Wake. Audit log completo.

---

## 05 — Kill -9 e auto-resume

**Problema:** comprovar que harness é stateless.

```bash
# terminal 1
$ wake server --local
[wake] worker pid 12345 ready

$ wake session create --agent coding-bot
sess_resume_test

$ wake session send sess_resume_test "Run a long task that takes 5 minutes"
[stream] ... task starting ...
[stream] tool_use bash: long_running_script.sh
```

```bash
# terminal 2 — mata o harness worker
$ kill -9 12345
```

```bash
# terminal 1 mostra
[wake] worker 12345 died unexpectedly
[wake] watchdog detected lost session sess_resume_test
[wake] respawning worker
[wake] worker pid 23456 ready
[wake] wake(sess_resume_test)
[wake] reading 8 events from log
[wake] last event: tool_use bash long_running_script.sh
[wake] container still alive, attaching
[wake] resuming from event 8
[stream] tool_result: <script output>
[stream] assistant.message: "Task completed."
```

Zero perda. Cliente recebe o mesmo stream após reconectar.

---

## 06 — Replay e fork

**Problema:** agente fez algo estranho ontem. Reproduzir.

```bash
$ wake session list --since 24h --status failed
sess_prod_42  failed  18h ago  pr-reviewer

$ wake session events sess_prod_42 --type tool_use
seq  3  tool_use  bash       "git log --oneline"
seq  7  tool_use  bash       "rm -rf node_modules && npm install"
seq 12  tool_use  bash       "rm -rf /"  ← O QUE
seq 13  tool_use  bash       (failed: permission denied)
seq 14  error              harness panicked

# replay determinístico desde antes da decisão estranha
$ wake session replay sess_prod_42 \
  --from-event 6 \
  --use-snapshots \
  --fork-as sess_debug_42

forked sess_debug_42

# observa o que aconteceu
$ wake session stream sess_debug_42 --follow
# vê exatamente o mesmo `rm -rf /` sendo proposto
# agora pode inspecionar prompts, context, ferramentas disponíveis
```

Resample alternativo (nova amostragem do LLM):

```bash
$ wake session replay sess_prod_42 --from-event 6 --resample
# LLM amostra de novo a partir do evento 6 — pode tomar decisão diferente
```

---

## 07 — Integração MCP (GitHub server)

```yaml
agent:
  name: pr-reviewer
  model: claude-opus-4-7
  tools: [bash, file_read]
  mcp_servers:
    - name: github
      transport: http
      url: https://mcp.github.com/v1
      vault_ref: github_token  # autenticação via vault
```

```bash
# OAuth flow
$ wake vault add github_token --provider github --oauth
[browser opens] [user authorizes] [token stored]

$ wake session create --agent pr-reviewer --vault github_token
$ wake session send sess_xxx "Review PR #1234 in raphael/myrepo"
```

O agente usa MCP tools `github.list_pull_requests`, `github.get_pr_diff`, `github.create_review_comment`. O token nunca toca o harness — proxy injeta no momento da chamada HTTP.

Audit:

```bash
$ wake session events sess_xxx --type vault.access
seq 4   vault.access  vault=github_token  purpose=github.get_pr_diff
seq 7   vault.access  vault=github_token  purpose=github.create_review_comment
```

---

## 08 — OAuth via Infisical Agent Vault

Demonstra o vault + proxy end-to-end.

```bash
$ wake vault init --backend infisical
[wake] starting Infisical Agent Vault on :7474
[wake] HTTPS interception proxy on :7475

$ wake vault add slack_bot --provider slack --oauth
$ wake vault add notion --provider notion --oauth
$ wake vault list
slack_bot     slack    expires_at=...
notion        notion   expires_at=...
```

```yaml
agent:
  name: ops-bot
  tools: [bash]
  mcp_servers:
    - name: slack
      transport: http
      url: https://slack.com/api
      vault_ref: slack_bot
    - name: notion
      transport: http
      url: https://api.notion.com
      vault_ref: notion
```

Agora o agente posta no Slack e lê do Notion sem ver nenhuma credencial real.

---

## 09 — 100 experimentos paralelos

**Problema:** quer comparar 100 variantes do mesmo prompt contra a mesma tarefa.

```python
from wake import Wake
import asyncio

wake = Wake(server="http://localhost:8080")

prompts = [
    "You are a careful coder. {{task}}",
    "You are a fast coder. {{task}}",
    # ... 98 mais
]

task = "Implement binary search in Python"

async def run_variant(prompt_template, idx):
    agent = wake.agents.create(
        name=f"variant-{idx}",
        model="claude-opus-4-7",
        system=prompt_template,
        tools=["bash", "file_write"],
    )
    session = wake.sessions.create(agent=agent.id)
    session.send(task)
    result = await session.wait_complete()
    return result

results = await asyncio.gather(*[
    run_variant(p, i) for i, p in enumerate(prompts)
])

# compara resultados
$ wake session diff sess_001 sess_002 --side-by-side
```

100 sessões rodam em paralelo. Cada uma com event log próprio. Comparáveis via CLI.

---

## 10 — Export audit-grade

**Problema:** compliance pede log assinado de toda ação do agente.

```bash
$ wake session export sess_xxx \
  --format jsonl \
  --sign \
  --output audit_sess_xxx.jsonl

$ head -3 audit_sess_xxx.jsonl
{"id":"01H...","seq":0,"type":"user.message",...,"signature":"ed25519:..."}
{"id":"01H...","seq":1,"type":"status",...,"signature":"ed25519:..."}
{"id":"01H...","seq":2,"type":"provision",...,"signature":"ed25519:..."}

$ wake audit verify audit_sess_xxx.jsonl
✓ 234 events verified
✓ signing key: kid=wake-prod-2026
✓ chain: complete (no gaps in seq)
✓ timestamps: monotonic
```

JSONL assinado entrega ao auditor. Replay determinístico permite reproduzir.

---

## 11 — Multiagent (coordinator + workers)

**Problema:** dividir tarefa entre múltiplos agentes especializados.

```yaml
# coordinator agent
agent:
  name: lead
  model: claude-opus-4-7
  system: "You delegate work to specialized agents."
  multiagent:
    agents:
      - id: backend-eng
        role: "Backend Engineer"
      - id: frontend-eng
        role: "Frontend Engineer"
      - id: reviewer
        role: "Code Reviewer"
```

```bash
$ wake session create --agent lead
$ wake session send sess_xxx "Build a webhook endpoint with TS frontend"

# coordinator decide chamar backend-eng e frontend-eng em paralelo
# cada um vira uma child session
# eventos da child propagam pro parent log com tags
```

```bash
$ wake session tree sess_xxx
sess_xxx [lead]
├── sess_yyy [backend-eng] (parallel)
├── sess_zzz [frontend-eng] (parallel)
└── sess_www [reviewer] (sequential, after both)
```

---

## 12 — BYO LLM (modelo local via Ollama)

**Problema:** rodar agente com modelo local pra privacidade/custo.

```yaml
agent:
  name: local-coder
  model:
    provider: ollama
    id: qwen2.5-coder:32b
    base_url: http://localhost:11434
  tools: [bash, file_ops]
```

```bash
$ wake session create --agent local-coder
$ wake run "refactor this module" --agent local-coder
```

Tudo do Wake funciona — sandbox, vault, event log, replay. Só o LLM mudou. Provider abstraction via LiteLLM por baixo.

Limitação honesta: tool use semântica do Ollama é diferente da Anthropic. Alguns adapters podem perder features (prompt caching, thinking blocks).

---

## 13 — Long-running 12h task com pausa/resume

**Problema:** tarefa de 12 horas precisa sobreviver a deploy, restart, network.

```bash
$ wake session create --agent data-processor --timeout 24h
sess_long123

$ wake session send sess_long123 "Process 50TB of logs, find anomalies"
[wake] container provisioned with 16cpu/64GB
[stream] tool_use bash: aws s3 sync s3://logs-2026 /workspace/data
[stream] tool_result: synced 50TB
[stream] tool_use bash: python process.py
[stream] (long output...)
```

Hora 6: deploy do Wake server (rolling restart).

```
[wake] received SIGTERM
[wake] gracefully stopping workers
[wake] checkpoint: session sess_long123 state saved
[wake] worker exit clean

[new pod] wake starting...
[new pod] watchdog: sess_long123 was running, container still alive
[new pod] worker pid 99999 wake(sess_long123)
[new pod] resuming from event 12834
[stream] (continues...)
```

Cliente reconecta no SSE com `Last-Event-ID` e continua o stream sem perder eventos.

Hora 9: ECONNRESET na rede do cliente.

```bash
# cliente
$ wake session attach sess_long123 --tail 10
[wake] connected
[stream] tool_use python: ...
[stream] (continues from where left off)
```

---

## 14 — Drop-in compat com Managed Agents API

**Problema:** seu código foi escrito contra Managed Agents da Anthropic. Quer rodar self-host sem reescrever.

```python
# código original (Managed Agents da Anthropic)
import anthropic

client = anthropic.Anthropic(
    base_url="https://api.anthropic.com",  # ← muda só isso
    default_headers={"anthropic-beta": "managed-agents-2026-04-01"},
)

agent = client.beta.agents.create(
    name="my-agent",
    model="claude-opus-4-7",
    tools=[{"type": "agent_toolset_20260401"}],
)

session = client.beta.sessions.create(
    agent=agent.id,
    environment_id="env_xxx",
)
```

Trocando pra Wake self-host:

```python
client = anthropic.Anthropic(
    base_url="http://localhost:8080",  # ← Wake server
)
# resto idêntico
```

Wake responde aos mesmos endpoints. Mesmos schemas. Mesma sequência de SSE events.

(Honestidade: algumas features Anthropic-only não funcionam — prompt caching server-side, code execution managed, etc. Documentadas como "out of scope" no compat mode.)

---

## Estrutura no repo final

```
examples/
├── 01-hello-world/
│   ├── README.md
│   └── run.sh
├── 02-coding-refactor/
│   ├── README.md
│   ├── wake.yaml
│   └── run.sh
├── 03-langgraph-on-wake/
│   ├── README.md
│   ├── my_agent.py
│   └── run.py
├── 04-crewai-on-wake/
│   ├── README.md
│   └── run.py
├── 05-kill-and-resume/
│   ├── README.md
│   └── demo.sh
├── 06-replay-fork/
│   ├── README.md
│   └── demo.sh
├── 07-mcp-github/
│   ├── README.md
│   └── wake.yaml
├── 08-vault-credentials/
│   ├── README.md
│   └── demo.sh
├── 09-batch-experiments/
│   ├── README.md
│   └── batch.py
├── 10-audit-export/
│   ├── README.md
│   └── compliance.sh
├── 11-multiagent-team/
│   ├── README.md
│   └── coordinator.yaml
├── 12-byo-llm-ollama/
│   ├── README.md
│   └── local.yaml
├── 13-long-running/
│   ├── README.md
│   └── process_logs.py
└── 14-managed-agents-dropin/
    ├── README.md
    └── migrate.py
```

Cada exemplo: README com problema + comandos + saída esperada, mais arquivos rodáveis. Tudo runnable em <2min após `wake server --local`.
