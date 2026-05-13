# ROADMAP

Marcos concretos do projeto. Honesto sobre o que não está no caminho.

---

## Day 1 (semana 1-2)

**Objetivo:** projeto existe publicamente com algo rodável.

### Deliverables

**Spec v0.1.0 — papel, não código**

- [ ] `SPEC-HARNESS-ADAPTER.md` revisada e congelada (já rascunhada)
- [ ] `SPEC-EVENT-SCHEMA.md` revisada e congelada (já rascunhada)
- [ ] JSON Schemas para validação
- [ ] `CONTRIBUTING.md` + processo RFC

**Wake runtime v0.1.0 — single binary**

- [ ] `pip install wake-ai` ou `brew install wake`
- [ ] `wake server --local` sobe num único processo (SQLite event store)
- [ ] API REST: `/v1/agents`, `/v1/environments`, `/v1/sessions`, `/v1/sessions/:id/events`, `/v1/sessions/:id/stream`
- [ ] Event log SQLite com schema canônico
- [ ] Tool router com tools built-in: `bash`, `file_read`, `file_write`
- [ ] Sandbox backend: Docker padrão (sandbox-runtime fica pra Day-30)
- [ ] HarnessAdapter loaded via plugin discovery
- [ ] LLM provider via Anthropic SDK direto (LiteLLM Day-30)

**Adapter de referência v0.1.0**

- [ ] `wake-adapter-claude-sdk` — Claude SDK puro como harness
- [ ] Test suite de conformância rodando

**CLI v0.1.0**

- [ ] `wake server`
- [ ] `wake agent create/list/get`
- [ ] `wake session create/send/stream/events/list`
- [ ] `wake run "<message>"` — atalho one-shot

**Docs e exemplo mínimo**

- [ ] README.md raiz do repo com pitch + quickstart
- [ ] Exemplo 01-hello-world rodando
- [ ] Exemplo 02-coding-refactor rodando
- [ ] GIF/asciicast no README

**Métrica de sucesso Day-1:** dev clona, roda `wake server --local`, `wake run "hello"` retorna assistant.message em <2 minutos.

---

## Day 30 (mês 1)

**Objetivo:** generalidade da spec provada com 3 adapters.

### Deliverables

**Spec v0.2.0**

- [ ] Revisão pública com feedback da comunidade
- [ ] Ajustes nos schemas baseado em uso real
- [ ] Open questions Q1-Q4 resolvidas

**Wake runtime v0.2.0**

- [ ] Postgres backend para event store (single-node ainda)
- [ ] LiteLLM integration — multi-provider funciona
- [ ] sandbox-runtime backend (alternativo a Docker)
- [ ] Infisical Agent Vault integration
- [ ] agentgateway integration para egress MCP
- [ ] Resume após harness death (watchdog + advisory locks)

**Adapters de referência**

- [ ] `wake-adapter-langgraph` — StateGraph rodando
- [ ] `wake-adapter-crewai` — Crew rodando
- [ ] `wake-adapter-pydantic-ai` — Pydantic AI Agent rodando
- [ ] Test suite de conformância passando para os 4 adapters

**CLI features**

- [ ] `wake session replay --from N --fork-as Y`
- [ ] `wake session diff X Y`
- [ ] `wake vault add/list/remove`
- [ ] `wake session export --format jsonl --sign`

**Docs**

- [ ] `docs.wake.dev` no ar
- [ ] Tutorial completo: "deploy your first Wake agent"
- [ ] Tutorial: "port your LangGraph agent to Wake"
- [ ] Blog post: "Why Wake: the harness-portable substrate"
- [ ] Blog post: "HarnessAdapter spec walkthrough"

**Distribuição**

- [ ] Show HN
- [ ] Twitter/X thread
- [ ] Discord/Slack community
- [ ] Conversa com mantenedores de LangGraph, CrewAI, Pydantic AI

**Métrica de sucesso Day-30:** 4 adapters rodando, 1k+ stars, 3-5 contribuidores externos abrindo issues/PRs na spec.

---

## Day 90 (mês 3)

**Objetivo:** confiabilidade de produção. Adoção real.

### Deliverables

**Spec v0.3.0 → v1.0 RC**

- [ ] Spec considerada estável após review final
- [ ] Compat tests para múltiplas versões de cada framework
- [ ] Backward compat tests entre Wake versions

**Wake runtime v0.3.0**

- [ ] Multi-node deploy (vários workers, Postgres compartilhado)
- [ ] Helm chart + Docker Compose oficiais
- [ ] OpenTelemetry exporters (Langfuse, Phoenix, Helicone validados)
- [ ] Cloud deploy guides: AWS, GCP, Fly.io
- [ ] Rate limiting + quotas básicos
- [ ] Health checks + metrics endpoint

**Adapters expandidos**

- [ ] `wake-adapter-mcp-only` — agentes que só usam MCP, sem framework
- [ ] `wake-adapter-claude-code` — Claude Code Agent SDK (privately, se possível)
- [ ] Community-contributed adapter for AutoGen / MAF

**Sandbox backends adicionais**

- [ ] Firecracker microVM backend (opcional)
- [ ] E2B SDK backend (opcional)

**UI/Dashboard (pacote separado)**

- [ ] `wake-ui` repositório separado
- [ ] Web UI para listar sessions, ver event stream, replay, debug
- [ ] Read-only inicialmente

**Audit + compliance**

