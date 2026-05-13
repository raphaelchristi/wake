# Phase 5 Execution Contract — Operator UI (Wake Dashboard)

> Construir o **Wake Dashboard** (SPA Next.js 15) que opera Wake em produção.
> 3 agents Opus em paralelo, slices disjuntos, merge sequencial.

---

## Decisões locked (não rediscutir)

| Decisão | Valor | Justificativa |
|---|---|---|
| Frontend stack | **Next.js 15** (App Router + RSC) | Ecosystem maior, shadcn/ui maduro, codegen confortável, Vercel optional |
| Package manager | **pnpm** | bundle eficiente, lockfile estável |
| Component lib | **shadcn/ui** + Tailwind v4 | copy-paste, sem npm dep, fácil customizar |
| Data fetching | **TanStack Query v5** | cache + SSE-friendly + retries |
| Tables | **TanStack Table v8** | virtualização, sort, filter, headless |
| Charts | **Recharts** (Composable React charts, SVG, leve) | jagged-edge bom o suficiente; ECharts em rotas heavy se precisar |
| OpenAPI codegen | **openapi-typescript** | client typed gerado do FastAPI |
| Tests | **Vitest** (unit) + **Playwright** (e2e) + **Storybook** (catalog) | padrão atual |
| Auth | **API key bearer** (header `X-Wake-API-Key`) | minimal MVP; OAuth fica pra v1.1 |
| Hosting | **Next.js standalone build → Docker** (multi-stage) | self-host first; Helm + Compose |
| Real-time | **SSE** (Wake já expõe `GET /sessions/{id}/stream`) + polling 5s fallback | nada de WebSocket novo |
| Date | **date-fns** | leve, tree-shakeable |
| Icons | **Lucide React** | consistent |
| JSON viewer | **react-json-view-lite** | leve |
| TypeScript | **strict** | sem `any` |

---

## Pre-existing — não modificar

- `src/wake/types.py`, `src/wake/store/*`, `src/wake/sandbox/*`, `src/wake/adapters/*`, `src/wake/runtime/*` — backend core locked
- `docs/SPEC-HARNESS-ADAPTER.md`, `docs/SPEC-EVENT-SCHEMA.md` — specs v0.1.0
- `adapters/*` — não tocar
- `phases/PHASE-*-CONTRACT.md` anteriores — histórico
- `pyproject.toml` raiz — exceto adição de novas deps opcionais por extras (se necessário)

**Backend FastAPI (`src/wake/api/`) pode ser ESTENDIDO** com novas rotas (additive only). Rotas existentes não podem mudar shape sem RFC.

### Endpoints já existentes (auditados)

```
GET    /health
POST   /agents          GET /agents          GET /agents/{id}          PATCH /agents/{id}
POST   /agents/{id}/archive  GET /agents/{id}/versions
POST   /environments    GET /environments    GET /environments/{id}    archive  delete
POST   /sessions        GET /sessions        GET /sessions/{id}        DELETE /sessions/{id}
POST   /sessions/{id}/interrupt              POST /sessions/{id}/archive
POST   /sessions/{id}/events                  GET /sessions/{id}/events
GET    /sessions/{id}/stream                  (SSE)
```

### Endpoints que cada slice adiciona

- **dashboard-shell** estende `GET /sessions` com query params (agent, status, model, since, until, q, page, page_size) — backwards-compatible
- **dashboard-replay** adiciona `GET /sessions/{id}/state-at/{seq}` (sandbox state snapshot reconstruction)
- **dashboard-metrics-vault** adiciona `GET /metrics/summary`, `GET /workers`, `GET /vault/credentials`, `POST /vault/oauth/start`, `GET /vault/oauth/callback`, `POST /vault/credentials/{id}/rotate`, `GET /vault/audit`

---

## Divisão de slices

