# Phase 5 — Operator UI (Wake Dashboard)

> **Objetivo:** SPA real para operadores de Wake — sessions list, replay determinístico visual, drill-down de eventos, métricas operacionais, vault management. Killer demo pro launch público.

| | |
|---|---|
| **Status** | ⚪ not_started |
| **Duração estimada** | 3-5 semanas (~4-6h multi-agent wall-clock) |
| **Dependências** | Phase 4 done (production stack), Phase 3 done (4 adapters) |
| **Pre-requisito não bloqueante** | Phase 5.0 tech debt (pydantic-ai pin, CrewAI drift, CLI discovery) |

---

## Por que essa fase existe

Phase 4 entregou o substrate. Operar Wake em produção hoje exige `psql`, `kubectl logs`, `pytest`. Aceitável pra dev — inaceitável pra empresa que adota.

O **Wake Dashboard** é onde a tese se prova visualmente:

- "Veja Claude SDK, LangGraph e CrewAI rodando lado a lado, todos no mesmo event log."
- "Mate um worker. Veja a session resumir em outro em 30 segundos."
- "Prompt injection tentando exfiltrar token? Veja o vault bloqueando no log."
- "Replay deterministico: arraste o scrubber pra qualquer evento e veja o estado da sandbox naquele instante."

Sem isso, o launch é uma lib bem documentada. Com isso, é um produto.

---

## Entry criteria

- ✅ Phase 4 done (`v0.4.0-production`)
- ✅ FastAPI backend em `src/wake/api/` expondo:
  - `GET /sessions` (list + filter)
  - `GET /sessions/{id}/events` (replay)
  - `GET /sessions/{id}/stream` (SSE live)
  - `GET /agents` + `GET /environments`
  - `GET /metrics` (Prometheus exposition)
- ⏳ **Decisão pendente:** stack frontend (Next.js vs SvelteKit) + posição na roadmap (Phase 5 ou 6)

---

## Exit criteria (gates)

Todos verificáveis:

### Shell + Auth
- [ ] App SPA rodando em `frontend/` com routing, layout e dark mode
- [ ] Autenticação: bearer token / API key local OU integração OAuth via vault Infisical (escolha documentada)
- [ ] CI: `pnpm build` + `pnpm test` + `pnpm lint` clean em GitHub Actions

### Sessions list
- [ ] Tabela paginada de sessions com colunas: id (ULID short), agent name, status, model, created_at, duration, event_count, cost_usd
- [ ] Filtros: agent (multi-select), status (idle/running/completed/failed), model, date range, text search
- [ ] Click numa row → drill-down (`/sessions/[id]`)
- [ ] Auto-refresh via SSE de novos eventos ou polling 5s

### Replay scrubber
- [ ] Página `/sessions/[id]/replay` com timeline visual horizontal
- [ ] Scrubber arrastável: cada tick = 1 evento; play/pause/step buttons
- [ ] Painel esquerdo: lista de eventos com tipos coloridos (user.message / assistant.message / tool_use / tool_result / sandbox.* / vault.*)
- [ ] Painel direito: payload do evento focado (JSON viewer com syntax highlight)
- [ ] Painel inferior: estado reconstruído do sandbox no instante do evento (last bash output, files modified)
- [ ] Keyboard shortcuts: ← → step, Space play/pause, Home/End jump

### Drill-down de eventos
- [ ] Tool calls expandidas mostram: input args, output, duration, exit_code, sandbox handle
- [ ] Vault accesses mostram: placeholder usado, host alvo, autorizado/bloqueado, sem expor token real
- [ ] Sandbox events: provision/destroy timings, container_id, workspace_path
- [ ] Cost tracking visível por LLM call (LiteLLM callback metadata)

