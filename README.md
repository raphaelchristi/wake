<p align="center">
  <img src="docs/assets/banner.png" alt="Wake — Durable runtime substrate for AI agents" width="900">
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="Apache 2.0"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/status-alpha-orange.svg" alt="alpha">
  <a href="https://github.com/raphaelchristi/wake/releases/tag/v0.4.0-production"><img src="https://img.shields.io/badge/version-v0.4.0--production-green.svg" alt="v0.4.0"></a>
</p>

<p align="center">
  Bring your framework, your model, your tools. Wake handles event log, sandbox, vault and lifecycle.
</p>

---

## Why Wake?

Three problems hit every team running AI agents in production:

1. **Durability** — agent dies mid-task, loses everything
2. **Sandbox** — agent runs arbitrary code, vulnerable to prompt injection
3. **Framework lock-in** — LangGraph in one team, CrewAI in another, nothing shared

Anthropic solved this internally with **Managed Agents** (proprietary, hosted, Claude-only). Wake is the open-source version — and goes further: *any* harness runs on the same substrate via the **`HarnessAdapter` ABI**.

## Quickstart

```bash
pip install wake-ai[all-adapters]
```

```python
from wake.runtime import Session
from wake_adapter_claude_sdk import ClaudeSDKAdapter

session = await Session.create(
    adapter=ClaudeSDKAdapter(model="claude-sonnet-4-6"),
    tools=["bash", "file_read", "file_write"],
)

async for event in session.run("Refactor src/auth.py to use async/await"):
    print(event.type, event.payload)
```

Swap `ClaudeSDKAdapter` for `LangGraphAdapter`, `CrewAIAdapter`, or `PydanticAIAdapter` — same substrate, same event log, same sandbox.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Harness  (Claude SDK · LangGraph · CrewAI · Pydantic AI)   │
└──────────────────────────┬──────────────────────────────────┘
                           │ HarnessAdapter ABI v0.1.0
┌──────────────────────────▼──────────────────────────────────┐
│  Wake Runtime  — sessions, dispatcher, event stream         │
├─────────────────┬────────────────┬──────────────────────────┤
│  Event Store    │   Sandbox      │      Vault               │
│  Postgres/SQLite│   sandbox-rt   │      Infisical           │
│  LISTEN/NOTIFY  │   Docker       │      OAuth flows         │
│  partitioned    │   fallback     │      egress proxy        │
└─────────────────┴────────────────┴──────────────────────────┘
```

The seam is the **HarnessAdapter ABI** (locked v0.1.0). Specs in [`docs/`](./docs/).

## Adapters

| Adapter | Package | Conformance | Status |
|---|---|---:|---|
| Claude Agent SDK | `wake-adapter-claude-sdk` | 10/10 | stable |
| LangGraph | `wake-adapter-langgraph` | 10/10 | stable |
| CrewAI | `wake-adapter-crewai` | 10/10 | stable |
| Pydantic AI | `wake-adapter-pydantic-ai` | 10/10 | stable |

Write your own — see [`docs/WRITING-AN-ADAPTER.md`](./docs/WRITING-AN-ADAPTER.md).

## Production stack

Phase 4 ships the infra layer:

- **Postgres backend** — events partitioned by `HASH(session_id)`, LISTEN/NOTIFY, advisory locks, multi-worker heartbeat
- **sandbox-runtime** — Anthropic's npm sandbox wrapped in Python, with graceful Docker fallback
- **Infisical Vault** — OAuth flows (GitHub/Slack/Notion), egress proxy, prompt-injection protection
- **LiteLLM** — Anthropic / OpenAI / Ollama multi-provider, normalized to canonical Wake events
- **agentgateway** — MCP HTTP egress sidecar
- **Deploy** — Helm chart + Docker Compose + 5 deploy guides

```bash
docker compose -f deploy/docker-compose.yml up    # self-host stack
helm install wake deploy/helm/wake                # kubernetes
```

## Reuses, doesn't reinvent

| Layer | Component |
|---|---|
| OS sandbox | [`anthropic-experimental/sandbox-runtime`](https://github.com/anthropic-experimental/sandbox-runtime) |
| Vault + proxy | [`Infisical/agent-vault`](https://github.com/Infisical/agent-vault) |
| Model router | [`LiteLLM`](https://github.com/BerriAI/litellm) |
| MCP gateway | [`agentgateway`](https://github.com/agentgateway/agentgateway) (Linux Foundation) |
| Tool protocol | [Model Context Protocol](https://modelcontextprotocol.io/) |

Wake builds the **spec, the runtime, the adapters.** Everything else plugs in.

## Status

| Phase | Status |
|---|---|
| 0 — Design Lock | ✅ done |
| 1 — Skeleton (runtime + CLI + SQLite) | ✅ done |
| 2 — First Adapter (HarnessAdapter ABI + Claude SDK + conformance suite) | ✅ done |
| 3 — Spec Validation (LangGraph + CrewAI + Pydantic AI adapters, 10/10) | ✅ done |
| 4 — Production Stack (Postgres + sandbox-runtime + Vault + LiteLLM + deploy) | ✅ done |
| 5 — Public Launch | ⚪ next |

See [`phases/`](./phases/) for detailed progress.

## Docs

Start with:

- [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) — how Wake works technically
- [`docs/SPEC-HARNESS-ADAPTER.md`](./docs/SPEC-HARNESS-ADAPTER.md) — the ABI, locked v0.1.0
- [`docs/SPEC-EVENT-SCHEMA.md`](./docs/SPEC-EVENT-SCHEMA.md) — canonical event log, locked v0.1.0
- [`docs/WRITING-AN-ADAPTER.md`](./docs/WRITING-AN-ADAPTER.md) — port your framework

Full index in [`docs/README.md`](./docs/README.md).

## Contributing

RFC-driven. Open an issue tagged `rfc` for spec changes, `bug` for defects, `feature` for proposals. Templates in [`.github/ISSUE_TEMPLATE/`](./.github/ISSUE_TEMPLATE/). See [`CONTRIBUTING.md`](./CONTRIBUTING.md).

## License

Apache 2.0 — see [`LICENSE`](./LICENSE).
