# COMPARISON

Comparações lado a lado entre Wake e os projetos mais próximos. Honesto sobre onde cada um é melhor.

---

## Wake vs Anthropic Managed Agents (produto hosted)

|  | Anthropic Managed Agents | Wake |
|---|---|---|
| **Modelo** | Hosted, SaaS | Self-host, OSS |
| **Billing** | $0.05/h/container | sua infra |
| **API surface** | 4 primitives (Agent/Env/Session/Event) | mesmas 4 (compat superficial) |
| **Provider LLM** | Claude only | Claude default + BYO via LiteLLM |
| **Harness** | Proprietário, Claude-only | HarnessAdapter ABI, qualquer framework |
| **Sandbox** | Anthropic-managed | sandbox-runtime / Docker / Firecracker (plugável) |
| **Vault** | Anthropic-managed | Infisical Agent Vault (plugável) |
| **MCP support** | ✓ | ✓ |
| **Outcomes/eval** | beta (research preview) | não no core, pacote separado futuro |
| **Multiagent** | beta (research preview) | não no core, pacote separado futuro |
| **Memory** | beta | não no core, integra Letta/Mem0 |
| **Skills** | ✓ | parcial (via tool registry) |
| **Branding restriction** | "Powered by Claude" obrigatório | nenhuma |
| **Status** | GA beta | pre-alpha |

**Onde Anthropic é melhor:**
- UX out-of-box absurdamente refinada
- Otimizações server-side (prompt caching, compaction automática)
- Outcomes/multiagent/memory já existem (beta)
- Sandbox enterprise-grade já testado em produção
- TTFT melhor (otimização interna inalcançável fora)

**Onde Wake é melhor:**
- Self-host total, sem billing
- Sem branding obrigatório
- Multi-framework (não só Claude SDK)
- Multi-provider (não só Claude)
- Sandbox/vault/store plugáveis
- Audit log próprio, sem dependência externa

**Verdade desconfortável:** Wake nunca vai bater Managed Agents em UX e otimização. Wake vence em controle e flexibilidade.

---

## Wake vs OpenClaw Managed Agents

|  | OpenClaw | Wake |
|---|---|---|
| **Posicionamento** | Clone explícito Managed Agents OSS | Substrato framework-agnostic |
| **API surface** | Idêntica Managed Agents | Idêntica + extensões |
| **Harness** | OpenClaw próprio (locked) | HarnessAdapter ABI |
| **Harness location** | Inside container | Outside container (Wake) |
| **Multi-framework** | ❌ | ✓ |
| **Multi-provider** | ✓ | ✓ |
| **Sandbox** | Docker | Plugável |
| **Vault** | Próprio | Infisical (default) |
| **MCP** | ✓ | ✓ |
| **Stars** | ~410 | 0 (greenfield) |
| **Maturity** | v0.2.0, ativo | pre-alpha |

**Onde OpenClaw é melhor:**
- Existe e funciona hoje
- Comunidade pequena mas real
- Direto e simples (menos abstração)

**Onde Wake é melhor:**
- HarnessAdapter ABI permite outros frameworks
- Harness fora do container = resiliência e replay melhores
- Reusa componentes maduros (sandbox-runtime, Infisical, LiteLLM)

**Quando OpenClaw é a escolha certa:**
- Você quer Managed Agents OSS direto, sem multi-framework
- Você só usa Claude e tudo bem
- Você não quer wait pra projeto pre-alpha amadurecer

**Quando Wake é a escolha certa:**
- Você tem múltiplos frameworks na empresa
- Você quer audit log + replay determinístico nativos
- Você precisa de standard publicada (não single-vendor lock-in)

---

## Wake vs OpenHands V1

|  | OpenHands V1 | Wake |
|---|---|---|
| **Posicionamento** | Coding agent product | Substrato framework-agnostic |
| **Arquitetura** | Stateless Agent + EventLog + Workspace | Idêntica (Wake adota mesmo padrão) |
| **Harness flexível** | Próprio (closed component model) | HarnessAdapter ABI público |
| **Sandbox** | Workspace (local/Docker/Remote) | Plugável genérico |
| **MCP** | ✓ | ✓ |
| **Multi-provider** | ✓ (via LiteLLM) | ✓ (via LiteLLM) |
| **Vault** | SecretRegistry (próprio) | Infisical (default) |
| **UI/CLI bundled** | ✓ (web, CLI, GitHub App) | CLI only no core, UI separada |
| **Foco** | Coding agents | Geral (coding é caso de uso) |
| **Stars** | 68.6k | 0 |
| **Funding** | $18.8M Series A | nenhum |

**Verdade brutal:** OpenHands V1 é **arquiteturalmente quase idêntica** a Wake. A diferença é posicionamento — OpenHands é produto coding-agent, Wake é substrato neutro.