| Agent | Worktree | Branch | Owns |
|---|---|---|---|
| `dashboard-shell` | `wake-wt-dashboard-shell` | `agent/dashboard-shell` | `frontend/` scaffolding + auth + sessions list + layout/theme + CI + OpenAPI codegen pipeline + extensão de `GET /sessions` filters |
| `dashboard-replay` | `wake-wt-dashboard-replay` | `agent/dashboard-replay` | Replay scrubber + event detail + sandbox state panel + backend `state-at` endpoint |
| `dashboard-metrics-vault` | `wake-wt-dashboard-metrics-vault` | `agent/dashboard-metrics-vault` | Metrics page + vault page + backend metrics/workers/vault routes + `deploy/` (Dockerfile + Helm + Compose) + `docs/DASHBOARD.md` |

Cada slice trabalha em `frontend/` dentro de subpastas disjuntas + um router FastAPI dedicado quando aplicável.

---

## Files ownership

### `dashboard-shell` owns

```
frontend/package.json                                            NEW
frontend/pnpm-lock.yaml                                          NEW (generated)
frontend/tsconfig.json                                           NEW
frontend/next.config.mjs                                         NEW
frontend/tailwind.config.ts                                      NEW
frontend/postcss.config.mjs                                      NEW
frontend/.eslintrc.cjs                                           NEW
frontend/.prettierrc                                             NEW
frontend/.gitignore                                              NEW
frontend/README.md                                               NEW
frontend/components.json                                         NEW   (shadcn config)
frontend/src/app/layout.tsx                                      NEW
frontend/src/app/page.tsx                                        NEW   (redirect → /sessions)
frontend/src/app/globals.css                                     NEW
frontend/src/app/(authed)/layout.tsx                             NEW   (auth gate + nav shell)
frontend/src/app/(authed)/sessions/page.tsx                      NEW
frontend/src/app/(authed)/sessions/[id]/page.tsx                 NEW   (detail shell only — replay tab provided by replay slice)
frontend/src/app/(authed)/sessions/loading.tsx                   NEW
frontend/src/app/login/page.tsx                                  NEW
frontend/src/components/ui/                                      NEW   (shadcn primitives copy)
frontend/src/components/layout/AppShell.tsx                      NEW
frontend/src/components/layout/Sidebar.tsx                       NEW
frontend/src/components/layout/Topbar.tsx                        NEW
frontend/src/components/sessions/SessionsTable.tsx               NEW
frontend/src/components/sessions/SessionFilters.tsx              NEW
frontend/src/components/sessions/SessionRow.tsx                  NEW
frontend/src/components/sessions/SessionStatusBadge.tsx          NEW
frontend/src/lib/api/client.ts                                   NEW   (fetch wrapper + auth header)
frontend/src/lib/api/types.ts                                    NEW   (re-export generated openapi types)
frontend/src/lib/api/generated.ts                                NEW   (output do openapi-typescript)
frontend/src/lib/auth.ts                                         NEW
frontend/src/lib/format.ts                                       NEW   (dates, durations, money)
frontend/src/lib/sse.ts                                          NEW   (EventSource hook + reconnect)
frontend/src/lib/queryClient.ts                                  NEW
frontend/src/hooks/useSessions.ts                                NEW
frontend/src/hooks/useSession.ts                                 NEW
frontend/src/hooks/useSSE.ts                                     NEW
frontend/src/styles/                                             (extends globals.css if needed)
frontend/tests/unit/sessions-table.test.tsx                      NEW
frontend/tests/unit/api-client.test.ts                           NEW
frontend/tests/unit/auth.test.ts                                 NEW
frontend/tests/e2e/sessions-list.spec.ts                         NEW
frontend/playwright.config.ts                                    NEW
frontend/vitest.config.ts                                        NEW
frontend/.github/workflows/frontend-ci.yml                       NEW   (deve ir em .github/workflows/ no merge — see Cross-cutting)

# Backend additions (additive)
src/wake/api/routes/sessions.py                                  UPDATE: add filter query params to GET /sessions
src/wake/api/schemas.py                                          UPDATE if needed
```

### `dashboard-replay` owns