### Métricas
- [ ] Página `/metrics` com gráficos: p50/p95/p99 latency por step, cost per session (avg + outliers), sessions/worker, queue depth, error rate
- [ ] Filtros temporais: last 1h / 24h / 7d / 30d
- [ ] Drill-down: click num bucket pra ver sessions naquele intervalo
- [ ] Dados pulled de `GET /metrics` (Prometheus) + queries Postgres se necessário

### Vault management
- [ ] Página `/vault` lista credentials (name, provider, created_at, last_used)
- [ ] Botão "Add credential" inicia OAuth flow (GitHub/Slack/Notion) com redirect callback
- [ ] Botão "Rotate" pra cada credential
- [ ] Audit log: lista accesses recentes (session_id, host, allowed/denied, timestamp)
- [ ] **Tokens NUNCA exibidos** (apenas hashes/placeholders)

### Deploy
- [ ] `Dockerfile.frontend` build + serve (multi-stage)
- [ ] Helm chart `deploy/helm/wake/templates/deployment-frontend.yaml` + service + ingress
- [ ] Docker Compose adiciona `frontend` service
- [ ] Docs `docs/DASHBOARD.md` cobrindo run local + auth setup + customização

### Quality
- [ ] Lighthouse score ≥ 90 (Performance/Accessibility/Best Practices)
- [ ] Component tests via Vitest/Playwright
- [ ] Storybook (ou catalog) com componentes-chave
- [ ] Sem `any` em TypeScript (strict mode)

---

## Deliverables

### Estrutura

```
frontend/
├── package.json                      # pnpm workspace
├── pnpm-lock.yaml
├── tsconfig.json
├── README.md
├── Dockerfile
├── src/
│   ├── lib/
│   │   ├── api/                      # client gerado/typed do FastAPI OpenAPI
│   │   ├── auth/
│   │   ├── sse/                      # SSE hook + reconnect
│   │   └── utils/
│   ├── components/
│   │   ├── ui/                       # primitives (Button, Card, Table, …)
│   │   ├── sessions/
│   │   │   ├── SessionsTable.tsx
│   │   │   ├── SessionFilters.tsx
│   │   │   └── SessionRow.tsx
│   │   ├── replay/
│   │   │   ├── ReplayScrubber.tsx
│   │   │   ├── EventList.tsx
│   │   │   ├── EventDetail.tsx
│   │   │   └── SandboxStatePanel.tsx
│   │   ├── metrics/
│   │   │   ├── LatencyChart.tsx
│   │   │   ├── CostChart.tsx
│   │   │   └── WorkerHealth.tsx
│   │   └── vault/
│   │       ├── CredentialsList.tsx
│   │       ├── AddCredentialDialog.tsx
│   │       └── AuditLog.tsx
│   ├── routes/ (or app/)             # depende do framework
│   │   ├── (auth)/login
│   │   ├── sessions/
│   │   ├── sessions/[id]/replay
│   │   ├── metrics/
│   │   └── vault/
│   └── styles/
├── tests/
│   ├── unit/
│   └── e2e/                          # Playwright
└── storybook/                        # ou Histoire (svelte)

deploy/
├── docker-compose.yml                # +service frontend
└── helm/wake/templates/
    ├── deployment-frontend.yaml      # NEW
    ├── service-frontend.yaml         # NEW
    └── ingress.yaml                  # UPDATE (route /, /sessions, …)

docs/
└── DASHBOARD.md                      # NEW

src/wake/api/
└── (additive: endpoints faltando se houver, sem breaking changes)
```

### API contract (backend additions, se necessário)

Endpoints **provavelmente já existentes** em `src/wake/api/` precisam validação. Faltantes prováveis:

- `GET /sessions?agent=&status=&model=&since=&until=&q=&page=&page_size=`
- `GET /sessions/{id}/state-at/{seq}` → snapshot reconstruído (sandbox state + last events)
- `GET /metrics/summary?window=24h` → JSON-friendly métricas
- `GET /vault/credentials` (sem expor tokens)
- `POST /vault/oauth/start` + `GET /vault/oauth/callback` (delegado pro Infisical adapter)
- `POST /vault/credentials/{id}/rotate`
- `GET /vault/audit?since=&limit=`

