# CONTEXT — Wake (2026-05-14 14:55)

Briefing pra retomar em sessão nova. Wake é substrato durável open-source pra agentes de IA, framework-agnostic via HarnessAdapter ABI. Inspirado no Anthropic Managed Agents.

---

## TL;DR

- **Repo:** https://github.com/raphaelchristi/wake — HEAD `bca099e`, tag `v0.5.2-fixes`.
- **Phases 0-5.2 ✅ shipped.** Roadmap re-priorizado em 2026-05-14: Public Launch foi adiado pra Phase 10; **Phase 6 = Multi-tenancy + RBAC** é o próximo.
- **POC ceppem-agent funcionou** — `root_orchestrator` (CompiledStateGraph 9 nodes) wrappeado com `LangGraphAdapter`, ABI conformance OK, conformance suite 1/10 (esperado sem mock LLM).
- **Backend tenancy já está parcialmente pronto** (em `git stash`, ~25 arquivos). `src/wake/tenancy.py`, alembic migration 0002, `organization_id`/`workspace_id` first-class em stores+routes+types, header `X-Wake-Organization-Id` / `X-Wake-Workspace-Id` honrado pela API.
- **Próximo passo concreto:** popar o stash, revisar/completar o backend tenancy, depois executar `docs/FRONTEND-TENANCY.md` (8 ajustes mapeados pra dashboard).

---

## Próximo passo (a fazer)

**Phase 6 — Multi-tenancy + RBAC. Sessão começa por:**

```bash
# 1. Inspecionar e recuperar o WIP de backend tenancy
git stash list
git stash show --name-only stash@{0}
git stash pop                                       # ~25 arquivos volta pra working tree

# 2. Ler o playbook do frontend
cat docs/FRONTEND-TENANCY.md                        # 8 ajustes mapeados pra dashboard

# 3. Validar o backend stashed
source .venv/bin/activate
pytest tests/unit/ -q                               # baseline antes do que veio do stash
pytest tests/unit/test_api_tenancy.py -v            # arquivo novo do stash — confirmar passing
pytest adapters/postgres-store/tests/ -q            # migration 0002 não pode quebrar

# 4. Cobrir RBAC (que ainda NÃO está no stash) — Tier 0 gap #2
#    Backend tenancy resolve Tier 0 #1. RBAC (Tier 0 #2) ainda missing.
#    Backup story (Tier 0 #3) também missing — phase 6 ou 7, decidir.
```

**Ordem dentro da Phase 6:**

1. **Backend (parcial → completo)** — pop stash, fix qualquer gap, write tests faltantes
2. **RBAC layer** — `User` entity + roles (`admin`/`operator`/`viewer`) + per-user session scoping
3. **Frontend** — executar `docs/FRONTEND-TENANCY.md` (lista 8 items, ~1-2 dias multi-agent)
4. **Backup runbook** — `pgbackrest` wireado em Helm + `docs/DISASTER-RECOVERY.md`

---

## Sessão anterior (2026-05-13 14:55 → 2026-05-14 14:50)

Sessão longa (≈24h cobrindo Phase 5 → 5.1 → 5.2 → planning de tenancy). Resumo do que mudou:

- **Phase 5** (Operator UI) shipped — Next.js 15 dashboard + replay scrubber + métricas + vault management. 3 slices multi-agent. Backend additions additive.
- **Codex adversarial review** rodada — encontrou 6 findings (3 crit + 3 high)
- **Phase 5.1** shipped — 3 slices fix em paralelo (auth-env-canon, api-bootstrap, vault-state-rotate). Resolveu auth fail-open, missing wake worker, OAuth state per-process, rotate dup, frontend env var mismatch.
- **Codex adversarial review #2** rodada — encontrou 3 regressões introduzidas por 5.1
- **Phase 5.2** shipped (inline, sem multi-agent) — sync Uvicorn factory, shared `WAKE_OAUTH_STATE_SECRET` no Helm, worker holds advisory lock during step
- **README rewrite** — foreground decision criteria: "Why Wake / When / When NOT / K8s analogy / Known gaps"
- **docs/ROADMAP.md rewrite** — 23 gaps tiered (0-5), nova ordem de phases. Public Launch movido pra Phase 10.
- **POC ceppem-agent** — confirmou que LangGraph adapter wrapa `root_orchestrator` sem mudar 1 linha do ceppem
- **Backend tenancy iniciado** — encontrado WIP não-commitado (provavelmente sessão paralela); stashed pra preservar