```
frontend/src/app/(authed)/sessions/[id]/replay/page.tsx          NEW
frontend/src/app/(authed)/sessions/[id]/replay/loading.tsx       NEW
frontend/src/components/replay/ReplayScrubber.tsx                NEW
frontend/src/components/replay/EventList.tsx                     NEW
frontend/src/components/replay/EventTypeBadge.tsx                NEW
frontend/src/components/replay/EventDetail.tsx                   NEW   (JSON viewer + payload nav)
frontend/src/components/replay/SandboxStatePanel.tsx             NEW
frontend/src/components/replay/PlaybackControls.tsx              NEW
frontend/src/components/replay/TimelineTrack.tsx                 NEW
frontend/src/hooks/useReplayState.ts                             NEW   (reducer pra scrubber position + play state)
frontend/src/hooks/useEvents.ts                                  NEW
frontend/src/hooks/useStateAt.ts                                 NEW
frontend/src/lib/replay/index.ts                                 NEW   (event grouping, timestamps)
frontend/src/lib/replay/types.ts                                 NEW
frontend/tests/unit/replay-scrubber.test.tsx                     NEW
frontend/tests/unit/event-list.test.tsx                          NEW
frontend/tests/unit/replay-state.test.ts                         NEW
frontend/tests/e2e/replay.spec.ts                                NEW
frontend/stories/replay/ReplayScrubber.stories.tsx               NEW
frontend/stories/replay/EventDetail.stories.tsx                  NEW

# Backend additions
src/wake/api/routes/state.py                                     NEW   (router: GET /sessions/{id}/state-at/{seq})
src/wake/api/state_reconstruction.py                             NEW   (logic)
src/wake/api/app.py                                              UPDATE: include state.router
tests/unit/test_state_reconstruction.py                          NEW
```

### `dashboard-metrics-vault` owns

```
# Frontend — Metrics
frontend/src/app/(authed)/metrics/page.tsx                       NEW
frontend/src/components/metrics/LatencyChart.tsx                 NEW
frontend/src/components/metrics/CostChart.tsx                    NEW
frontend/src/components/metrics/ThroughputChart.tsx              NEW
frontend/src/components/metrics/ErrorRateChart.tsx               NEW
frontend/src/components/metrics/WorkerHealth.tsx                 NEW
frontend/src/components/metrics/MetricsTimeRangePicker.tsx       NEW
frontend/src/hooks/useMetrics.ts                                 NEW
frontend/src/hooks/useWorkers.ts                                 NEW

# Frontend — Vault
frontend/src/app/(authed)/vault/page.tsx                         NEW
frontend/src/app/(authed)/vault/audit/page.tsx                   NEW
frontend/src/components/vault/CredentialsList.tsx                NEW
frontend/src/components/vault/AddCredentialDialog.tsx            NEW
frontend/src/components/vault/RotateCredentialDialog.tsx         NEW
frontend/src/components/vault/AuditLog.tsx                       NEW
frontend/src/components/vault/ProviderIcon.tsx                   NEW
frontend/src/hooks/useCredentials.ts                             NEW
frontend/src/hooks/useAudit.ts                                   NEW

# Frontend — OAuth callback
frontend/src/app/oauth/callback/page.tsx                         NEW
frontend/src/app/oauth/callback/route.ts                         NEW   (server action receives code, posts to backend)

frontend/tests/unit/metrics-chart.test.tsx                       NEW
frontend/tests/unit/vault-list.test.tsx                          NEW
frontend/tests/e2e/metrics.spec.ts                               NEW
frontend/tests/e2e/vault.spec.ts                                 NEW

# Backend additions
src/wake/api/routes/metrics.py                                   NEW   (GET /metrics/summary, GET /workers)
src/wake/api/routes/vault.py                                     NEW   (vault routes)
src/wake/api/metrics_aggregation.py                              NEW
src/wake/api/app.py                                              UPDATE: include metrics.router, vault.router
tests/unit/test_metrics_aggregation.py                           NEW
tests/unit/test_vault_routes.py                                  NEW

# Deploy
deploy/Dockerfile.frontend                                       NEW   (multi-stage Next.js standalone)
deploy/docker-compose.yml                                        UPDATE: + frontend service (don't break existing)
deploy/helm/wake/templates/deployment-frontend.yaml              NEW
deploy/helm/wake/templates/service-frontend.yaml                 NEW
deploy/helm/wake/templates/ingress.yaml                          UPDATE   (route / → frontend, /api → wake-api)
deploy/helm/wake/values.yaml                                     UPDATE   (frontend.enabled, image, replicas)

# Docs
docs/DASHBOARD.md                                                NEW
```

