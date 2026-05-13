# LANDSCAPE

Panorama do ecossistema OSS de agentes de IA em 2026, organizado por camada. Para cada camada, projetos relevantes e como Wake se relaciona com eles.

Este doc responde: "isso aqui já existe?" — A resposta é: pedaços sim, a costura inteira não.

---

## Visão por camadas

```
┌────────────────────────────────────────────────────────────────────┐
│                       APLICAÇÕES DE AGENTES                         │
│              (chatbots, coding agents, research, etc.)              │
├────────────────────────────────────────────────────────────────────┤
│                       FRAMEWORKS DE AGENTES                         │
│        LangGraph · CrewAI · Pydantic AI · AG2 · MAF · etc.         │
├────────────────────────────────────────────────────────────────────┤
│                   ▼ HarnessAdapter ABI (Wake) ▼                     │
│                                                                     │
│                       RUNTIME / SUBSTRATO                           │
│      OpenHands V1 · OpenClaw · MAF · Wake · Deep Agents Deploy     │
├────────────────────────────────────────────────────────────────────┤
│                       DURABLE EXECUTION                             │
│      Temporal · Restate · DBOS · Inngest · Conductor               │
├────────────────────────────────────────────────────────────────────┤
│   SANDBOX     │     VAULT      │     MEMORY     │   OBSERVABILITY   │
│   E2B         │   Infisical    │     Letta      │   Langfuse        │
│   sandbox-rt  │   HashiCorp    │     Mem0       │   Phoenix         │
│   Daytona     │                │     Zep        │   Helicone        │
│   Modal       │                │     Cognee     │   Braintrust      │
├────────────────────────────────────────────────────────────────────┤
│   MODEL ROUTER       │       TOOL PROTOCOL      │   AGENT SPEC      │
│   LiteLLM            │       MCP                │   Open Agent Spec │
│   OpenRouter         │       A2A                │                   │
│   agentgateway       │                          │                   │
└────────────────────────────────────────────────────────────────────┘
```

Wake fica na camada **substrato/runtime**, expondo a **HarnessAdapter ABI** para cima e reusando componentes das camadas abaixo.

---

## Camada: Frameworks de agentes

Camada **acima** de Wake. Esses são os "harnesses" que rodam em Wake via adapters.

| Projeto | Stars | License | Tipo | Adapter Wake planejado |
|---|---|---|---|---|
| LangChain | 100k+ | MIT | Framework geral | via LangGraph |
| LangGraph | 15k+ | MIT | Graph-based agent framework | ✓ Day-1 |
| LlamaIndex | 40k+ | MIT | Data + agent framework | futuro |
| CrewAI | 30k+ | MIT | Multi-agent | ✓ Day-1 |
| Pydantic AI | 10k+ | MIT | Type-safe, model-agnostic | ✓ Day-1 |
| Microsoft Agent Framework | em alta | MIT | Production agent framework | ✓ Day-30 |
| AG2 (ex-AutoGen) | 40k+ | Apache 2.0 | Multi-agent + interop | ✓ Day-30 |
| AutoGen (Microsoft) | 40k+ | MIT | Multi-agent | via MAF |
| SmolAgents (HuggingFace) | crescente | Apache 2.0 | Small, hackable | futuro |
| Agno (ex-Phidata) | 39k | open core | "AgentOS" production | futuro |
| Mastra | 22k+ | Apache 2.0 | TS framework | futuro |
| Strands Agents (AWS) | ativo | open | Model-driven, MCP-native | futuro |
| Dapr Agents | ativo | Apache 2.0 | Dapr-backed | futuro |
| BeeAI (IBM, LF) | LF-hosted | Apache 2.0 | Python + TS | futuro |
| Claude Agent SDK | NA | proprietary | Anthropic SDK | ✓ Day-1 |
| OpenAI Agents SDK | NA | proprietary | OpenAI SDK | ✓ Day-30 |

**Relação com Wake:** estes não são competidores. São consumers da HarnessAdapter ABI. Wake roda eles.

---

## Camada: Coding agents (harnesses opinativos)

Camada também acima de Wake, mas mais opinativa (vem com harness + UI + integrations bundled).

| Projeto | Stars | License | Sobre |
|---|---|---|---|
| OpenHands (ex-OpenDevin) | 68.6k | MIT | Coding agent completo, V1 SDK paper publicado |
| goose (Block) | 32k | Apache 2.0 | Rust, MCP-first, 70+ extensions |
| Aider | 41k | Apache 2.0 | Terminal, git-first |
| Cline | 58k | Apache 2.0 | VS Code extension |
| Continue.dev | 31k | Apache 2.0 | IDE-integrated |
| Tabby | 33k | Apache 2.0 | Self-hosted code assistant |
| Open Interpreter | 50k | AGPL | Local code execution |
| SWE-agent | 14k | MIT | Eval-focused coding agent |
| Devstral | ativo | Apache 2.0 | Mistral coding agent |
| Smol Developer | menor | MIT | Hackable codegen |

**Relação com Wake:** OpenHands V1 é o maior risco arquitetural — seu paper descreve uma arquitetura quase idêntica à de Wake. Se eles desacoplam o Workspace e publicam um adapter público, consomem a tese. Wake precisa publicar a spec antes.

