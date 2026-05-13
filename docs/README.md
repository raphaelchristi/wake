# Wake — Documentação

> **Wake** é o substrato durável para rodar agentes de IA. Você escolhe o framework. Você escolhe o modelo. Wake cuida do event log, do sandbox, do vault e do lifecycle.

Status: **pre-alpha, fase de design.** Estes documentos capturam a tese, a arquitetura, a spec proposta e o roteiro. Nada foi implementado ainda.

---

## Índice

### Comece aqui

1. [VISION.md](./VISION.md) — Por que Wake existe, a tese, o problema, a aposta
2. [PRINCIPLES.md](./PRINCIPLES.md) — Princípios de design e decisões irreversíveis
3. [ARCHITECTURE.md](./ARCHITECTURE.md) — Como Wake funciona tecnicamente

### Specs (versionáveis, propostas)

4. [SPEC-HARNESS-ADAPTER.md](./SPEC-HARNESS-ADAPTER.md) — Interface `HarnessAdapter` v0.1.0
5. [SPEC-EVENT-SCHEMA.md](./SPEC-EVENT-SCHEMA.md) — Event schema canônico v0.1.0

### Contexto competitivo

6. [LANDSCAPE.md](./LANDSCAPE.md) — Panorama do ecossistema OSS por camada
7. [COMPARISON.md](./COMPARISON.md) — Wake vs OpenHands / OpenClaw / Multica / MAF / Managed Agents
8. [RESEARCH.md](./RESEARCH.md) — Todas as referências, links, papers, repos relevantes

### Usando Wake

9. [EXAMPLES.md](./EXAMPLES.md) — 14 cenários concretos de uso com código
10. [ROADMAP.md](./ROADMAP.md) — Day-1, Day-30, Day-90, Day-365
11. [FAQ.md](./FAQ.md) — Perguntas comuns e respostas honestas

---

## Pitch de 30 segundos

Agentes de IA em produção sofrem três problemas:

1. **Durabilidade** — agente morre no meio da tarefa, perde tudo
2. **Sandbox** — agente roda código arbitrário, vulnerável a prompt injection
3. **Framework lock-in** — LangGraph num time, CrewAI noutro, nada compartilhado

A Anthropic resolveu isso internamente com **Managed Agents** (proprietário, hosted, Claude-only). Wake é a versão open-source — mas vai além: **qualquer harness** (LangGraph, CrewAI, Pydantic AI, Claude Agent SDK, custom) roda no mesmo substrato, com o mesmo event log, mesmo sandbox, mesmo vault.

A peça que ninguém construiu ainda: **HarnessAdapter ABI** — a interface que torna isso possível.

---

## Princípios em uma frase cada

- **Event log é a fonte de verdade.** Tudo é replayable.
- **Harness é stateless.** Pode morrer a qualquer momento.
- **Container é cattle.** Provisionado preguiçoso, descartável.
- **Sandbox é uma tool.** Não um modo de execução.
- **Credenciais nunca tocam o harness.** Vault + proxy.
- **Frameworks plugam, não engessam.** HarnessAdapter ABI.
- **Reuse, não reinvente.** sandbox-runtime, Infisical Vault, LiteLLM, MCP.

---

## Stack reusada (não-reinventada)

| Camada | Componente |
|---|---|
| Sandbox OS-level | [anthropic-experimental/sandbox-runtime](https://github.com/anthropic-experimental/sandbox-runtime) |
| Vault + egress proxy | [Infisical/agent-vault](https://github.com/Infisical/agent-vault) |
| Model router | [LiteLLM](https://github.com/BerriAI/litellm) |
| MCP+A2A gateway | [agentgateway](https://github.com/agentgateway/agentgateway) |
| Tool protocol | [Model Context Protocol](https://modelcontextprotocol.io/) |
| Agent definition spec | [Open Agent Specification](https://github.com/oracle/agent-spec) |

Wake constrói: **a spec, o runtime, e os adapters.** O resto pluga.

---

## Como contribuir

(A definir) Por enquanto, esse repositório é a sala de design. PRs/issues bem-vindos para revisar as specs antes de qualquer código ser escrito.

## Licença

(A definir — provável MIT ou Apache 2.0)
