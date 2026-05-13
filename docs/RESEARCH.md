# RESEARCH

Todas as referências, papers, repos e links que informaram o design de Wake. Organizado por tema.

---

## Anthropic Managed Agents (a inspiração direta)

### Documentação oficial

- **[Managed Agents Overview](https://platform.claude.com/docs/en/managed-agents/overview)** — O que é, primitivas, lifecycle, billing, beta access. Beta header `managed-agents-2026-04-01`. Rate limits 300/600 rpm.
- **[Agent Setup](https://platform.claude.com/docs/en/managed-agents/agent-setup)** — Schema completo do Agent: name, model, system, tools, mcp_servers, skills, multiagent, description, metadata. Versionamento, archive.
- **[Environment Setup](https://platform.claude.com/docs/en/managed-agents/environments)** — Container template, package managers (apt/cargo/gem/go/npm/pip), networking (unrestricted/limited), allowed_hosts, allow_package_managers, allow_mcp_servers.
- **[Sessions](https://platform.claude.com/docs/en/managed-agents/sessions)** — Two-step lifecycle (create → send event), pin to version, vault_ids, statuses (idle/running/rescheduling/terminated).

### Engineering posts (oxigênio arquitetural)

- **[Scaling Managed Agents: Decoupling the brain from the hands](https://www.anthropic.com/engineering/managed-agents)** — **O paper-chave.** Descreve brain/hands split, session log durável, harness stateless com wake/getEvents/emitEvent, sandbox como tool, vault + proxy. TTFT p50 -60%, p95 -90%.
- **[Building agents with the Claude Agent SDK](https://claude.com/blog/building-agents-with-the-claude-agent-sdk)** — Filosofia "give your agents a computer." Agent loop: gather context → take action → verify work → repeat. Verificação: rules-based, visual, LLM-as-judge.
- **[Making Claude Code more secure and autonomous with sandboxing](https://www.anthropic.com/engineering/claude-code-sandboxing)** — Threat: prompt injection. Filesystem isolation + network isolation. Reduz prompts de permissão em 84% internamente.
- **[Claude Code auto mode: a safer way to skip permissions](https://www.anthropic.com/engineering/claude-code-auto-mode)** — Two-layer defense: prompt-injection probe + transcript classifier (Sonnet 4.6). Stage 1: 8.5% FP / 6.6% FN. Full pipeline: 0.4% FP / 17% FN.

---

## Tool use, MCP, code execution

- **[Tool use with Claude](https://platform.claude.com/docs/en/docs/build-with-claude/tool-use)** — Client vs server tools, tool_choice options, agentic loop, fine-grained streaming. `strict: true` para conformância de schema.
- **[Code execution tool](https://platform.claude.com/docs/en/docs/agents-and-tools/tool-use/code-execution-tool)** — `code_execution_20250825` e `code_execution_20260120`. Container 5GB/5GB/1cpu, internet disabled, 30-day expiration, 1550 hours free/month then $0.05/h. Multi-environment warning explícito.
- **[Model Context Protocol](https://modelcontextprotocol.io/)** — "USB-C for AI applications." Open protocol para conectar AI a data sources, tools, workflows.

---

## Sandbox e segurança

- **[anthropic-experimental/sandbox-runtime](https://github.com/anthropic-experimental/sandbox-runtime)** — **Componente reusável central.** OS-level filesystem + network sandboxing. macOS via sandbox-exec/seatbelt, Linux via bubblewrap + seccomp BPF + Unix socket relay via socat. HTTP/HTTPS proxy + SOCKS5 proxy.
- **[Infisical Agent Vault](https://github.com/Infisical/agent-vault)** — MITM HTTPS proxy que substitui placeholders por credenciais reais. Integra com Claude Code, OpenClaw, Hermes. Reusable componente para o vault layer de Wake.

---

## Runtimes / substratos concorrentes/adjacentes

### Closest matches

- **[OpenClaw Managed Agents](https://github.com/stainlu/openclaw-managed-agents)** — Clone explícito Managed Agents OSS. MIT. ~410 stars. v0.2.0 Apr 2026.
- **[OpenHands V1 SDK](https://github.com/OpenHands/OpenHands)** — Coding agent com EventLog imutável. Paper: [arxiv 2511.03690](https://arxiv.org/html/2511.03690v1). 68.6k stars. MIT. $18.8M Series A.
- **[Multica](https://github.com/multica-ai/multica)** — Control plane sobre CLIs (Claude Code, Codex, Gemini CLI). 10.7k stars. Q1-Q2 2026 momentum.
- **[Microsoft Agent Framework](https://github.com/microsoft/agent-framework)** — v1.0 GA Apr 2026. MIT. Python + .NET. Checkpointing, MCP, A2A, multi-provider.
- **[LangChain Deep Agents Deploy](https://www.langchain.com/blog/deep-agents-deploy-an-open-alternative-to-claude-managed-agents)** — Explicit "open alternative to Claude Managed Agents." Self-host via LangSmith Deployments.

### Mais distantes

- **[Kitaru (ZenML)](https://github.com/zenml-io/kitaru)** — Python decorator-based durable execution. `@flow`/`@checkpoint`, `kitaru.wait()` pause/resume, artifact lineage.
- **[Inside Claude Managed Agents (Pluto Security writeup)](https://pluto.security/blog/inside-claude-managed-agents/)** — Análise externa da arquitetura Managed Agents.

---

## Frameworks de agentes (potenciais adapters)

### Tier 1 (Day-1 adapters)

- **[LangGraph](https://github.com/langchain-ai/langgraph)** — Graph-based agent framework, durable execution via checkpointers.
- **[CrewAI](https://github.com/crewAIInc/crewAI)** — Multi-agent orchestration, 30k+ stars, MIT.
- **[Pydantic AI](https://github.com/pydantic/pydantic-ai)** — Type-safe agents, native MCP/A2A/durable-execution.
- **[Claude Agent SDK](https://github.com/anthropics/anthropic-sdk-python)** — Anthropic SDK.

### Tier 2 (Day-30+ adapters)

- **[LangChain](https://github.com/langchain-ai/langchain)** — 100k+ stars. Geral framework.
- **[LlamaIndex](https://github.com/run-llama/llama_index)** — Data + agent framework.
- **[Microsoft AutoGen → Agent Framework](https://github.com/microsoft/agent-framework)** — Production successor.
- **[AG2 (ex-AutoGen)](https://github.com/ag2ai/ag2)** — Multi-framework interop.
- **[OpenAI Agents SDK](https://github.com/openai/openai-agents-python)** — OpenAI's SDK.
- **[Strands Agents](https://github.com/strands-agents/sdk-python)** — AWS, model-driven, MCP-native.
- **[Dapr Agents](https://github.com/dapr/dapr-agents)** — Apache 2.0, Dapr-backed.
- **[Pydantic AI](https://ai.pydantic.dev/)** — Type-safe.
- **[SmolAgents (HuggingFace)](https://github.com/huggingface/smolagents)** — Small, hackable.
- **[Agno (ex-Phidata)](https://github.com/agno-agi/agno)** — "AgentOS" production.
- **[Mastra](https://github.com/mastra-ai/mastra)** — TypeScript.
- **[BeeAI (IBM, LF)](https://github.com/i-am-bee/beeai-framework)** — Linux Foundation.

---

## Coding agents (harnesses opinativos)

- **[OpenHands (ex-OpenDevin)](https://github.com/All-Hands-AI/OpenHands)** — 68.6k stars.
- **[goose (Block)](https://github.com/block/goose)** — Rust, 32k stars, MCP-first.
- **[Aider](https://github.com/Aider-AI/aider)** — Terminal, git-first.
- **[Cline](https://github.com/cline/cline)** — VS Code extension.
- **[Continue.dev](https://github.com/continuedev/continue)** — IDE-integrated.
- **[Tabby](https://github.com/TabbyML/tabby)** — Self-hosted code assistant.
- **[Open Interpreter](https://github.com/OpenInterpreter/open-interpreter)** — Local code execution.
- **[SWE-agent](https://github.com/SWE-agent/SWE-agent)** — Eval-focused.

---

## Durable execution (camada abaixo de Wake)

- **[Temporal](https://temporal.io/)** — Workflow engine genérico, multi-language. Integração com OpenAI Agents SDK GA Mar 2026.
- **[Restate](https://restate.dev/)** — Durable handlers, journal-backed step replay, Pydantic AI integration.
- **[DBOS](https://dbos.dev/)** — Postgres/SQLite-backed durable workflows.
- **[Inngest](https://www.inngest.com/)** — Event-driven durable execution.
- **[Inngest AgentKit](https://github.com/inngest/agent-kit)** — TypeScript multi-agent networks.
- **[Trigger.dev](https://trigger.dev/)** — TS-first durable workflows.
- **[Conductor OSS](https://github.com/conductor-oss/conductor)** — Netflix event-driven, Apache 2.0.
- **[Cloudflare Workflows](https://developers.cloudflare.com/workflows/)** — Platform-specific.

---

## Sandbox-as-a-service

- **[E2B](https://e2b.dev/)** — Firecracker microVMs, ~150ms cold start, open core MIT.
- **[Daytona](https://www.daytona.io/)** — Docker-based, sub-90ms cold start.
- **[Modal](https://modal.com/)** — Serverless GPU + sandbox.
- **[Vercel Sandbox](https://vercel.com/docs/vercel-sandbox)** — Firecracker microVMs.
- **[Riza](https://riza.io/)** — Code interpreter alternative.
- **[Pyodide](https://pyodide.org/)** — Python in WASM.

---

## Memória (camada paralela)

- **[Letta (ex-MemGPT)](https://github.com/letta-ai/letta)** — Memory-first agent runtime, three-tier core/recall/archival.
- **[Mem0](https://github.com/mem0ai/mem0)** — Universal memory layer, 21+ framework integrations, Apache 2.0.
- **[Zep / Graphiti](https://github.com/getzep/graphiti)** — Temporal knowledge graph.
- **[Cognee](https://github.com/topoteretes/cognee)** — GraphRAG, deep knowledge retrieval.

---

## Observabilidade (consumers do event log)

- **[Langfuse](https://github.com/langfuse/langfuse)** — OSS leader, ClickHouse Series D $400M Jan 2026.
- **[Arize Phoenix](https://github.com/Arize-ai/phoenix)** — Elastic 2.0, OpenInference-native.
- **[Helicone](https://github.com/Helicone/helicone)** — Proxy-based, simplest install.
- **[Braintrust](https://www.braintrust.dev/)** — Eval-first.
- **[W&B Weave](https://wandb.ai/site/weave)** — ML obs platform.
- **[Literal AI](https://github.com/Chainlit/literalai-python)** — LLM obs.
- **[Lunary](https://github.com/lunary-ai/lunary)** — Open core.
- **[Laminar](https://github.com/lmnr-ai/lmnr)** — Agent rollout debugger.
- **[LangSmith](https://smith.langchain.com/)** — Closed, LangChain-native.

---

## Model routing

- **[LiteLLM](https://github.com/BerriAI/litellm)** — OpenAI-compatible across 100+ providers. **Componente reusable central.**
- **[OpenRouter](https://openrouter.ai/)** — SaaS marketplace.
- **[Portkey](https://portkey.ai/)** — Observability gateway.
- **[Vercel AI Gateway](https://vercel.com/docs/ai-gateway)** — Provider abstraction.
- **[agentgateway (Linux Foundation)](https://github.com/agentgateway/agentgateway)** — AI-native gateway, Rust, MCP + A2A + LLM gateway. **Componente reusable.**

---

## Specs / protocolos abertos

- **[Model Context Protocol (MCP)](https://modelcontextprotocol.io/)** — Anthropic + comunidade. Standard para tools.
- **[Agent-to-Agent Protocol (A2A)](https://google.github.io/a2a/)** — Google. Standard para multi-agent.
- **[Open Agent Specification](https://github.com/oracle/agent-spec)** — Oracle + Microsoft + Google. Declarative agent definition format.
- **[OpenTelemetry](https://opentelemetry.io/)** — CNCF. Tracing standard.
- **[OpenInference](https://github.com/Arize-ai/openinference)** — OpenTelemetry semantic conventions for LLM/agent.

---

## Papers (relevantes para arquitetura)

- **[OpenHands V1 SDK paper](https://arxiv.org/html/2511.03690v1)** — Architecture blueprint quase idêntico à tese Wake.
- **[Voyager: An Open-Ended Embodied Agent with LLMs](https://arxiv.org/abs/2305.16291)** — Skill library evolution.
- **[ReAct: Synergizing Reasoning and Acting in LLMs](https://arxiv.org/abs/2210.03629)** — Tool use loop padrão.
- **[Reflexion: Language Agents with Verbal Reinforcement Learning](https://arxiv.org/abs/2303.11366)** — Self-correction loops.
- **[SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering](https://arxiv.org/abs/2405.15793)** — Coding agent design.

---

## Outras leituras úteis

### Sobre design de event-sourced systems

- **["Designing Data-Intensive Applications" (Kleppmann)](https://dataintensive.net/)** — Capítulos 7, 11.
- **["Event Sourcing" (Fowler)](https://martinfowler.com/eaaDev/EventSourcing.html)** — Fundamentos.

### Sobre sandbox security

- **[Linux container security (cgroups, namespaces)](https://man7.org/linux/man-pages/man7/namespaces.7.html)**
- **[seccomp BPF](https://www.kernel.org/doc/html/latest/userspace-api/seccomp_filter.html)**
- **[bubblewrap](https://github.com/containers/bubblewrap)**

### Sobre WSGI/ASGI (analogia da HarnessAdapter)

- **[PEP 3333: WSGI](https://peps.python.org/pep-3333/)**
- **[ASGI specification](https://asgi.readthedocs.io/)**

### Sobre Temporal / durable execution

- **[Temporal Architecture](https://docs.temporal.io/temporal#temporal-platform)**
- **[Restate Concepts](https://docs.restate.dev/concepts/durable-execution)**

---

## Comunidade e discussões

- **[LangChain blog: Deep Agents Deploy](https://www.langchain.com/blog/deep-agents-deploy-an-open-alternative-to-claude-managed-agents)** — Posicionamento explícito como alternativa OSS.
- **[Anthropic Cookbook](https://github.com/anthropics/anthropic-cookbook)** — Patterns oficiais.
- **[MCP Server Registry](https://github.com/modelcontextprotocol/servers)** — Lista de MCP servers.

---

## Eventos de mercado relevantes (2024-2026)

- Anthropic lança Claude Code (2024)
- MCP é open-sourced (Nov 2024)
- OpenHands ganha Series A $18.8M (2025)
- Anthropic publica engineering post sobre Managed Agents (2026)
- Anthropic open-sources sandbox-runtime (2026)
- Multica explode com 10k+ stars Q1-Q2 2026
- Microsoft Agent Framework v1.0 GA (Apr 2026)
- LangChain Deep Agents Deploy lançado (Q1 2026)
- Langfuse acquired by ClickHouse $400M Series D (Jan 2026)
- Open Agent Specification publicado por Oracle + MS + Google (2026)

---

## Esta lista é viva

Atualizada conforme novos projetos / papers / posts aparecerem. PRs adicionando recursos relevantes são bem-vindos.

**Critério para inclusão:** o recurso deve ter impactado ou influenciado decisão de design em Wake, ou ser potencial componente reusável, ou ser competidor/adjacente a tracking.