---

## Cross-cutting (cuidado!)

### `frontend/.github/workflows/frontend-ci.yml`

CI config tem que viver em `.github/workflows/` (não em `frontend/`). O slice **dashboard-shell** cria o file em `.github/workflows/frontend-ci.yml`. Os outros 2 slices **não tocam** — orchestrator garante isso ao merge.

### `src/wake/api/app.py`

`include_router` calls — cada slice (replay, metrics-vault) **adiciona uma linha**. Conflito esperado: orchestrator resolve no merge mantendo todas as inclusões.

### `frontend/src/components/ui/` (shadcn)

shadcn copia primitives no `dashboard-shell`. Outros slices podem reusar (Read-only) ou adicionar componentes shadcn novos via `pnpm dlx shadcn add <comp>` — desde que não modifiquem primitives já copiados pelo shell.

### `frontend/src/app/(authed)/layout.tsx`

Definido pelo shell. Outros slices respeitam o layout via Next.js layouts.

### `pyproject.toml` raiz

Provavelmente nada a alterar (frontend é Node, não Python). Se algum slice precisar de dev dep Python nova, adiciona em `[project.optional-dependencies] dev` — conflito potencial menor.

### `deploy/docker-compose.yml` e `deploy/helm/wake/templates/ingress.yaml`

Existem (criados em Phase 4). Slice metrics-vault **modifica** ambos. Outros slices não tocam.

---

## ACCEPTANCE CRITERIA por slice

### `dashboard-shell` done quando:

- [ ] `cd frontend && pnpm install && pnpm build` works
- [ ] `pnpm dev` sobe servidor em http://localhost:3000
- [ ] `/login` aceita API key, persiste em localStorage (não em cookie), redireciona pra `/sessions`
- [ ] `/sessions` lista sessions via API call autenticada com `X-Wake-API-Key`
- [ ] Tabela paginada (TanStack Table) com colunas: ULID short, agent, status badge, model, created_at relative, duration, event_count
- [ ] Filtros (URL query params): `agent=...&status=...&model=...&since=ISO&until=ISO&q=text&page=N`
- [ ] Click row → `/sessions/[id]` (página de detail; tab de replay implementada pelo replay slice)
- [ ] Layout: sidebar (Sessions / Metrics / Vault) + topbar (logout + dark mode toggle)
- [ ] Dark mode default + light toggle persiste em localStorage
- [ ] OpenAPI codegen pipeline: `pnpm openapi:generate` lê `http://localhost:8080/openapi.json` (fallback: read `openapi.json` no repo)
- [ ] Backend: `GET /sessions` aceita query params; passa testes unitários
- [ ] `pnpm test` (Vitest) e `pnpm test:e2e` (Playwright) verdes
- [ ] Lighthouse `/sessions` Performance ≥85, Accessibility ≥90
- [ ] CI workflow `.github/workflows/frontend-ci.yml` (lint + typecheck + test + build)
- [ ] `frontend/README.md` documenta setup, scripts, env vars
- [ ] TypeScript strict, sem `any` em código de produção

### `dashboard-replay` done quando:

- [ ] `/sessions/[id]/replay` página rendered
- [ ] Timeline horizontal com 1 tick por evento, coloridos por tipo (user.message azul, assistant.message verde, tool_use roxo, tool_result amarelo, sandbox.* cinza, vault.* laranja, error vermelho)
- [ ] Scrubber arrastável: click no tick OU drag handle
- [ ] Playback controls: play/pause, step ←, step →, jump start, jump end, speed (0.5x/1x/2x/5x)
- [ ] Keyboard shortcuts: ← → Space Home End
- [ ] Painel esquerdo: lista de eventos (virtualized se >500 eventos)
- [ ] Painel direito: detalhe do evento focado — header (seq, type, timestamp), JSON viewer do payload, copy button
- [ ] Painel inferior: estado reconstruído do sandbox naquele evento — cwd, last bash output (text), files modified (lista) — via novo endpoint `GET /sessions/{id}/state-at/{seq}`
- [ ] Performance: 1k eventos com 60fps no scrubber
- [ ] Backend: `GET /sessions/{id}/state-at/{seq}` retorna `{ seq, sandbox: {cwd, last_output_lines, files_modified}, tool_calls_so_far: int, errors_so_far: int }`
- [ ] State reconstruction: replay evento por evento até `seq` mantendo estado mínimo (sandbox + counters)
- [ ] Tests: unit (reducer, event-list, scrubber); e2e (Playwright cena de 50 eventos)
- [ ] Storybook stories pros 3 componentes principais (ReplayScrubber, EventList, EventDetail)
- [ ] Mocks de dados em `frontend/tests/fixtures/events-fixture.json`

