# Wake

> Durable runtime substrate for AI agents. Bring your framework. Bring your model. Bring your tools. Wake handles the event log, sandbox, vault and lifecycle.

**Status:** pre-alpha — design phase. Nothing built yet. The docs below capture the thesis, the architecture, the spec proposal, and the roadmap.

---

## What is Wake?

Three problems hit every team running AI agents in production:

1. **Durability** — agent dies mid-task, loses everything
2. **Sandbox** — agent runs arbitrary code, vulnerable to prompt injection
3. **Framework lock-in** — LangGraph in one team, CrewAI in another, nothing shared

Anthropic solved this internally with **Managed Agents** (proprietary, hosted, Claude-only). Wake is the open-source version — but goes further: **any harness** (LangGraph, CrewAI, Pydantic AI, Claude Agent SDK, custom) runs on the same substrate, with the same event log, the same sandbox, the same vault.

The piece nobody has built yet: **`HarnessAdapter` ABI** — the interface that makes this possible.

## Why now?

The agent infrastructure layer is going to commoditize in the next 12 months. OpenHands V1 SDK, Microsoft Agent Framework, Multica, OpenClaw — they're all converging. The fight is over who establishes the standard.

Wake is the bet that **a framework-agnostic substrate with a published HarnessAdapter spec** is the right shape — and that publishing it openly, with reference adapters for LangGraph / CrewAI / Pydantic AI / Claude Agent SDK on day one, is the right play.

## How is Wake different?

| | Wake | OpenHands V1 | OpenClaw | Multica | MAF | Managed Agents |
|---|---|---|---|---|---|---|
| Event log append-only | ✓ | ✓ | ✓ | partial | ✗ | ✓ |
| Harness stateless | ✓ | ✓ | partial | n/a | ✗ | ✓ |
| Sandbox-as-tool | ✓ | partial | ✗ | n/a | ✗ | ✓ |
| **HarnessAdapter ABI public** | **✓** | **✗** | **✗** | **✗** | **✗** | **✗** |
| Vault + proxy | ✓ | ✓ | ✓ | n/a | partial | ✓ |
| Multi-framework | ✓ | ✗ | ✗ | CLIs only | ✗ | ✗ |
| Self-host | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ |

The row that matters: **HarnessAdapter ABI public.**

## Documentation

Everything lives in [`docs/`](./docs/):

1. [README](./docs/README.md) — Documentation index
2. [VISION](./docs/VISION.md) — Why Wake exists, the thesis, the bet
3. [PRINCIPLES](./docs/PRINCIPLES.md) — Design principles
4. [ARCHITECTURE](./docs/ARCHITECTURE.md) — How Wake works technically
5. [SPEC-HARNESS-ADAPTER](./docs/SPEC-HARNESS-ADAPTER.md) — The ABI, v0.1.0
6. [SPEC-EVENT-SCHEMA](./docs/SPEC-EVENT-SCHEMA.md) — Canonical event log, v0.1.0
7. [LANDSCAPE](./docs/LANDSCAPE.md) — OSS ecosystem map
8. [COMPARISON](./docs/COMPARISON.md) — Wake vs every adjacent project
9. [EXAMPLES](./docs/EXAMPLES.md) — 14 concrete usage scenarios
10. [ROADMAP](./docs/ROADMAP.md) — Day-1, Day-30, Day-90, Day-365
11. [RESEARCH](./docs/RESEARCH.md) — All references
12. [FAQ](./docs/FAQ.md) — Honest answers to common questions

## What Wake is NOT

- Not a framework. LangGraph, CrewAI, Pydantic AI keep existing. Wake runs them.
- Not a sandbox. Reuses [sandbox-runtime](https://github.com/anthropic-experimental/sandbox-runtime), Docker, gVisor, Firecracker.
- Not a vault. Reuses [Infisical Agent Vault](https://github.com/Infisical/agent-vault).
- Not a memory layer. Letta, Mem0 keep existing.
- Not an observability platform. Langfuse, Phoenix consume Wake's event log via OpenTelemetry.
- Not a durable execution engine. Temporal, Restate, DBOS keep existing (Wake may use one internally).
- Not a SaaS product. OSS, self-host first.

**It is:** the seam between all those pieces, governed by an open spec (HarnessAdapter + event schema).

## Reused components (not reinvented)

| Layer | Component |
|---|---|
| OS-level sandbox | [anthropic-experimental/sandbox-runtime](https://github.com/anthropic-experimental/sandbox-runtime) |
| Vault + egress proxy | [Infisical/agent-vault](https://github.com/Infisical/agent-vault) |
| Model router | [LiteLLM](https://github.com/BerriAI/litellm) |
| MCP+A2A gateway | [agentgateway](https://github.com/agentgateway/agentgateway) (Linux Foundation) |
| Tool protocol | [Model Context Protocol](https://modelcontextprotocol.io/) |
| Agent definition | [Open Agent Specification](https://github.com/oracle/agent-spec) |

Wake builds: **the spec, the runtime, the adapters.** Everything else plugs in.

## Status and contributing

This repository is in **design phase**. The docs are the product right now. The bet is that publishing the `HarnessAdapter` ABI and event schema as a stable, community-reviewed open spec — before any code is written — is the right way to establish a standard.

If you want to help shape Wake before code lands:

- Read the specs ([SPEC-HARNESS-ADAPTER](./docs/SPEC-HARNESS-ADAPTER.md), [SPEC-EVENT-SCHEMA](./docs/SPEC-EVENT-SCHEMA.md))
- Open issues with critiques, gaps, or use cases the design fails to cover
- Argue with the [VISION](./docs/VISION.md) and [COMPARISON](./docs/COMPARISON.md)

A formal `CONTRIBUTING.md` and RFC process will land before any code does.

## License

To be decided around Day-30 based on input from potential enterprise users. Most likely **MIT** or **Apache 2.0**.

---

## The one-paragraph pitch

The agent infra layer is becoming commodity. Sandboxes (E2B, sandbox-runtime), vaults (Infisical), model routers (LiteLLM), durable execution (Temporal, Restate), memory (Letta, Mem0), and observability (Langfuse, Phoenix) are all mature OSS. What is missing is **the seam** — a runtime substrate that stitches these together with an open contract that any agent framework can implement. Wake is that seam: an append-only event log as the source of truth, a stateless harness defined by the `HarnessAdapter` ABI, a sandbox invoked as a tool, and credentials handled by a vault the harness never touches. Bring LangGraph, CrewAI, Pydantic AI, the Claude Agent SDK, or your own loop — they all run on the same substrate. Self-host. Replay deterministically. Audit every action. No billing, no lock-in.