Os outros são produtos verticais. Não competem diretamente, mas devs deles podem ser usuários de Wake se quiserem rodar agentes coding fora do tooling embarcado.

---

## Camada: Runtime / substrato

**Esta é a camada onde Wake compete.**

### Closest match: OpenClaw Managed Agents

- **URL:** github.com/stainlu/openclaw-managed-agents
- **Stars:** ~410 | MIT | v0.2.0 Apr 2026
- **Sobre:** Clone explícito da API Managed Agents. Mesma estrutura Agent/Environment/Session/Event, JSONL event log, Docker container por sessão, vault, MCP.
- **Cobertura da tese Wake:** ~80%
- **Gap principal:** roda só o harness próprio dele. Não tem HarnessAdapter ABI publicada. Harness vive dentro do container (não fora).
- **Risco:** se eles adicionarem adapter abstraction, fecham o gap. Mas momentum atual é menor que outros.

### OpenHands V1 SDK

- **URL:** github.com/OpenHands/OpenHands
- **Stars:** 68.6k | MIT | V1 SDK paper arxiv 2511.03690
- **Sobre:** Coding agent com arquitetura "stateless Agent + Conversation com EventLog imutável + Workspace executável."
- **Cobertura da tese Wake:** ~85% na arquitetura, ~40% no posicionamento.
- **Gap principal:** Workspace é environment-specific (não generic `execute(name, input)`). Não tem ABI pública para outros frameworks plugarem. Posicionamento é "coding agent product", não "substrato neutro."
- **Risco:** o paper já descreve as primitivas certas. Se o team OpenHands extrair o V1 SDK como produto separado e publicar HarnessAdapter, é game over. **Risco #1.**

### Microsoft Agent Framework 1.0

- **URL:** github.com/microsoft/agent-framework
- **License:** MIT | v1.0 GA Apr 2026
- **Sobre:** SDK + runtime Python/.NET com checkpointing, multi-provider, MCP, A2A, pluggable memory.
- **Cobertura da tese Wake:** ~55%
- **Gap principal:** é o framework + runtime juntos. Não foi desenhado para hospedar outros frameworks. Não tem ABI aberta para harnesses externos.
- **Risco:** distribuição enterprise + Azure/Foundry vai fazer dele o padrão corporativo default. Concorre por mindshare.

### LangChain Deep Agents Deploy

- **URL:** langchain.com/blog/deep-agents-deploy
- **License:** MIT | lançado Q1 2026
- **Sobre:** Explicitly "open alternative to Claude Managed Agents." Self-host, sandbox plugável, MCP both as consumer and producer.
- **Cobertura da tese Wake:** ~60%
- **Gap principal:** harness é Deep Agents (LangGraph-based). Não suporta outros frameworks como peers.
- **Risco:** integra-se ao ecossistema LangChain massivo. Usuários LangChain default lá.

### Multica

- **URL:** github.com/multica-ai/multica
- **Stars:** ~10.7k (explosivo Q1-Q2 2026) | MIT
- **Sobre:** Control plane que despacha pra CLIs de coding agents (Claude Code, Codex, Gemini CLI, OpenClaw). Não tem runtime próprio.
- **Cobertura da tese Wake:** 50% no posicionamento, 0% no substrato.
- **Gap principal:** delega tudo do runtime aos CLIs.
- **Risco:** se eles pivotam para framework-agnostic runtime nativo, viram Wake com mais momentum.

---

## Camada: Durable execution

Camada **abaixo** de Wake. Wake pode usar um destes internamente (ou implementar próprio).

| Projeto | Tipo | Wake usaria? |
|---|---|---|
| Temporal | Workflow engine genérico, Go/Java/Python | possivelmente como backend opcional |
| Restate | Durable handlers, journal-backed | possivelmente |
| DBOS | Postgres/SQLite, durable workflows | possivelmente como reference impl |
| Inngest | Event-driven durable execution, TS-first | menos provável |
| Trigger.dev | TS-first durable workflows | menos provável |
| Conductor OSS | Netflix event-driven, Java | não |
| Cloudflare Workflows | Plataforma específica | não |
| Kitaru (ZenML) | Python decorator-based, replay | possivelmente |
| Pydantic AI + Restate | combo já popular | os adapter Wake usa por baixo |

**Relação com Wake:** Wake pode implementar durabilidade caseira (Postgres + advisory locks) ou plugar um destes. Decisão será baseada em complexidade vs ganho.

---

## Camada: Sandbox

Camada abaixo de Wake. Wake reusa.

| Projeto | Tipo | Wake suporta? |
|---|---|---|
| anthropic sandbox-runtime | bubblewrap + seccomp + proxy, OSS | ✓ default backend |
| E2B | Firecracker microVMs, ~150ms cold start | ✓ via adapter |
| Daytona | Docker-based, sub-90ms cold start | ✓ via adapter |
| Modal | Serverless, closed | ✓ via adapter |
| Vercel Sandbox | Firecracker, AI-focused | ✓ via adapter |
| Docker (vanilla) | Padrão indústria, isolamento fraco | ✓ default fallback |
| gVisor | Kernel userspace | futuro |
| Firecracker (raw) | microVMs | futuro |

