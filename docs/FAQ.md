# FAQ

Perguntas comuns e respostas honestas.

---

## Sobre o projeto

### Por que não simplesmente forkar o OpenHands V1?

Considerei seriamente. Argumentos a favor:

- OpenHands tem 68k stars
- Arquitetura V1 é ~85% da tese Wake
- Pular meses de trabalho

Argumentos contra (que ganharam):

- **Posicionamento entranhado.** OpenHands é produto coding-agent. Mudar pra "substrato neutro" exige reescrever messaging, README, marketing, exemplos, comunidade. É forking de produto, não de código.
- **Workspace é environment-specific.** Generalizar para `execute(name, input) → string` é uma refatoração não-trivial que afeta toda a base.
- **HarnessAdapter ABI exigiria PR aceito.** O time OpenHands pode (legitimamente) não querer essa abstração que afeta seu produto principal.
- **Fork não-mergeado vira manutenção dupla.** A história OSS está cheia de forks técnicos abandonados.

Wake greenfield é mais arriscado em adoção, menos arriscado em direção. Se OpenHands publicar HarnessAdapter equivalente, Wake contribui de volta e morre limpa.

---

### Por que não contribuir pro Multica?

Multica é control plane sobre **CLIs** (Claude Code, Codex, Gemini CLI). Diferente da tese Wake (substrato sob **SDKs de framework**).

Não é mesma coisa. Multica não é runtime — delega tudo aos CLIs. Wake é runtime — frameworks plugam.

Possível convergência futura: Multica adiciona suporte a frameworks SDK. Aí conversamos.

---

### Wake vai competir com LangGraph?

Não. LangGraph é framework de agentes. Wake é substrato de execução. Você usa LangGraph para escrever o agente; Wake para hospedar com durabilidade/sandbox/vault.

Analogia: Django vs uvicorn. Você não escolhe um. Você usa os dois.

---

### Wake é só pra usar com Claude?

Não. Wake é Claude-first (compat surface superficial com Managed Agents API, semântica de tool use canônica idêntica à Anthropic), mas suporta outros providers via LiteLLM.

Limitação honesta: alguns features Anthropic-only (prompt caching, thinking blocks, skills nativas) não funcionam fora de Claude.

---

### Vou pagar pra usar Wake?

Não. OSS, MIT ou Apache 2.0 (licença final decide Day-30 baseado em feedback enterprise).

Hosted comercial pode existir no futuro, mantido por terceiros. Não é parte do core.

---

### Wake substitui Temporal/Restate/DBOS?

Não. Wake é agent-specific. Temporal/Restate/DBOS são durable execution genéricos.

Você pode rodar Wake **em cima de** Temporal/Restate/DBOS (e provavelmente vai, em deployments grandes). Wake oferece event schema canônico + tool ABI + sandbox + vault que aqueles não fornecem.

---

### Quem mantém Wake?

Hoje: um grupo pequeno em design phase.

Day-90: governance pública formalizada (steering committee, RFC process). Idealmente comunidade auto-sustentável; Linux Foundation se houver tração.

---

## Sobre arquitetura

### Por que append-only event log e não state direto?

Três razões:

1. **Resume.** Harness morre, novo harness lê log, continua. Sem log, perda total.
2. **Replay.** Debug requires reproducibilidade. State direto não reproduz.
3. **Audit.** Compliance/regulated industries exigem log imutável.

State derivado é caro? Sim. Mas é re-derivável em segundos a partir de log com índices.

---

### Harness fora do container é mesmo necessário?