Cada adição respeita SPEC-EVENT-SCHEMA e gera OpenAPI spec (FastAPI nativo). Frontend consome via codegen (`openapi-typescript`).

---

## Tasks detalhadas

### Stack & scaffolding (3 dias)

#### T5.1 — Decisão de stack (0.5d)

Decidir entre Next.js 15 (App Router + RSC) e SvelteKit 2:

| Critério | Next.js 15 | SvelteKit 2 |
|---|---|---|
| Bundle size | médio | pequeno |
| SSR/RSC | RSC first-class | SSR maduro |
| Ecosystem | maior | menor mas crescente |
| Self-host | OK (Node adapter ou static export) | OK (Node adapter) |
| Component lib | shadcn/ui (deep) | skeleton.dev + bits-ui |
| Learning curve | hooks + RSC mental model | mais simples |
| Charts | Recharts / Tremor / Visx | Layer Cake / Apache ECharts |

Pesos: **self-host first** + **bundle size** favorecem Svelte. **Ecosystem** + **shadcn/ui maturidade** favorecem Next. Decisão do user.

Documentar decisão em `docs/decisions/frontend-stack.md`.

#### T5.2 — Scaffolding + CI (1d)

- `pnpm create` (next-app ou sveltekit)
- TypeScript strict, ESLint, Prettier
- TailwindCSS + shadcn/ui (next) ou skeleton.dev (svelte)
- GitHub Actions: install → lint → test → build
- Storybook ou Histoire

#### T5.3 — API client typed (0.5d)

- `openapi-typescript` lê FastAPI OpenAPI spec e gera tipos
- Wrapper fetch com auth header injection
- TanStack Query (next) ou TanStack Query Svelte (svelte) pra caching

#### T5.4 — Auth (1d)

Decidir entre:
- **API key local** (mais simples, suficiente pra self-host single-user)
- **OAuth via Infisical** (reusa vault, mais complexo, melhor pra multi-user)

Recomendação: começar com API key, evoluir pra OAuth em phase posterior.

### Sessions UI (3 dias)

#### T5.5 — Sessions list (1.5d)
- Tabela virtualizada (`@tanstack/react-table` ou `svelte-headless-table`)
- Filtros como query params (URL = state)
- Polling 5s + SSE de "new session" subscription

#### T5.6 — Session detail shell (1d)
- Layout `/sessions/[id]` com tabs: Replay, Events, Metadata
- Header: agent, model, status badge, cost total, duration

#### T5.7 — Empty/loading/error states (0.5d)
- Skeletons consistent
- Error boundary com retry

### Replay scrubber (5 dias)

#### T5.8 — Timeline component (2d)
- D3-timeline ou custom canvas
- Eventos como ticks coloridos
- Drag/keyboard navigation
- Performance pra >10k eventos (virtualização)

#### T5.9 — Event detail panel (1d)
- JSON viewer (react-json-view ou svelte-json-tree)
- Syntax highlight (Shiki)
- Copy/expand buttons

#### T5.10 — Sandbox state reconstruction (1.5d)
- API `GET /sessions/{id}/state-at/{seq}` retorna snapshot
- Painel mostra: cwd, last bash output, files modified
- Diff view entre states consecutivos

#### T5.11 — Playback controls + shortcuts (0.5d)
- Play/pause/step
- Keyboard nav
- Speed (0.5x / 1x / 2x / 5x)

### Métricas (2 dias)

#### T5.12 — Metrics page (1.5d)
- Recharts/Layer Cake/ECharts
- 4 cards principais: latency, cost, throughput, errors
- Drill-down por session

#### T5.13 — Worker health (0.5d)
- Live status de workers (heartbeat from postgres-store)
- Queue depth + processing rate

