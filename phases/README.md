# Phases

Plano de execução do Wake. Cada fase tem **gates de saída objetivos** — você só passa pra próxima depois de cumprir todos os critérios listados.

`docs/` é o **que** Wake é. `phases/` é o **como** Wake vai ser construído.

---

## Visão geral

| Fase | Nome | Duração | Status |
|---|---|---|---|
| [Phase 0](./PHASE-0-design-lock.md) | Design Lock | 1-2 semanas | ✅ done |
| [Phase 1](./PHASE-1-skeleton.md) | Skeleton | 2 semanas | ✅ done |
| [Phase 2](./PHASE-2-first-adapter.md) | First Adapter | 2 semanas | ✅ done |
| [Phase 3](./PHASE-3-spec-validation.md) | Spec Validation | 3 semanas | ✅ done |
| [Phase 4](./PHASE-4-production-stack.md) | Production Stack | 3 semanas | ✅ done |
| [Phase 5](./PHASE-5-operator-ui.md) | Operator UI (Wake Dashboard) | 3-5 semanas | ✅ done |
| [Phase 5.1](./PHASE-5.1-CONTRACT.md) | Adversarial Review Fixes | 2-3h | ✅ done |
| Phase 5.2 | Adversarial Review Fixes (2nd pass) | <1h | ✅ done |
| [Phase 6](./PHASE-6-public-launch.md) | Public Launch | 1 semana | ⚪ not_started |

**Total estimado:** 12-13 semanas (≈3 meses) para Wake v0.1.0 público com 4 adapters funcionando.

### Phase 0 — done (empirical validation in lieu of 7-day review window)

Phase 0 originalmente exigia janela pública de 7 dias antes de lock das specs. Foi substituído por **validação empírica via implementação** — Phase 2 e 3 provaram a HarnessAdapter ABI v0.1.0 com 4 reference adapters atingindo 10/10 conformance. Specs locked sem amendments.