- [ ] Event signing com ed25519
- [ ] Export JSONL assinado verificável
- [ ] Documentação para SOC2 / HIPAA / GDPR

**Métrica de sucesso Day-90:** 5k+ stars, 10+ deploys reportados em produção, 2-3 adapters mantidos pela comunidade (não-fundadores).

---

## Day 180 (semestre 1)

**Objetivo:** consolidação como padrão.

### Deliverables

**Spec v1.0 lock**

- [ ] HarnessAdapter v1.0 final, breaking changes proibidos
- [ ] Event schema v1.0 final
- [ ] Tool ABI v1.0 final
- [ ] Governance pública (steering committee, RFC process formal)

**Wake runtime v1.0**

- [ ] GA com SLA de backwards compat
- [ ] Performance benchmarks publicados
- [ ] Security audit externo concluído

**Ecosystem**

- [ ] Adapter para Microsoft Agent Framework
- [ ] Adapter para OpenAI Agents SDK (se a comunidade quiser)
- [ ] Plugins oficiais: `wake-memory-letta`, `wake-memory-mem0`, `wake-outcomes-llm-judge`
- [ ] Wake aparece em palestras / conferências como referência

**Métrica de sucesso Day-180:** 10k+ stars, 1-2 empresas conhecidas em produção, mantenedores de pelo menos 2 frameworks (LangGraph, CrewAI, etc.) endossando publicamente.

---

## Day 365 (ano 1)

**Objetivo:** ser o padrão de facto.

### Deliverables

- [ ] Wake runtime v1.x estável
- [ ] HarnessAdapter v1.x spec adotada por ≥5 frameworks
- [ ] Comunidade auto-sustentável (PRs vindo de fora, não só fundadores)
- [ ] Vendors comerciais oferecendo Wake-hosted (Wake.cloud, etc.)
- [ ] Conferência própria ou track dedicada em conferência maior

---

## O que NÃO está no roadmap (e por quê)

### Memória persistente como primitiva

Letta, Mem0, Zep, Cognee resolvem isso. Wake roda eles via tools. Não vai duplicar.

### Vector store embutido

RAG vector stores são feature de aplicação, não substrato. Pluga via tool.

### LLM fine-tuning / training

Fora de escopo.

### Visual IDE / agent builder GUI

UI separada como pacote opcional. Core não.

### Marketplace de agentes

Marketplace é produto SaaS. Wake é substrato OSS.

### Billing, quotas, multi-tenant comercial

Quem quiser comerciar Wake-hosted constrói por cima.

### Suporte oficial a OpenAI Responses API como primary

Wake é Claude-first. OpenAI/Gemini via adapter degradado é Day-30+. Tornar OpenAI primary seria refazer event schema. Não.

### Multiagent coordinator avançado

Existem outcomes/multiagent em research preview na Anthropic, AG2 já faz multi-framework interop. Wake provê primitivas (parent_id em eventos, child sessions). Coordinator avançado vira pacote separado.

### LLM-as-judge / outcomes

Idem. Vira `wake-outcomes` package, não core.

### Skills com progressive disclosure

Anthropic-specific. Wake pode suportar como caso especial de tool registry, mas não é prioridade.

### Otimização automática de prompt

Fora de escopo.

### Hosted SaaS proprietário do Wake

OSS first. Hosted comercial fica para terceiros.

---

## Decisões de roadmap explicitamente adiadas

Estas decisões precisam ser tomadas mas não no Day-1. Listadas para não esquecer:

- **Q1 — Linguagem do runtime principal:** Python (default rápido), Go (single binary), ou Rust (perf máxima)? Day-1 começa Python, Day-90 decide se reescrita justificada.
- **Q2 — Backend de durabilidade:** caseiro Postgres ou plugar Temporal/Restate? Day-1 caseiro. Day-30 decide.
- **Q3 — Modelo de governança:** Linux Foundation, OSS Capital, ou comunidade direta? Day-90 decide.
- **Q4 — Licença final:** MIT, Apache 2.0, Elastic 2.0, SSPL? Day-30 decide com input de potenciais usuários enterprise.

---

## Critérios de cancelamento / pivot

Wake é uma aposta. Vale a pena reconhecer quando errar.

**Sinais para cancelar/pivotar:**

- Dentro de 6 meses, OpenHands V1 SDK publica HarnessAdapter público equivalente — Wake vira contribuição de volta ou fork
- MAF / OpenAI / LangChain anunciam padrão concorrente com adoção real — Wake adota o padrão alheio
- Comunidade não vem (após 6 meses, <500 stars, <3 contribuidores externos) — Wake vira projeto pessoal ou descontinuado
- Nenhum framework principal adota Wake adapter oficialmente — sinal de que a tese não interessa

**Não-sinais (não cancelar por isso):**

- Outro projeto OSS lançar coisa parecida sem ABI pública — não compete
- MAF crescer rápido — espaço enterprise diferente
- Multica crescer mais — espaço CLI orchestration diferente

---

## Resumo

```
Day 1:    spec congelada + runtime mínimo + 1 adapter
Day 30:   4 adapters + Postgres + Vault + sandbox-runtime
Day 90:   multi-node deploy + UI + 2-3 adapters externos
Day 180:  spec v1.0 + audit security + endorsements
Day 365:  padrão de facto + comunidade auto-sustentável
```

Wake é projeto de 12 meses para impacto. Wake é projeto de 3 meses para validar. Wake é projeto de 2 semanas para existir publicamente.