### `dashboard-metrics-vault` done quando:

**Métricas:**
- [ ] `/metrics` página com 6 cards: latency (p50/p95/p99), cost USD total/avg, throughput sessions/h, error rate %, workers ativos, queue depth
- [ ] Charts (Recharts): latency line chart, cost histogram, throughput area chart
- [ ] Time range picker: 1h / 24h / 7d / 30d
- [ ] Backend: `GET /metrics/summary?window=24h` retorna agregados; `GET /workers` retorna heartbeat status
- [ ] Métricas agregam de `events` (timestamps, payloads `cost_usd` em metadata) — funciona com SQLite e Postgres
- [ ] Refresh manual button + auto-refresh 30s

**Vault:**
- [ ] `/vault` lista credentials (name, provider, created_at, last_used) — **sem expor tokens**
- [ ] Botão "Add credential" → dialog com escolha de provider (GitHub/Slack/Notion) → inicia OAuth flow
- [ ] OAuth callback page `/oauth/callback` recebe code, posta pro backend `POST /vault/oauth/callback`, mostra resultado
- [ ] Botão "Rotate" abre dialog, executa `POST /vault/credentials/{id}/rotate`
- [ ] `/vault/audit` lista accesses recentes (session_id link, provider, host, allowed/denied, timestamp)
- [ ] Backend: 7 routes acima implementadas em `src/wake/api/routes/vault.py`, delegando pro `wake_vault_infisical` adapter quando disponível (graceful degradation se vault não configurado)
- [ ] Tokens **NUNCA** retornados via API — só metadata + hashes

**Deploy:**
- [ ] `deploy/Dockerfile.frontend` multi-stage (deps → build → standalone runner)
- [ ] `deploy/docker-compose.yml` ganha service `frontend` com healthcheck
- [ ] Helm chart: deployment + service + ingress route `/` → frontend, `/api` → wake-api
- [ ] `helm lint deploy/helm/wake` clean
- [ ] `docker compose -f deploy/docker-compose.yml config` valida
- [ ] `docs/DASHBOARD.md` ≥500 linhas: setup local, auth, customização, deploy production, troubleshooting, screenshots de cada surface

**Quality (todos):**
- [ ] Vitest + Playwright tests passam em cada slice individualmente
- [ ] TypeScript strict
- [ ] Bundle size cada rota <300KB gzip
- [ ] ruff/mypy strict clean em adições Python

---

## ENTRY POINTS

Frontend é app Next.js standalone. Backend FastAPI já tem `app = FastAPI()` em `src/wake/api/app.py`. Novos routers registrados via `app.include_router(...)`.

---

## SHARED DECISIONS

### Versioning
- Frontend `package.json` versão `0.5.0`
- Backend permanece `wake-ai 0.0.1` (pode bumpar pra `0.5.0` no merge final, decisão do orchestrator)

### Auth header
- Frontend envia `X-Wake-API-Key: <key>` em todas requests
- Backend valida via FastAPI `Depends(verify_api_key)` (a ser adicionado por dashboard-shell)
- Chave default lida de env `WAKE_API_KEY`

### CORS
- dashboard-shell adiciona CORSMiddleware permitindo `localhost:3000` em dev, configurável via env `WAKE_API_CORS_ORIGINS`