---

## Current state

- **Branch:** `main`, sincronizado com `origin/main`
- **HEAD:** `bca099e docs: roadmap reordered around 23 gaps from adversarial reviews + ceppem POC`
- **Working tree:** clean (último commit foi o ROADMAP)
- **Stash:** `stash@{0}: WIP on main: 894eead readme: foreground the decision criteria` — contém backend tenancy
- **Tags:** `spec-v0.1.0-frozen`, `v0.4.0-production`, `v0.5.0-dashboard`, `v0.5.1-fixes`, `v0.5.2-fixes`
- **Active gh:** `raphaelchristi` (não `raphaelcsogitec` — switchar se push falhar 403)
- **Venv:** `.venv/` Python 3.11.10 com todos adapters + ceppem-agent venv tem wake-ai+langgraph adapter instalado (POC ainda válido)

### Stash inventário (Phase 6 starting kit)

```
adapters/postgres-store/alembic/versions/0002_tenancy_columns.py    NEW
adapters/postgres-store/src/wake_store_postgres/agents.py           M  — +organization_id +workspace_id
adapters/postgres-store/src/wake_store_postgres/environments.py     M
adapters/postgres-store/src/wake_store_postgres/events.py           M
adapters/postgres-store/src/wake_store_postgres/models.py           M  — colunas + indexes
adapters/postgres-store/src/wake_store_postgres/sessions.py         M
adapters/postgres-store/alembic/versions/0001_initial_schema.py     M

src/wake/tenancy.py                                                 NEW — DEFAULT_*_ID + helpers
src/wake/api/dependencies.py                                        M  — tenant header parsing
src/wake/api/routes/{agents,environments,events,metrics,sessions,state}.py  M — tenant scope filters
src/wake/api/sse.py                                                 M
src/wake/core/agent.py / event_log.py / session.py                  M
src/wake/store/base.py / sqlite.py                                  M
src/wake/types.py                                                   M  — organization_id/workspace_id em entidades

tests/unit/fakes.py / test_store.py                                 M
tests/unit/test_api_tenancy.py                                      NEW

docs/ARCHITECTURE.md / DASHBOARD.md                                 M
docs/FRONTEND-TENANCY.md                                            NEW — playbook detalhado do frontend
```

### Tests baseline (pré-stash)

```bash
source .venv/bin/activate
pytest tests/unit/ -q                          # 277 pass / 5 fail (httpx[socks] pre-existing)
pytest adapters/claude-sdk/tests/ -q           # 14 pass
pytest adapters/conformance/tests/ -q          # 29 pass
pytest adapters/langgraph/tests/ -q            # 42 pass
pytest adapters/postgres-store/tests/ -q       # 18 pass / 37 skip
pytest adapters/sandbox-runtime/tests/ -q      # 46 pass / 2 skip
pytest adapters/vault-infisical/tests/ -q      # 47 pass
pytest adapters/llm-litellm/tests/ -q          # 39 pass
# frontend: pnpm vitest run                    # 79 pass

# Pré-existentes em test_cli_client.py (5 fails por httpx[socks] missing); não bloqueia
```

---

## docs/FRONTEND-TENANCY.md — playbook do que falta no dashboard

Doc detalhado (do stash) lista **8 ajustes** pra alinhar frontend com backend tenancy:

1. **API client envia headers de tenant** (`frontend/src/lib/api/client.ts`)
   - Criar `frontend/src/lib/tenant.ts` com `getTenantScope()` (lê `wake.organization_id`/`wake.workspace_id` do localStorage, fallback `default/default`)
   - `WakeApiClient.headers()` injeta `X-Wake-Organization-Id` + `X-Wake-Workspace-Id` em toda request autenticada

2. **Tipos gerados/stubs** (`frontend/src/lib/api/generated.ts` + `types.ts` + `replay/types.ts` + fixtures)
   - Adicionar `organization_id` / `workspace_id` em `Session`, `AgentConfig`, `Event`

3. **TanStack Query cache keys** incluem `workspaceId`
   - `["sessions", workspaceId, filters]`, `["session", workspaceId, sessionId]`, etc
   - Arquivos: `useSessions.ts`, `useSession.ts`, `useEvents.ts`, `useStateAt.ts`, `useMetrics.ts`, `useWorkers.ts`