### Vault management (2 dias)

#### T5.14 — Credentials list + add (1d)
- Lista credentials
- Dialog "Add" inicia OAuth → redirect → callback
- Toast de sucesso/erro

#### T5.15 — Audit log + rotation (1d)
- Tabela paginada de accesses
- Filtros: provider, host, allowed/denied
- Rotation flow (revogar + criar nova credential)

### Deploy + Docs (1 dia)

#### T5.16 — Dockerfile + Helm + Compose (0.5d)
- Dockerfile multi-stage (build → static serve via nginx ou Node)
- Helm template
- Compose service

#### T5.17 — `docs/DASHBOARD.md` (0.5d)
- Setup local
- Auth setup
- Customização (theme, branding)
- Screenshots

---

## Reusable components (não reinventar)

| Item | Source | License | Por quê |
|---|---|---|---|
| Component lib (Next) | [shadcn/ui](https://ui.shadcn.com/) | MIT | copy-paste maduro, sem npm dep |
| Component lib (Svelte) | [skeleton.dev](https://www.skeleton.dev/) | MIT | tailwind-native |
| Tables | [TanStack Table](https://tanstack.com/table) | MIT | virtualização, sort, filter |
| Data fetching | [TanStack Query](https://tanstack.com/query) | MIT | cache, retries, mutations |
| Charts | [Apache ECharts](https://echarts.apache.org/) ou [Recharts](https://recharts.org/) | Apache 2 / MIT | maduros, customizáveis |
| JSON viewer | [react-json-view](https://github.com/uiwjs/react-json-view) ou [svelte-json-tree](https://github.com/timhall/svelte-json-tree) | MIT | rendering profundo |
| Syntax highlight | [Shiki](https://shiki.matsu.io/) | MIT | bundled themes |
| Icons | [Lucide](https://lucide.dev/) | ISC | consistent, framework-agnostic |
| OpenAPI codegen | [openapi-typescript](https://openapi-ts.dev/) | MIT | typed client free |
| Date | [date-fns](https://date-fns.org/) | MIT | leve, tree-shakeable |
| Forms | [React Hook Form](https://react-hook-form.com/) ou [Felte](https://felte.dev/) | MIT/Apache | perf |
| Tests | [Vitest](https://vitest.dev/) + [Playwright](https://playwright.dev/) | MIT/Apache | padrão atual |
| Hosting | [Vercel](https://vercel.com/) (PR previews) + self-host Docker | n/a | dev experience + customer ownership |

### Anti-reuso
- ❌ Material UI / Ant Design — demasiado opinionated, design não combina com Wake
- ❌ TailwindCSS plugins de admin pré-prontos — looks genérico
- ❌ Grafana embedded — usuário já roda Grafana se quer; aqui é product surface

---

## Risks e mitigações

### R5.1 — Replay scrubber performance com >10k eventos
**Prob:** alta · **Imp:** médio
- Virtualizar timeline (only render visible window)
- Pre-compute aggregated index server-side (`/sessions/{id}/events?bucket=1s`)
- Cap inicial: 1k eventos pre-renderizados, lazy-load resto

### R5.2 — SSE reconnect pode duplicar eventos
**Prob:** média · **Imp:** baixo
- Client envia `Last-Event-ID` no reconnect
- Backend já tem `events.subscribe(session_id, since=N)` no SQLite/Postgres

### R5.3 — OAuth callback complexo de testar
**Prob:** média · **Imp:** médio
- Mock OAuth provider em dev (existing pattern em `adapters/vault-infisical/tests/test_oauth.py`)
- Playwright e2e com mock callback

### R5.4 — Bundle size cresce explosivo (charts + json viewer + monaco)
**Prob:** média · **Imp:** alto
- Lazy-load rotas pesadas
- Substituir Monaco por CodeMirror se necessário
- Bundle analyzer no CI

### R5.5 — Frontend e backend evolution descompasso
**Prob:** alta · **Imp:** médio
- OpenAPI codegen quebra o build se schema mudar
- API versioning explícito (`/v1/sessions`)

### R5.6 — Acessibilidade ignorada
**Prob:** alta · **Imp:** baixo-médio
- Lighthouse a11y ≥90 como gate
- Radix UI (next) ou bits-ui (svelte) traz ARIA correto

### R5.7 — Auth weak permite ataque
**Prob:** média · **Imp:** alto
- Iniciar com bearer token gerado por wake CLI
- HTTPS obrigatório em prod
- Rate limiting via FastAPI middleware

---

## Decisões adiadas

- ❌ Multi-tenant (workspaces) — pós v1.0
- ❌ Histórico de prompts editáveis (`replay with diff`) — RFC futura
- ❌ Embedded code editor pra editar agent system prompt — pós v1.0
- ❌ White-label theming completo — pós v1.0
- ❌ Mobile app — provavelmente nunca; mobile web responsivo basta

---

## Definition of Done

- [ ] Todos os Exit Criteria checados
- [ ] Lighthouse ≥90 em todas as 4 páginas principais (sessions, replay, metrics, vault)
- [ ] CI green (lint, typecheck, unit, e2e)
- [ ] Helm chart inclui frontend service
- [ ] `docs/DASHBOARD.md` cobre setup completo
- [ ] Tag `v0.5.0-dashboard` em git
- [ ] Screenshot/asciinema/video curto pro README + launch

---

## Métricas de sucesso

| Métrica | Mínimo | Meta |
|---|---|---|
| Páginas funcionais | 4 (sessions, replay, metrics, vault) | 4 + storybook |
| Lighthouse Performance | ≥80 | ≥90 |
| Lighthouse Accessibility | ≥85 | ≥95 |
| Bundle size (gzip) | <500 KB | <300 KB |
| Time to interactive (3G simulated) | <5s | <3s |
| Replay scrubber FPS com 1k eventos | ≥30 | ≥60 |
| Cobertura de tests | ≥60% | ≥80% |

---

## After this phase

→ [Phase 6: Public Launch](./PHASE-6-public-launch.md) — dashboard se torna a star do launch. Asciinemas viram videos curtos no landing page. Demo principal: "Wake Dashboard rodando contra um cluster real com 50 sessions paralelas em LangGraph + CrewAI + Claude SDK + Pydantic AI."

---

## Multi-agent slicing sugerido

Padrão validado 4x: 3 agents paralelos. Slicing proposto:

| Slice | Worktree | Owns |
|---|---|---|
| `dashboard-shell` | `wake-wt-dashboard-shell` | Scaffolding + auth + sessions list + layout + CI |
| `dashboard-replay` | `wake-wt-dashboard-replay` | Replay scrubber + event detail + sandbox state panel |
| `dashboard-metrics-vault` | `wake-wt-dashboard-metrics-vault` | Metrics page + vault page + deploy (Helm + Compose) + DASHBOARD.md |

Cada slice ~120-180min wall-clock.

Pre-existing não modificar:
- `src/wake/` (backend Python — só **adicionar** endpoints se necessário, sem breaking)
- `adapters/*` (não toca)
- `phases/*-CONTRACT.md` anteriores

---

## Open questions (a fechar antes de despachar agents)

1. **Stack:** Next.js 15 vs SvelteKit 2?
2. **Auth:** API key local ou OAuth Infisical?
3. **Hosting:** static export + nginx, Node adapter, ou Vercel?
4. **Component lib:** shadcn/ui (se Next), skeleton.dev ou bits-ui (se Svelte)?
5. **Posição na roadmap:** Phase 5 (empurra public launch pra 6) ou Phase 6 (depois do launch)?
6. **Backend endpoints:** quais já existem, quais precisam ser adicionados? (auditar `src/wake/api/`)