Sim. Ver [Decoupling the brain from the hands](https://www.anthropic.com/engineering/managed-agents).

Resumo: container morre = sessão morre quando tudo está dentro. Container morre = tool_call_error quando harness está fora.

OpenClaw e maioria dos outros rodam harness dentro. Wake roda fora.

---

### Provisionamento preguiçoso vale a pena?

Sim. Sessões que só conversam (sem chamar bash/file_ops) nunca provisionam container. Custo = zero. Latência = igual chamada de API normal.

Anthropic reporta TTFT p95 reduzido em >90% com essa decisão.

---

### Por que Postgres e não Kafka/EventStore?

Postgres é:

- Operacionalmente simples (uma peça)
- Conhecido por todos os devs
- Suficiente para milhões de sessões com particionamento básico
- Suporta JSONB, FTS, advisory locks, listen/notify — tudo que precisamos

Kafka/EventStore vêm depois quando escala justificar. Plugável via backend interface.

---

### Wake é stateless mesmo?

Harness é stateless. Wake o sistema **não** — tem Postgres, tem vault, tem object storage. Mas cada componente é stateless ou simples-stateful.

Harness workers podem rodar em FaaS / Kubernetes Jobs / Cloud Run sem problema.

---

### Como Wake lida com idempotência de tools?

Tools com side effects precisam de `tool_use_id` único. Runtime deduplifica via unique constraint no event log:

```sql
CREATE UNIQUE INDEX uniq_tool_use
ON events (session_id, (payload->>'tool_use_id'))
WHERE type = 'tool_use';
```

Re-emissão pelo harness após crash não duplica.

Tools sem side effects (pure compute) podem rodar 2x sem problema.

---

### E se a tool não é idempotente nem tem tool_use_id?

Documentar como **não-resumable** no manifest. Sessão com tool não-resumable que crashar mid-tool: marca evento de erro, deixa decisão pro usuário (retry com risco, ou abort).

---

### Como Wake faz determinismo no replay?

Dois modos:

**`--use-snapshots`:** events foram gravados com snapshot da resposta LLM original. Replay reusa. Determinístico 100%, custa storage.

**`--resample`:** LLM é chamado de novo. Não determinístico (amostragem). Útil pra explorar alternativas.

Tools são determinísticas por contrato (pure compute) ou snapshotadas (side effects).

---

## Sobre o ecossistema

### Wake vai colidir com Open Agent Specification?

Não. Open Agent Spec define **formato declarativo do agent** (model, system, tools, mcp). Wake consome esse formato.

HarnessAdapter ABI define **interface entre harness e runtime** — coisa diferente. Open Agent Spec não tem isso.

Wake pode (e deve) adotar Open Agent Spec como linguagem de definição.

---

### Por que não usar A2A para multi-agent?

Vai usar, mas Day-30+. Day-1 foco é single-agent + tool use. Multi-agent via A2A é feature derivada.

---

### MCP é obrigatório no Wake?

Não obrigatório, mas first-class. Tools podem ser:

- Built-in (Wake oferece bash, file_ops, etc.)
- MCP (qualquer servidor MCP pluga)
- Custom (Python/TS funções registradas)

MCP é o caminho default para tools de terceiros (GitHub, Slack, Notion, etc.).

---

### Wake suporta skills (Anthropic-style)?

Parcialmente. Skills com progressive disclosure são Anthropic-specific. Wake pode emular como tools especiais que carregam contexto sob demanda, mas não vai replicar a otimização server-side da Anthropic.

---

### LangChain Deep Agents Deploy faz quase a mesma coisa. Por que Wake?

Deep Agents Deploy é:

- LangChain-aligned (lock-in)
- Self-host via LangSmith Deployments (pago)
- Harness é Deep Agents (LangGraph-based)

Wake é:

- Framework-agnostic (LangChain é UM dos suportados)
- Self-host direto (Docker Compose, Helm, qualquer K8s)
- HarnessAdapter ABI público (não single-vendor)

Quem ama LangChain pode preferir Deep Agents. Quem quer neutralidade prefere Wake.

---

## Sobre tecnologia

### Qual linguagem o Wake runtime usa?

Day-1: Python (rápido pra prototipar, ecosystem AI maior).

Day-90 decide se reescrita em Go/Rust justifica (single binary, perf).

SDKs: Python + TypeScript Day-1. Outras linguagens via cliente HTTP genérico.

---

### Por que sandbox-runtime e não Docker direto?

Docker padrão é **namespace isolation**, não sandbox. Container Docker normal pode:

- Acessar dados sensíveis se mount errado
- Egress livre (sem proxy)
- Escapar via CVEs de runc

sandbox-runtime usa bubblewrap + seccomp + proxy = isolamento real. É o que Anthropic usa internamente.

Default Wake: sandbox-runtime. Fallback Wake: Docker padrão (modo "trusted code only").

---

### E Firecracker / gVisor?

Backends futuros. Maior segurança, maior complexidade operacional. Não default.

---

### Como Wake roda em produção?

Stack mínima:

```
- Wake API server (Python, FastAPI ou similar)
- Postgres (event log + agent/env catalog)
- Wake harness workers (Python, qualquer scheduler)
- Object store S3-compatible (artifacts)
- Optional: Redis ou NATS (SSE pub/sub fan-out)
```

Helm chart oficial Day-30.

---

### Wake escala?

Sim, horizontalmente:

- API server: stateless, escalável
- Harness workers: stateless, qualquer número
- Postgres: particionamento por session_id hash; partition por month para tables crescendo
- SSE fan-out: Redis Streams ou NATS

Limite prático: ~milhões de sessões/dia num cluster modesto. Bilhões com tuning sério (Kafka backend, ClickHouse para analytics).

---

### Wake tem GUI?

Core: CLI only.

Pacote separado: `wake-ui` (Day-90 roadmap). Web UI read-only inicialmente — listar sessions, ver stream, replay, export.

---

## Sobre adoção

### Já dá pra usar Wake?

Não. Pre-alpha, fase de design. Specs em revisão. Código não-escrito.

Acompanhe issues/PRs no repo para feedback nas specs.

---

### Quando posso usar Wake em produção?

Day-90 minimum (3 meses). Day-180 com mais confiança (audit security, multi-node deploys validados).

---

### Como contribuir?

Hoje: revisar specs em `docs/`. Abrir issues com críticas, dúvidas, casos de uso.

Quando código existir: PRs welcome via processo documentado em `CONTRIBUTING.md`.

---

### Wake aceita doações / sponsorship?

Não tem estrutura formal ainda. Day-180 conforme governance se formalizar.

---

## Sobre risco

### E se OpenHands publicar HarnessAdapter primeiro?

Wake contribui de volta, descontinua, ou foca em diferenças menores.

Não vamos brigar com 68k stars + $18M de funding por um marco que já existe. O bem comum é o padrão existir; secundário é quem cria.

---

### E se MAF dominar enterprise?

Wake foca em casos não-enterprise primeiro (devs solo, startups, OSS). MAF e Wake podem coexistir.

---

### E se Anthropic open-sourcear Managed Agents?

Wake vira contribuição para o projeto upstream ou se posiciona como "Managed Agents fork com HarnessAdapter público."

---

### E se Wake não vingar?

Documentos ficam. Specs servem de referência para próximas tentativas. Custo absoluto: 3-6 meses de trabalho + alguns dollars de infra.

ROI mesmo em falha: aprendizado profundo da camada agent infrastructure.

---

## Honestidade final

Wake é uma aposta com odds desconhecidas. As probabilidades honestas:

- **30%** — Wake vira referência adotada pelos frameworks principais como padrão
- **30%** — Wake estabelece a spec mas runtime fica nicho; OpenHands ou MAF dominam infra
- **20%** — OpenHands V1 SDK ou outro publica HarnessAdapter equivalente, Wake morre ou contribui
- **20%** — Wake nunca alcança massa crítica, fica como projeto de referência técnica

Vale a pena tentar? Para quem se importa com o problema, sim. Para quem busca certeza de sucesso, não.