4. **SSE proxy Next.js** (`frontend/src/lib/sse.ts` + `useSSE.ts` + replay page)
   - `EventSource` não aceita custom headers; criar rota Next.js `/api/wake/sessions/[id]/stream` que injeta tenant headers e faz proxy do stream

5. **Workspace selector UI**
   - `frontend/src/app/login/page.tsx` (inputs)
   - `frontend/src/components/layout/Topbar.tsx` (selector)
   - `frontend/src/app/providers.tsx` + `lib/queryClient.ts` (invalidate queries on switch)

6. **OAuth callback proxy** (`frontend/src/app/oauth/callback/api/route.ts`)
   - Encaminhar tenant headers; senão credentials caem em `default/default`

7. **Tests a adicionar** em `api-client.test.ts`, `fixtures/sessions.ts`, hooks tests, e2e mocks
   - Mínimo: headers presentes, fallback default, query keys mudam com workspaceId, fixtures incluem org_id/workspace_id, SSE preserva tenant

8. **Critério de aceite** — 6 checks (request autenticada envia tenant scope; nenhuma cache shared entre workspaces; tipos refletem tenancy; replay/SSE no workspace certo; OAuth não vaza pra default; tests cobrem 2+ workspaces)

**Path do doc no stash:** `git show "stash@{0}^3:docs/FRONTEND-TENANCY.md"` (parent `^3` é a árvore de untracked).

---

## Roadmap re-priorizado (de docs/ROADMAP.md)