**Relação com Wake:** Wake é agnóstico ao backend de sandbox via `SandboxAdapter` interface.

---

## Camada: Vault / credenciais

Camada abaixo de Wake. Wake reusa.

| Projeto | Sobre | Wake usa? |
|---|---|---|
| Infisical Agent Vault | MITM HTTPS proxy, substitui placeholders por creds | ✓ default |
| HashiCorp Vault | Genérico enterprise | ✓ via plugin |
| AWS Secrets Manager | Cloud-specific | ✓ via plugin |
| Doppler | SaaS secrets | ✓ via plugin |
| dotenv-vault | Encriptado .env | viável |

**Relação com Wake:** Infisical Agent Vault é literalmente o padrão de design que a tese precisa. Wake adota como default integrando.

---

## Camada: Memória

Camada **lateral** a Wake (não cima nem baixo). Pluga via tools ou via skills.

| Projeto | Sobre |
|---|---|
| Letta (ex-MemGPT) | Memory-first agent runtime, três-tiers |
| Mem0 | Universal memory layer, 21+ integrations |
| Zep / Graphiti | Temporal knowledge graph |
| Cognee | GraphRAG, deep knowledge retrieval |

**Relação com Wake:** Wake não embute memory. Adapters de framework podem injetar memory tools que falam com qualquer um destes.

---

## Camada: Observabilidade

Camada **paralela** a Wake. Consumers do event log.

| Projeto | Sobre | Integração |
|---|---|---|
| Langfuse | OSS leader, self-host, ClickHouse Series D | OTel consumer |
| Arize Phoenix | Elastic 2.0, OpenInference-native | OTel consumer |
| Helicone | Proxy-based simplest install | proxy mode |
| Braintrust | Eval-first | OTel consumer |
| W&B Weave | ML obs platform | OTel consumer |
| Literal AI | LLM obs | OTel consumer |
| Lunary | Open core | OTel consumer |
| Laminar | Agent rollout debugger, session replay | OTel consumer |
| LangSmith | LangChain-native, closed | custom adapter |

**Relação com Wake:** Wake emite OpenTelemetry spans para cada event. Qualquer obs platform consome.

---

## Camada: Model routing

Camada abaixo de Wake. Wake reusa.

| Projeto | Sobre | Wake usa? |
|---|---|---|
| LiteLLM | OpenAI-compatible across 100+ providers, OSS | ✓ default |
| OpenRouter | SaaS marketplace | ✓ via LiteLLM |
| Portkey | Observability gateway, self-host opt | ✓ via adapter |
| Vercel AI Gateway | Provider abstraction | ✓ via adapter |
| agentgateway (LF) | AI-native, MCP + A2A + LLM gateway, Rust | ✓ para egress |

**Relação com Wake:** LiteLLM faz model routing. agentgateway faz MCP/A2A egress filtering. Wake combina os dois.

---

## Camada: Protocolos / specs abertas

Wake **consome** estas specs, não inventa próprias onde existirem.

| Spec | Mantenedor | Wake usa? |
|---|---|---|
| MCP (Model Context Protocol) | Anthropic + comunidade | ✓ first-class |
| A2A (Agent-to-Agent) | Google + comunidade | ✓ futuro |
| Open Agent Specification | Oracle + MS + Google | ✓ futuro (agent definition) |
| OpenTelemetry / OpenInference | CNCF + Arize | ✓ para tracing |
| OpenAPI / JSON Schema | indústria | ✓ para tool schemas |

**Relação com Wake:** convergência da indústria nessas specs é boa pra Wake — reduz superfície que Wake precisa definir. Wake só inventa onde nada existe: **HarnessAdapter ABI**.

---

## Whitespace: onde Wake é único

Após mapear tudo acima, há duas funções que NENHUM projeto faz:

1. **HarnessAdapter ABI publicada como spec aberta.** Cada framework hoje é silo. Não há protocolo público para "esse framework roda nesse runtime."

2. **Sandbox-as-tool com harness fora do container.** Anthropic faz internamente. OpenClaw, Goose, Cline rodam harness dentro do container. OpenHands V1 chega perto mas Workspace é environment-specific.

O resto é commodity ou está sendo construído.

---

## Convergência prevista (12 meses)

Predição honesta sobre como essa camada vai evoluir:

- **OpenHands** vira referência de "runtime + coding harness bundled" — domina o vertical coding
- **MAF** vira default enterprise — Microsoft channel + Azure
- **Open Agent Spec** vira o agent definition format default — adotado por LangChain/CrewAI/etc.
- **MCP** se consolida como tool protocol universal
- **LiteLLM** vira default model router
- **Infisical Vault** ou similar vira default credential layer

O slot "framework-agnostic substrate" será preenchido por **alguém** nesse período. Wake aposta em ser esse alguém via HarnessAdapter spec aberta + adapters de referência.

Janela: 6-12 meses para Wake publicar e ganhar mindshare antes da convergência fechar.