**Onde OpenHands é melhor:**
- Massa crítica enorme (68k stars)
- Funding pra durar
- Produto coding completo e refinado
- Evals e benchmarks (SWE-bench foco)
- UI/CLI/GitHub App bundle pronto

**Onde Wake é melhor (na tese, ainda não na prática):**
- HarnessAdapter ABI como spec pública (OpenHands tem abstrações internas, não API pública)
- Posicionamento neutro (não é "coding agent")
- Sandbox-as-tool genérico (vs Workspace específico)
- Drop-in compat com Managed Agents API

**Risco real:** se OpenHands publicar uma versão extraída do V1 SDK como "substrato neutro" com HarnessAdapter abstraction, Wake fica redundante. **Esse é o maior risco arquitetural ao projeto.**

**Mitigação:** Wake foca em (a) publicar a spec antes, (b) provar generalidade com 4 adapters Day-1, (c) evitar acoplamento com coding-agent UI/features.

---

## Wake vs Microsoft Agent Framework

|  | MAF 1.0 | Wake |
|---|---|---|
| **Posicionamento** | Framework + runtime bundled | Substrato sob frameworks |
| **Linguagens** | Python + .NET | Python + TS |
| **Checkpointing** | ✓ | Event log (mais granular) |
| **Multi-provider** | ✓ | ✓ |
| **MCP** | ✓ | ✓ |
| **A2A** | ✓ | futuro |
| **Distribution** | Microsoft (Azure/Foundry) | Comunidade OSS |
| **Sandbox** | não nativo | nativo (plugável) |
| **Vault** | Mem0/Redis/Neo4j/Foundry | Infisical (default) |
| **Adapter open spec** | ❌ | ✓ HarnessAdapter ABI |
| **Status** | GA Apr 2026 | pre-alpha |

**Onde MAF é melhor:**
- Maturity e GA
- Microsoft distribution channel
- Azure/Foundry integration nativa
- Enterprise blast radius

**Onde Wake é melhor:**
- Framework-agnostic (MAF é framework próprio)
- Não é Microsoft-aligned (importante pra alguns)
- Sandbox + vault como primitivas

**Quando MAF é a escolha:**
- Você está em stack Azure/Microsoft
- Você quer framework + runtime tudo em um
- Você precisa de A2A multi-agent enterprise

**Quando Wake é a escolha:**
- Você usa múltiplos frameworks ou nenhum específico
- Você quer self-host fora de Microsoft cloud
- Você precisa de event log replay + sandbox-as-tool

---

## Wake vs LangGraph (framework, não runtime)

Comparação não é apples-to-apples (LangGraph é framework, Wake é runtime), mas pessoas confundem.

|  | LangGraph | Wake |
|---|---|---|
| **Tipo** | Agent framework (StateGraph) | Runtime substrato |
| **Você escreve** | StateGraph + nodes | nada (usa framework de escolha) |
| **Durabilidade** | Checkpointers (SQLite/Postgres/Dynamo) | Event log durável |
| **Sandbox** | ❌ (tools rodam in-process) | ✓ |
| **Vault** | ❌ | ✓ |
| **Multi-framework** | é o framework | suporta vários |
| **Replay** | Time-travel via checkpoints | Replay via event log |

**Verdade:** Wake e LangGraph são complementares, não competidores. Você usa LangGraph para escrever o agente; usa Wake para hospedá-lo com sandbox/vault/durabilidade.

```python
from langgraph.graph import StateGraph
from wake.adapters.langgraph import WakeAdapter

graph = StateGraph(...)  # você escreve o grafo
adapter = WakeAdapter(graph)
wake.session.run(adapter, input="...")  # Wake hospeda
```

---

## Wake vs Temporal (durable execution genérico)

|  | Temporal | Wake |
|---|---|---|
| **Tipo** | Durable execution engine genérico | Substrato agent-specific |
| **Use case** | Qualquer workflow (não só agentes) | Agentes |
| **Event log** | Journal próprio (proprietário) | Open schema agent-specific |
| **Sandbox** | ❌ (você fornece) | ✓ |
| **Tool ABI** | ❌ (você define) | ✓ MCP + custom |
| **Vault** | ❌ (você fornece) | ✓ Infisical |
| **MCP** | ❌ | ✓ first-class |
| **Linguagens** | Go, Java, Python, TS, PHP, Ruby | Python, TS |

**Verdade:** Temporal é mais genérico, Wake é mais agent-specific. Você poderia construir Wake em cima de Temporal (e Wake pode opcionalmente usar Temporal como backend de durabilidade). Mas usar Temporal cru pra agentes obriga você a redescobrir event schema, tool ABI, sandbox, vault.