### Style
- Tailwind v4 (CSS-first config)
- Theme tokens em `frontend/src/styles/tokens.css`
- Dark mode via `class="dark"` no `<html>`, persistido em `localStorage.theme`

### Testing
- Vitest pra unit + react-testing-library
- Playwright pra e2e (browsers: chromium + firefox)
- Sem real backend nos testes — MSW (Mock Service Worker) intercepta fetch

### CI
- pnpm install --frozen-lockfile
- pnpm lint && pnpm typecheck && pnpm test && pnpm build
- Lighthouse CI opcional (não-bloqueante)

### Real frontend stack pinning
```
next@^15.0.0
react@^19.0.0
react-dom@^19.0.0
typescript@^5.6.0
tailwindcss@^4.0.0
@tanstack/react-query@^5.59.0
@tanstack/react-table@^8.20.0
recharts@^2.13.0
date-fns@^4.1.0
lucide-react@^0.453.0
react-json-view-lite@^1.5.0
zod@^3.23.0
```

Devops:
```
@playwright/test@^1.48.0
vitest@^2.1.0
@vitejs/plugin-react@^4.3.0
@testing-library/react@^16.0.0
msw@^2.4.0
openapi-typescript@^7.4.0
@storybook/react@^8.4.0  (apenas onde houver stories)
```

---

## MERGE ORDER

1. **`dashboard-shell`** → main (estabelece frontend/, backend filter additive, CI workflow)
2. **`dashboard-replay`** → main (conflito esperado: `frontend/src/app/(authed)/sessions/[id]/page.tsx` se shell criar a tab UI; e `src/wake/api/app.py` include_router)
3. **`dashboard-metrics-vault`** → main (conflitos esperados: `src/wake/api/app.py`, `deploy/docker-compose.yml`, `deploy/helm/wake/values.yaml`, `deploy/helm/wake/templates/ingress.yaml`)

Após cada merge:
```bash
source .venv/bin/activate
pytest src/wake/api -q 2>&1 | tail -2     # backend regression
cd frontend && pnpm install --frozen-lockfile && pnpm build
```

---

## CONVENÇÕES

- TypeScript strict, ESLint, Prettier — `pnpm lint`, `pnpm typecheck`, `pnpm format`
- Python 3.11+, ruff, mypy strict — onde houver código Python adicional
- Commit prefixes: `frontend:`, `api:`, `deploy:`, `docs:`
- Cada slice **EXCLUSIVAMENTE no seu worktree** (`wake-wt-dashboard-*`)
- Sem real OAuth providers em testes — MSW mocks
- Sem real Postgres em testes Python — usar SQLiteStore in-memory
- `pnpm` (NÃO npm/yarn)

---

## DELIVERABLES por agent (resumo)

| Slice | Frontend | Backend | Outros |
|---|---|---|---|
| dashboard-shell | scaffolding + auth + sessions list + layout + CI + codegen | filter query params em GET /sessions | frontend/README.md |
| dashboard-replay | scrubber + event list + detail + state panel + storybook | state-at endpoint + reconstruction logic | fixtures |
| dashboard-metrics-vault | metrics + vault + audit + OAuth callback | metrics + workers + vault routes (7) | Dockerfile + Helm + Compose update + DASHBOARD.md |

---

## REGRA DE OURO

1. **Leia este contrato + phases/PHASE-5-operator-ui.md + estrutura existente de `src/wake/api/` ANTES de codar.**
2. **Frontend é Next.js 15 App Router. shadcn/ui + Tailwind v4. pnpm. TypeScript strict.**
3. **Backend additions são ADDITIVE — não muda shape de rotas existentes.**
4. **OpenAPI codegen é a fonte de verdade pros tipos do frontend.**
5. **Tokens NUNCA expostos via API/frontend.**
6. **Commit no SEU worktree** (`wake-wt-dashboard-<slice>/`), branch `agent/dashboard-<slice>`.
7. **Quando terminar**: reporte tests (vitest + playwright + pytest), Lighthouse scores se aplicável, files fora do slice tocados.
8. **Estimativa**: 120-180min wall-clock por slice.
9. **NÃO PUSH. NÃO MERGE.** Orchestrator faz.