Deliverables fechados:
- `LICENSE` Apache 2.0 (`24d0c93`)
- `CONTRIBUTING.md` com processo RFC (`24d0c93`)
- `CODE_OF_CONDUCT.md` (Contributor Covenant v2.1, `fbee2da`)
- `.github/ISSUE_TEMPLATE/{rfc,bug,feature}.md` + `config.yml` (`fbee2da`)
- `.github/PULL_REQUEST_TEMPLATE.md` (`fbee2da`)
- `phases/decisions/runtime-language.md` (Python decision documented)
- `phases/decisions/license.md` (Apache 2.0 decision documented)
- `phases/decisions/spec-lock-v0.1.0.md` (lock without 7-day window, justified)
- RFC issues abertas: [#1](https://github.com/raphaelchristi/wake/issues/1) HarnessAdapter, [#2](https://github.com/raphaelchristi/wake/issues/2) Event Schema, [#3](https://github.com/raphaelchristi/wake/issues/3) Runtime language
- Git tag: `spec-v0.1.0-frozen` (HarnessAdapter ABI + Event Schema v0.1.0 locked)

### Phase 1 — done in 28 min wall-clock (multi-agent)

3 Opus agents em worktrees isolados (`agent/foundation`, `agent/runtime`, `agent/cli`) construíram em paralelo:

- **5.308 LoC source + 2.459 LoC tests**
- **154 unit tests passing** (foundation 57 + runtime 72 + cli 25)
- Coverage: foundation 97%, runtime 86%
- Branches merged into main (`f47f670`, `6cc1658`, `db427cc`)
- Post-merge integration fixes (`d35d8c2`) — 8 interface mismatches consertados

Lições para próximas fases:
- Contrato de interface (`PHASE-1-CONTRACT.md`) foi essencial para minimizar conflitos
- Scaffolding pré-merge (types.py, pyproject.toml) evitou trio de conflitos triviais
- Agents respeitaram boundaries — todos commitaram só seus paths
- Interface mismatches inevitáveis: aliases + helpers resolvem rápido

### Phase 2 — done in 35 min wall-clock (multi-agent)

3 Opus agents em worktrees isolados (`agent/core-claude-sdk`, `agent/conformance`, `agent/stubs-docs`):

- **HarnessAdapter ABI v0.1.0** publicada em `src/wake/adapters/` (Protocol + context + EventStream + ToolRegistry + AdapterRegistry com entry_points discovery)
- **`wake-adapter-claude-sdk`** — primeiro adapter conformante, refactor do harness Phase 1 (~350 LoC)
- **`wake-test-conformance`** — 10 scenarios canônicos, 88% coverage, echo adapter passa 10/10
- **2 stub adapters** (langgraph + crewai) discoverable via entry_points
- **`docs/WRITING-AN-ADAPTER.md`** — tutorial 2125 palavras
- **`examples/03-adapter-discovery/`** — demo rodável em 2.5s
- **`src/wake/runtime/`** — SessionDispatcher + WakeEventStream + WakeToolRegistry (concrete impls das ABCs)

Stats:
- **229 tests passing** (176 main + 14 claude-sdk + 29 conformance + 5 langgraph + 5 crewai)
- Coverage `src/wake/runtime/*`: 100% — `adapters/claude-sdk/*`: 91% — conformance: 88%
- Backward compat: `wake.harness.AnthropicHarness` ainda funciona (DeprecationWarning)
- Zero regressão nos 154 tests Phase 1 baseline
- Branches merged into main (`bdf2bda` conformance, `1a40103` claude-sdk, `74da1d9` stubs-docs)
- Post-merge polish: `e9b85c7` (ruff TC003 + A002 noqa)

Trap descoberto:
- PEP 440 não aceita `"0.1.0-stub"` como versão PyPI. Stubs packaging usa `"0.1.0a0"`; runtime `version` attr mantém `"0.1.0-stub"` per contract.

Validação keystone:
- `ClaudeSDKAdapter` é descoberta via entry_point (`adapter_registry.get("claude-sdk")` retorna instância)
- Implementa Protocol HarnessAdapter (verificado por `isinstance` + mypy)
- Roda contra conformance suite (7/10 com mock simples — gaps são scenarios que precisam mock LLM completo; cobertos via test_adapter.py com mocks específicos)

### Phase 3 — done in ~70 min wall-clock (multi-agent)

3 Opus agents em worktrees isolados implementaram adapters REAIS para 3 frameworks com paradigmas distintos:

- **`wake-adapter-langgraph`** (`31bb22b`) — graph-based: StateGraph, ToolNode, create_react_agent, astream. 42 tests. **Conformance 10/10.**
- **`wake-adapter-crewai`** (`9e92e6c`) — role-based: Crew, Agent, Task, callbacks. 37 tests. **Conformance 10/10.**
- **`wake-adapter-pydantic-ai`** (`3264be7`) — type-safe: typed Agent, FunctionToolset, streaming. 31 tests. **Conformance 10/10.**

Stats agregadas Phase 3:
- ~4.000 LoC adapter+tests através de 3 packages novos
- **329 tests total** no projeto (subiu de 229 Phase 2 → 329 Phase 3)
- Branches merged em main (`6248102` triple-merge)
- Worktrees + branches cleaned up

Validação da tese:
- A HarnessAdapter ABI v0.1.0 funciona em paradigmas radicalmente diferentes (graph / role / type) — sem mudança no Protocol
- Conformance suite catch comportamento problemático em todos os 3 (e os 3 passam após implementação correta)
- Pattern do claude-sdk adapter (referência) escala para outros frameworks sem retrabalho da spec

Frameworks instalados em `.venv` (gitignored, devs instalam local):
- `langgraph>=1.0,<2.0`
- `crewai>=1.0` (instalou 1.14.4)
- `pydantic-ai>=1.0`

### Phase 5 — done via multi-agent + continuation passes

3 Opus agents em worktrees isolados (`agent/dashboard-shell`, `agent/dashboard-replay`, `agent/dashboard-metrics-vault`) construíram o **Wake Dashboard** (Next.js 15 SPA) em paralelo. Primeira passagem entregou ~70% commitado; uma rodada de continuação fechou os gaps (frontend não commitado pelos agents originais que excederam o budget de tempo).

- **`agent/dashboard-shell`** (`26e8d30`) — scaffolding Next.js 15 + App Router + RSC + Tailwind v4 + shadcn/ui + TanStack Query + TanStack Table + auth `X-Wake-API-Key` + sessions list+filters + layout shell + dark mode + GitHub Actions CI. Backend additive: CORS middleware, filter query params em `GET /sessions`.
- **`agent/dashboard-replay`** (`a8c991a`) — replay scrubber + event list virtualizada + event detail (react-json-view-lite) + sandbox state panel + playback controls + keyboard shortcuts + 53-event fixture + storybook. Backend additive: `GET /sessions/{id}/state-at/{seq}` com event-by-event reconstruction.
- **`agent/dashboard-metrics-vault`** (`9bdaf9d`) — métricas (Recharts: latency p50/95/99, cost, throughput, error rate, workers, time range picker) + vault management UI (credentials list sem tokens, Add/Rotate dialogs, OAuth callback, audit log) + deploy (Dockerfile.frontend multi-stage, Helm `deployment-frontend.yaml` + `service-frontend.yaml` + ingress, Compose service) + `docs/DASHBOARD.md` (823 linhas). Backend additive: `GET /metrics/summary`, `GET /workers`, vault routes (list/oauth/start/oauth/callback/rotate/revoke/audit).

Stats agregadas Phase 5:
- ~14.000 LoC source+tests (frontend 11 rotas + 4 surfaces + tests + stories + deploy)
- **+143 tests novos** (79 vitest frontend + 64 pytest backend — api filters 11, state reconstruction 19, metrics aggregation 19, vault routes 15)
- Bundle gzip: max `/metrics` 229KB First Load (dentro do budget 300KB)
- Build clean: `next build` 11 rotas prerendered + 1 dynamic
- Regressions claude-sdk/conformance/langgraph/postgres/sandbox/vault/litellm todas verdes
- Post-merge fixes (`4556b6c`): typecheck (noUncheckedIndexedAccess), lint (type-only imports), happy-dom localStorage polyfill
- Worktrees + branches cleaned up

Decisões locked durante a phase:
- Stack: Next.js 15 App Router + RSC + Tailwind v4 + shadcn/ui + pnpm
- Auth: `X-Wake-API-Key` bearer header (OAuth Infisical fica pra v1.1)
- Real-time: SSE (já existente) + polling fallback
- Hosting: Next.js standalone build → Docker → Helm + Compose (self-host first)

---

### Phase 4 — done in ~37 min wall-clock (multi-agent)

3 Opus agents em worktrees isolados (`agent/postgres-store`, `agent/sandbox-runtime`, `agent/vault-llm-deploy`) construíram a production stack inteira em paralelo:

- **`wake-store-postgres`** (`94feb07`) — Postgres 16 backend: events particionados por HASH(session_id) com 16 partições, índice BRIN em created_at, LISTEN/NOTIFY pra SSE fan-out, advisory locks pra session ownership, `WorkerHeartbeat` pra multi-worker scheduling, migrações Alembic, load test opt-in.
- **`wake-sandbox-runtime`** (`03f1fbd`) — wrapper Python sobre `@anthropic-ai/sandbox-runtime` (npm) com `select_sandbox_backend()` graceful fallback pra Docker. Mandatory deny paths (`~/.ssh`, `~/.aws`, `/etc/shadow`) override-proof. Linux (bubblewrap) + macOS (sandbox-exec).
- **`wake-vault-infisical`** (`3647537`) — Infisical Agent Vault: OAuth flows pra GitHub/Slack/Notion, HTTPS proxy substitution, prompt-injection protection (testes confirmam token nunca em logs/events).
- **`wake-llm-litellm`** (`3647537`) — LiteLLM provider multi-model: Anthropic/OpenAI/Ollama normalizados pro canonical Wake event format, cost tracking via callbacks.
- **`deploy/`** — Docker Compose (api+worker+postgres+redis+agentgateway+vault sidecars), Helm chart v0.4.0 (10 templates), agentgateway config pra MCP egress.
- **`docs/DEPLOY*.md`** — 5 deploy guides (overview + Compose + Kubernetes + Fly.io + AWS).
- **`examples/05/07/08`** — kill-and-resume, mcp-github, vault-credentials runnables.

Stats agregadas Phase 4:
- ~7.000 LoC source+tests através de 4 packages novos + deploy + examples
- **+146 tests novos** (postgres 18 / sandbox 46 / vault 43 / litellm 39); regressions claude-sdk/langgraph/conformance verdes
- `src/wake/runtime/registry.py` introduzido (postgres-store slice) — `EntryPointRegistry[T]` genérico pra wake.stores/sandboxes/vaults/llm_providers
- `src/wake/py.typed` marker pra typed downstream adapters
- 3 merge commits sequenciais (`94feb07` postgres → `03f1fbd` sandbox → `3647537` vault-llm-deploy)
- Worktrees + branches cleaned up

Validação:
- Postgres backend reproduz comportamento de SQLiteStore (mesmas behavioral suites)
- sandbox-runtime fallback pra Docker verificado via `select_sandbox_backend()` test matrix
- Prompt-injection exfil test (vault) — token nunca aparece em payloads observáveis
- Helm chart `helm lint` clean; Docker Compose `config` válido
- Example 05 demonstra resume <60s após worker kill (in-memory FakeStore; Postgres path via `WAKE_DATABASE_URL`)

Issues identificadas (não bloqueantes, fora do escopo Phase 4):
- `pydantic-ai` upstream bumped pra `1.31.0` durante reinstall — `ToolReturnPart.outcome` arg removed → regressão de 10 testes no `wake-adapter-pydantic-ai` (precisa pinning + fix). Antes do Phase 4: 31/31 passing.
- `wake-adapter-crewai` ~9 testes failing após reinstall (provavelmente upstream drift similar; precisa investigação).
- `tests/unit/test_cli_client.py` — 5 failures pre-existentes (`httpx[socks]` missing) já documentadas pré-Phase 4.
- Discovery loaders `wake.sandboxes`/`wake.vaults`/`wake.llm_providers` declared como entry_points mas consumo no CLI ainda não wired (sandbox-runtime adapter funciona via constructor; integração via registry fica pra polish).

---

## Filosofia das fases

### 1. Gates são objetivos, não opinião

Cada fase termina quando todos os critérios de saída listados estão verificavelmente cumpridos. Não "estou achando que tá pronto." Tem que ter:

- Testes passando
- Artefato existindo no repo
- Comando que funciona reproduzivelmente
- Métrica que bateu

### 2. Sem pular fases

A tentação é começar a escrever código antes da Phase 0 fechar. Resistência: a tese inteira de Wake depende de specs validadas pela comunidade. Código sem spec validada é código que vai ser reescrito.

### 3. Cada fase produz algo demoável

Phase 1 demoa: `wake run hello`. Phase 2 demoa: `HarnessAdapter` funcionando. Phase 3 demoa: LangGraph rodando no Wake. Phase 4 demoa: kill -9 e resume. Phase 5 demoa: post no HN.

Se uma fase não tem demo, ela tá errada.

### 4. Riscos são listados antes, não depois

Cada fase tem seção de riscos com mitigações. Quando o risco se materializar, já tem plano.

### 5. Duração é teto, não meta

Estimativas são pessimistas (Hofstadter dobra). Se passar do teto, é sinal pra reavaliar arquitetura, não trabalhar mais horas.

### 6. Audite reuso antes de implementar

Toda fase tem seção `## Reusable Components`. Antes de qualquer task começar, ler essa seção e perguntar:

- **Existe lib madura que faz isso?** → importa.
- **Existe pattern em projeto referência?** → estuda, adapta.
- **Existe spec aberta?** → adota em vez de inventar.

Reescrever do zero o que já existe maduro é a forma #1 de queimar tempo em projeto OSS. As fases foram desenhadas assumindo reuso agressivo. Estimativas de duração só fecham se a regra for seguida.

Lista de reuso por fase em cada `PHASE-N-*.md`, seção `## Reusable Components`. Resumo cross-phase de componentes-chave:

| Componente | Phase | Reuso |
|---|---|---|
| Anthropic Cookbook tool-use | Phase 1 | pattern oficial |
| OpenHands V1 EventLog | Phase 1 | estudar antes de codar |
| `python-statemachine` | Phase 1 | session FSM |
| `pluggy` | Phase 2 | plugin discovery |
| ASGI/MCP conformance patterns | Phase 2 | template de spec testing |
| LangGraph/CrewAI/Pydantic AI docs oficiais | Phase 3 | estudo antes de adapter |
| Open Agent Specification | Phase 3 | adoção parcial considerada |
| `sandbox-runtime` (Anthropic) | Phase 4 | sandbox completo, evita 4 semanas |
| `Infisical Agent Vault` | Phase 4 | vault + proxy completo, evita 3 semanas |
| `LiteLLM` | Phase 4 | model router, evita 2 semanas |
| `agentgateway` (Linux Foundation) | Phase 4 | MCP/A2A gateway, evita 1 semana |
| `mkdocs-material` + FastAPI docs structure | Phase 5 | site pronto em 1 dia |
| `asciinema` | Phase 5 | demos terminal |
| Cloudflare Pages | Phase 5 | hosting grátis

---

## Dependências entre fases

```
Phase 0 (design lock)
   │
   ▼
Phase 1 (skeleton)
   │
   ▼
Phase 2 (first adapter) ──────────┐
   │                              │
   ▼                              │
Phase 3 (spec validation) ────────┤
   │                              │
   ▼                              ▼
Phase 4 (production stack) ─→ Phase 5 (public launch)
```

Phase 4 e Phase 5 podem rodar em paralelo parcialmente (docs/blog/launch prep durante Phase 4).

---

## Como usar este diretório

### Para o autor / equipe core

1. Abrir cada `PHASE-N-*.md` no início da fase
2. Marcar tasks completas conforme avança
3. Verificar gates de saída antes de marcar fase como `done`
4. Atualizar status nesta README ao mudar de fase

### Para contribuidores externos

1. Olha esta README pra ver onde estamos
2. Lê o `PHASE-N-*.md` da fase atual pra ver o que falta
3. Procura tasks marcadas como `help wanted` na fase atual
4. Não tenta contribuir em fase futura — issues serão aceitos mas trabalho não começa antes

### Para usuários potenciais

Lê o status na tabela acima. Se Wake está em Phase 0/1/2 — provavelmente não usável ainda. Phase 3+ — começa a dar pra experimentar. Phase 5 — produto público.

---

## Atualização desta README

Após cada mudança de status de fase, atualize a tabela acima E commite com mensagem `phase: <name> → <new status>`. Histórico do progresso fica visível via `git log phases/README.md`.

---

## Glossário rápido

- **Gate** — critério objetivo de saída de uma fase
- **DoD** (Definition of Done) — checklist final, todos os items precisam estar ✓
- **Help wanted** — task que pode ser feita por contribuidor externo sem dependência de decisão arquitetural
- **Spec lock** — momento em que uma spec é congelada e mudanças exigem RFC