**Quando Temporal é a escolha:**
- Você tem workflows não-agentes também
- Você quer flexibilidade total
- Você já investiu em Temporal

**Quando Wake é a escolha:**
- Foco é agentes
- Quer event schema canônico (compat com Managed Agents API)
- Quer sandbox/vault/tool ABI prontos

---

## Wake vs Multica

|  | Multica | Wake |
|---|---|---|
| **Tipo** | Control plane sobre CLIs | Substrato + adapters |
| **Roda harness?** | Não (delega aos CLIs) | Sim (HarnessAdapter ABI) |
| **CLIs suportados** | Claude Code, Codex, Gemini CLI, OpenClaw | qualquer framework via adapter |
| **Frameworks SDK** | ❌ | LangGraph, CrewAI, Pydantic AI, Claude SDK |
| **Event log** | Mensagem normalizada (não event log durável) | Event log append-only |
| **Sandbox** | Delega aos CLIs | Nativo plugável |
| **Vault** | Delega aos CLIs | Infisical nativo |
| **Stars** | ~10.7k (explosivo) | 0 |
| **Posicionamento** | "Pare de tentar ser runtime, seja control plane" | "Seja o runtime/substrato neutro" |

**Verdade:** Multica é uma resposta diferente ao mesmo problema. Multica diz "use os CLIs existentes, eu só orquestro." Wake diz "ofereça o substrato, frameworks plugam."

**Onde Multica é melhor:**
- Você só usa coding-agent CLIs (Claude Code, Codex, etc.)
- Você não quer construir agentes próprios
- Massa crítica de stars

**Onde Wake é melhor:**
- Você usa SDKs de frameworks (não só CLIs)
- Você quer audit log / replay nativos
- Você quer self-host total sem dependência de CLIs externos

**Risco para Wake:** se Multica adicionar suporte a frameworks SDK (não só CLIs) e runtime nativo, convergem nas teses. Multica tem distribuição maior.

---

## Wake vs LangChain Deep Agents Deploy

|  | Deep Agents Deploy | Wake |
|---|---|---|
| **Posicionamento** | "Open alternative to Claude Managed Agents" | Mesma cosa + framework-agnostic |
| **Harness** | Deep Agents (LangGraph-based) | Qualquer via HarnessAdapter |
| **Sandbox** | Plugável (Daytona/Runloop/Modal/LangSmith) | Plugável (sandbox-runtime/Docker/etc.) |
| **MCP** | ✓ both consumer e producer | ✓ |
| **Multi-provider** | ✓ | ✓ |
| **Self-host** | ✓ via LangSmith Deployments | ✓ direto |
| **Event log público** | não documentado | ✓ schema canônico |
| **Vault** | não documentado | Infisical |
| **Lock-in LangChain** | sim | nenhum |

**Onde Deep Agents Deploy é melhor:**
- Existe e funciona
- LangChain ecosystem massivo por trás
- LangSmith obs integrada

**Onde Wake é melhor:**
- Sem lock-in LangChain
- Event log público com schema canônico
- HarnessAdapter ABI permite mais frameworks
- Audit log/replay como primitivas

**Quando Deep Agents Deploy é a escolha:**
- Você já está fundo em LangChain
- LangSmith pago é aceitável
- Não precisa de outros frameworks

**Quando Wake é a escolha:**
- Você quer neutralidade entre frameworks
- Você quer self-host sem SaaS attached
- Você precisa de event log standard

---

## Matriz resumida

| Feature | Wake | OpenHands V1 | OpenClaw | Multica | MAF | Deep Agents | Managed Agents |
|---|---|---|---|---|---|---|---|
| Event log append-only | ✓ | ✓ | ✓ | parcial | ❌ | parcial | ✓ |
| Harness stateless | ✓ | ✓ | parcial | n/a | ❌ | parcial | ✓ |
| Sandbox-as-tool | ✓ | parcial | ❌ | n/a | ❌ | parcial | ✓ |
| HarnessAdapter ABI público | ✓ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Vault + proxy | ✓ | ✓ | ✓ | n/a | parcial | parcial | ✓ |
| MCP first-class | ✓ | ✓ | ✓ | parcial | ✓ | ✓ | ✓ |
| Self-host total | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ❌ |
| Multi-framework | ✓ | ❌ | ❌ | só CLIs | ❌ | ❌ | ❌ |
| Multi-provider LLM | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ❌ |
| Replay determinístico | ✓ | parcial | parcial | ❌ | parcial | parcial | ✓ |
| Maturity | pre-alpha | GA | beta | beta | GA | beta | GA beta |

A coluna "Wake" é aspiracional (pre-alpha). Os outros refletem realidade hoje.

A coluna que importa: **HarnessAdapter ABI público.** Wake é o único marcando ✓ — e essa é a tese inteira.