| Phase | Foco | Tier resolvido |
|---|---|---|
| ✅ 0-5 | Design Lock → Skeleton → ABI → Adapters → Production Stack → Operator UI | — |
| ✅ 5.1 / 5.2 | Adversarial review fixes | — |
| ⚪ **6 next** | **Multi-tenancy + RBAC + backup** | **Tier 0 (#1 #2 #3)** |
| ⚪ 7 | Ops hardening (idempotency, retention, rate limit, cost budget, Prometheus) | Tier 1 |
| ⚪ 8 | Client SDKs (Python + TS) + edit-and-replay + eval framework | Tier 2 |
| ⚪ 9 | Adapter catalog público + supply chain + benchmarks | Tier 3 |
| ⚪ 10 | Public Launch (era Phase 6) | — |
| ⚪ 11+ | Memory / artifacts / multi-agent / scheduled / computer-use | Tier 4 |

Razões + detalhes em [`docs/ROADMAP.md`](docs/ROADMAP.md). Phase 5/5.1/5.2 não têm tier mapping porque já shipparam.

---

## Discoveries (manter em mente)

### Stash não inclui untracked por padrão — usar `--include-untracked`

`git stash` sem flag perde `src/wake/tenancy.py`, `docs/FRONTEND-TENANCY.md`, etc. Pra extrair untracked-files do stash: `git show "stash@{0}^3:<path>"` (parent `^3` é a tree dos untracked).

### ceppem-agent rodando POC sem proxy

Importação de `graphs.root_orchestrator` falha por `httpx[socks]` se `HTTP_PROXY=http://localhost:56240` estiver setado no shell. Workaround: `unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY` antes de `python -c "from graphs.root_orchestrator..."`.

### Codex review tem limite de 1MB de input

Working tree com `.pnpm-store/` (untracked, ~60k files) crasha Codex adversarial review com `Input exceeds the maximum length of 1048576 characters`. **`.pnpm-store/` já está em `.gitignore`** (commit `12503de`), mas se reaparecer: confirmar gitignore.

### Helm `fail` directive funciona como gate de install

`{{- fail "..." -}}` num template aborta helm install com mensagem custom. Usado em `deploy/helm/wake/templates/secret.yaml` pra exigir `auth.apiKey` quando `auth.required=true`, e `auth.oauthStateSecret` quando `api.replicas > 1`. **Verificado via `helm template` em 3 cenários** (Phase 5.2).

### Uvicorn `--factory` exige callable síncrono

Async factory retorna coroutine; Uvicorn não awaits. Quem usar `uvicorn.run(..., factory=True)` precisa de função `def`, não `async def`. Fix em Phase 5.2: `create_production_app()` é sync e retorna FastAPI vazio; async init vai pra lifespan que Uvicorn awaits antes de aceitar traffic. Helper `create_production_app_async()` mantido pra tests/scripts.

### `WorkerHeartbeat.start()` precisa ser chamado pra lock segurar

Phase 5.1 criava `WorkerHeartbeat` mas nunca chamava `.start()`. Resultado: lock liberava antes do step. Phase 5.2 fix: `_try_claim` retorna handle (heartbeat instance), `.start()` adquire lock + heartbeat row, `.stop()` no `finally`.

### Backend tenancy stash detalhe — `models.py` adiciona colunas

`adapters/postgres-store/src/wake_store_postgres/models.py` ganha `organization_id`/`workspace_id` em `AgentRow`, `SessionRow`, `EventRow`, etc + index composto. Alembic migration `0002_tenancy_columns.py` adiciona as colunas com default `'default'` pra compat com data existente. **Validar a migration upgrade+downgrade antes de mergear.**

---

## Pending / Known issues

1. **`pydantic-ai` upstream drift** — 10 testes do `wake-adapter-pydantic-ai` quebram após bump pra `1.31.0` (`ToolReturnPart.outcome` removed). Pin `pydantic-ai<1.31` no adapter ou atualizar adapter.py.
2. **`wake-adapter-crewai`** — 9 testes failing similar; precisa investigação.
3. **`tests/unit/test_cli_client.py`** — 5 fails pre-existentes por `httpx[socks]` missing. Adicionar `httpx[socks]` em dev deps.
4. **Discovery loaders no CLI** — `EntryPointRegistry` existe mas `wake adapter list` / `wake store list` / `wake vault list` não wired.
5. **CrewAI 224 warnings em tests** — Pydantic deprecation upstream, não-actionable.
6. **`ToolDescriptor.schema` shadow warning** — rename `input_schema` em RFC futura.
7. **Pytest cross-package collision** — workaround é rodar por package; fix futuro com `--import-mode=importlib`.
8. **Phase 6 starting state confuso** — backend stashed + RBAC não-iniciado + backup não-iniciado. Decidir: stash pop first (tenancy CORE), depois RBAC + backup como deliverables paralelos.
9. **README link pra `docs/ROADMAP.md`** funciona agora (criado nesta sessão); a entrada `docs/ROADMAP-HISTORICAL.md` é o old day-based plan.

---

## Files-chave a revisitar (próxima sessão)

1. **[`docs/ROADMAP.md`](docs/ROADMAP.md)** — 23 gaps tiered, plano detalhado por phase, why-this-order
2. **[`docs/FRONTEND-TENANCY.md`](docs/FRONTEND-TENANCY.md)** (no stash; extrair com `git show stash@{0}^3:docs/FRONTEND-TENANCY.md`) — playbook 8 items pro frontend
3. **`src/wake/tenancy.py`** (no stash) — backend tenancy entry point
4. **`adapters/postgres-store/alembic/versions/0002_tenancy_columns.py`** (no stash) — migration que precisa validar
5. **`tests/unit/test_api_tenancy.py`** (no stash) — confirma se passa
6. **[`phases/README.md`](phases/README.md)** — status table refletindo nova ordem (Phase 6 = multi-tenancy)
7. **[`docs/SPEC-EVENT-SCHEMA.md`](docs/SPEC-EVENT-SCHEMA.md)** — verificar se schema precisa amendment pra tenancy (provavelmente sim — eventos ganham `organization_id`/`workspace_id`)

---

## Commands pra rodar local

### Setup do zero

```bash
cd /Users/raphael/Desktop/repos/managed-agents
uv venv --python 3.11 .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
uv pip install -e adapters/claude-sdk -e adapters/conformance \
                  -e adapters/langgraph -e adapters/crewai \
                  -e adapters/pydantic-ai \
                  -e adapters/postgres-store -e adapters/sandbox-runtime \
                  -e adapters/vault-infisical -e adapters/llm-litellm
```

### Subir backend + frontend pra testar (Phase 5.2 estado atual)

```bash
# backend (port 8080)
source .venv/bin/activate
WAKE_API_KEY=dev uvicorn --factory wake.api.bootstrap:create_production_app --host 127.0.0.1 --port 8080 &

# frontend dev (port 3000)
export PATH=/opt/homebrew/Cellar/node/25.9.0_2/bin:$PATH
cd frontend && npx pnpm@10.33.0 dev
# dashboard em http://localhost:3000 — login com "dev" como API key
```

### Subir stack production self-host

```bash
export WAKE_API_KEY=$(openssl rand -hex 32)
docker compose -f deploy/docker-compose.yml up    # API + worker + Postgres + redis + agentgateway + vault + dashboard
# Helm: helm install wake deploy/helm/wake --set auth.apiKey=$WAKE_API_KEY --set auth.oauthStateSecret=$(openssl rand -hex 32)
```

### Iniciar Phase 6 (multi-tenancy)

```bash
# 1. Recuperar backend WIP
git stash pop

# 2. Verificar que migration roda em SQLite + Postgres
pytest tests/unit/test_api_tenancy.py adapters/postgres-store/tests/ -q

# 3. Ler playbook frontend
git show "stash@{0}^3:docs/FRONTEND-TENANCY.md" | less   # se ainda no stash
# OU se já popado:
cat docs/FRONTEND-TENANCY.md

# 4. Escrever phases/PHASE-6-CONTRACT.md (modelo: PHASE-5-CONTRACT.md):
#    Slice A: backend completion + RBAC (User + roles + per-user scoping)
#    Slice B: frontend tenancy (8 items do FRONTEND-TENANCY.md)
#    Slice C: backup runbook (pgbackrest no Helm + docs/DISASTER-RECOVERY.md)

# 5. Worktrees + dispatch agents conforme padrão Phase 4/5
```

---

## Cronologia (últimas entradas)

| Data | Marco | Commit/Tag | Status |
|---|---|---|---|
| 2026-05-13 | Phases 1-4 done via multi-agent (Skeleton → Production Stack) | até `3647537` | shipped |
| 2026-05-13 | Tag `v0.4.0-production` + README rewrite | `ed80791` → `3c06d28` | shipped |
| 2026-05-13 | Phase 5 done (Operator UI: Next.js + replay scrubber + métricas + vault) | `26e8d30` → `87c748b` + tag `v0.5.0-dashboard` | shipped |
| 2026-05-13 | Codex adversarial review #1 → 6 findings | — | reviewed |
| 2026-05-13 | Phase 5.1 done (multi-agent 3 slices) | `d09c989` + `c81ec5f` + `07a37e2` + tag `v0.5.1-fixes` | shipped |
| 2026-05-14 | Codex adversarial review #2 → 3 regressões | — | reviewed |
| 2026-05-14 | Phase 5.2 done inline (sync factory + shared OAuth secret + held lock) | `429d99e` + tag `v0.5.2-fixes` | shipped |
| 2026-05-14 | README rewrite com decision criteria (why/when/when-not) | `894eead` | shipped |
| 2026-05-14 | POC ceppem-agent integration | (não commitado; análise) | validated |
| 2026-05-14 | ROADMAP.md re-priorizado com 23 gaps tiered | `bca099e` | shipped |
| 2026-05-14 | Backend tenancy WIP encontrado (~25 files) | stash@{0} | WIP |
| (próximo) | Phase 6 — Multi-tenancy + RBAC + backup | TBD | starting |

---

## Tone notes pra próxima sessão

- User pediu trabalho em **português**. Manter.
- User valoriza **ação rápida + multi-agent paralelo**. Padrão validado 5x (Phases 1-5).
- User aceita **honestidade brutal** — análise de gaps em 23 items + tier 0 missing + "Wake não está pronto pra customer real" foi recebida bem.
- User **investiu pesado** em Wake (≈30h cobrindo Phases 0-5.2 + roadmap + POC ceppem). Está calibrando ROI vs continuar.
- User pediu **explicações comparativas** (Wake vs Managed Agents, Wake vs standalone ceppem) — respeitar pedido de comparação clara.
- **NÃO lançar Public Launch antes de Tier 0**. User concordou: primeiro customer descobre gaps e sai queimado.

---

*Last updated: 2026-05-14 14:55 — Phase 5.2 shipped + ROADMAP re-priorizado + Phase 6 (multi-tenancy) é o próximo. Backend tenancy parcialmente pronto no stash. `docs/FRONTEND-TENANCY.md` tem o playbook do frontend.*
