# Phase 6 Execution Contract — Multi-tenancy + RBAC + Backup

> Tier 0 gaps #1 (tenancy completion) + #2 (RBAC) + #3 (backup runbook).
> 3 agents Opus em paralelo, slices disjuntos, merge sequencial B → A → C.
>
> **Baseline:** commit `89bec12` (`v0.5.3-tenancy-backend`) entrega o backend tenancy primitives — headers, migration `0002`, `TenantContext`, scoped reads/writes, 3 isolation tests. Esta phase consome esse baseline e completa o trio Tier 0.

---

## Decisões locked (não rediscutir)

| Decisão | Valor | Justificativa |
|---|---|---|
| Tenant headers | `X-Wake-Organization-Id` + `X-Wake-Workspace-Id` | Já implementado (`get_tenant_context`); honrados em todas rotas autenticadas |
| Cross-workspace response | **404** (não 403) | Opacidade — não vaza existência entre tenants |
| Default tenant | `default/default` | Backward-compat single-tenant + dev mode |
| Empty header value | **400** | Rejeita string vazia (já implementado) |
| Workspace selector UI | **Topbar** (compact `org/ws` + dropdown) | Wake tem 2 níveis só (org → workspace); sidebar é caminho crítico pra navegação primária; padrão Vercel/Supabase/Datadog |
| Cache strategy no switch | `queryClient.clear()` no `useEffect` do workspaceId change | Zero risco de vazamento visual; loading state é aceitável em troca de contexto explícita |
| SSE tenant transport | **Query string** + regex `^[a-z0-9][a-z0-9_-]{0,62}$` sanitization | `EventSource` não aceita custom headers; cookie/session exige infra nova fora do escopo da Phase; backend re-valida tudo (fronteira real de segurança) |
| RBAC roles | `admin` / `operator` / `viewer` | Mínimo viável; mapeia bem pra dev/ops/observer; estende com custom roles em phase futura |
| Role admin | CRUD all + manage users | Único role que cria/altera users |
| Role operator | CRUD sessions + read agents/environments/metrics/vault metadata | Operação dia-a-dia sem privilégio destrutivo |
| Role viewer | Read-only (sessions, events, metrics) | SRE/observer sem write |
| RBAC enforcement | Per-route via FastAPI `Depends(require_role(...))` | Não inline-check em handlers; gate na assinatura da rota |
| RBAC enablement | `WAKE_RBAC_ENABLED=true` (env) | Off por default — back-compat zero-friction dev mode |
| Auth user surface | API key + (opcional) `X-Wake-User-Id` header | Phase 6 introduz user; OAuth user-login fica pra phase futura (gateway/IdP injeta header) |
| Backup tool | **pgbackrest** sidecar | Mais maduro que `pg_dump`-on-cron; incremental + full + restore-test built-in; usa S3-compatible storage |
| Backup schedule | Full semanal (Sun 02:00 UTC), incremental diário (02:00 UTC), retenção 30 dias | Configurável via `values.yaml` |
| Restore RTO target | **<30min** documentado + validado em CI smoke | Drill mensal automático |
| Restore RPO target | **<24h** (incremental diário) | Tradeoff aceito pra baseline; tighter via WAL archiving em phase futura |
| Backup storage | S3-compatible (AWS S3, MinIO, R2) — config via `values.yaml` | Sem assumir vendor; compose dev usa MinIO local |

---

## Pre-existing — não modificar

- `src/wake/tenancy.py`, `TenantContext`, `DEFAULT_*_ID` (commit `89bec12`)
- `get_tenant_context` dependency em `src/wake/api/dependencies.py`
- `verify_api_key` + canonical auth modes (Phase 5.1)
- Migration `0002_tenancy_columns` (`89bec12`)
- Stores: `AgentStore` / `EnvironmentStore` / `SessionStore` / `EventLog` Protocols — só ESTENDER (não muda shape de métodos existentes)
- `src/wake/types.py` campos `organization_id` / `workspace_id` em `Session` / `AgentConfig` / `Event` — adicionado pelo `89bec12`
- Specs `docs/SPEC-HARNESS-ADAPTER.md` / `docs/SPEC-EVENT-SCHEMA.md` — eventos já podem carregar `workspace_id`
- `adapters/*` — não tocar
- `phases/PHASE-*-CONTRACT.md` anteriores — histórico
- `pyproject.toml` raiz — exceto adições de deps opcionais por extras

### Endpoints existentes (auditados)

```
GET    /health
POST   /v1/agents            GET /v1/agents             GET /v1/agents/{id}      PATCH /v1/agents/{id}
POST   /v1/agents/{id}/archive  GET /v1/agents/{id}/versions
POST   /v1/environments      GET /v1/environments       GET /v1/environments/{id} archive  delete
POST   /v1/sessions          GET /v1/sessions           GET /v1/sessions/{id}    DELETE /v1/sessions/{id}
POST   /v1/sessions/{id}/interrupt  POST /v1/sessions/{id}/archive
POST   /v1/sessions/{id}/events     GET  /v1/sessions/{id}/events
GET    /v1/sessions/{id}/stream     (SSE)
GET    /v1/sessions/{id}/state-at/{seq}
GET    /v1/metrics/summary          GET /v1/workers
GET    /v1/vault/credentials        POST /v1/vault/oauth/start  GET /v1/vault/oauth/callback
POST   /v1/vault/credentials/{id}/rotate   POST /v1/vault/credentials/{id}/revoke
GET    /v1/vault/audit
```

Todas honram `X-Wake-Organization-Id` / `X-Wake-Workspace-Id` (commit `89bec12`).

### Endpoints que cada slice adiciona

- **A (rbac-backend)**: `POST/GET/PATCH /v1/users`, `GET /v1/users/me`, `POST /v1/users/{id}/roles`, `DELETE /v1/users/{id}/roles/{role}`
- **B (frontend)**: rota Next.js `GET /api/wake/sessions/[id]/stream` (proxy SSE com tenant injection) — **não é rota FastAPI**, é Next.js app route
- **C (ops)**: nenhuma rota nova

---

## Divisão de slices

| Agent | Worktree | Branch | Owns |
|---|---|---|---|
| `tenancy-rbac` | `wake-wt-tenancy-rbac` | `agent/tenancy-rbac` | RBAC layer (User + roles + per-user scoping) + Postgres upgrade/downgrade validation + cross-RBAC tests |
| `tenancy-frontend` | `wake-wt-tenancy-frontend` | `agent/tenancy-frontend` | 8 items do `docs/FRONTEND-TENANCY.md` + topbar selector + SSE proxy + multi-workspace tests |
| `tenancy-ops` | `wake-wt-tenancy-ops` | `agent/tenancy-ops` | pgbackrest no Helm + restore drill + `docs/DISASTER-RECOVERY.md` + `docs/RUNBOOK.md` |

Cada slice trabalha em subpastas disjuntas (verificadas na seção `Cross-cutting`).

---

## Files ownership

### `tenancy-rbac` owns

```
# Core RBAC
src/wake/rbac.py                                                 NEW   (User, Role enum, require_role factory)
src/wake/api/dependencies.py                                     UPDATE (get_current_user, require_role decorator)
src/wake/api/routes/users.py                                     NEW   (CRUD users + role assignment)
src/wake/api/app.py                                              UPDATE (include_router users)
src/wake/api/schemas.py                                          UPDATE (UserCreate, UserOut, RoleAssign)
src/wake/types.py                                                UPDATE (User type, Role enum, UserRole binding)

# Per-route role gates (UPDATE — additive Depends only; sem mudar shape)
src/wake/api/routes/agents.py                                    UPDATE (require_role(admin|operator) nas writes)
src/wake/api/routes/environments.py                              UPDATE (idem)
src/wake/api/routes/sessions.py                                  UPDATE (idem)
src/wake/api/routes/events.py                                    UPDATE (idem)
src/wake/api/routes/vault.py                                     UPDATE (admin-only writes; operator/viewer leem audit)
src/wake/api/routes/state.py                                     UPDATE (read role check)
src/wake/api/routes/metrics.py                                   UPDATE (read role check)

# Stores
src/wake/store/base.py                                           UPDATE (UserStore Protocol)
src/wake/store/sqlite.py                                         UPDATE (SQLite UserStore impl)
adapters/postgres-store/src/wake_store_postgres/users.py         NEW   (Postgres UserStore impl)
adapters/postgres-store/src/wake_store_postgres/models.py        UPDATE (UserRow + UserRoleRow tables)
adapters/postgres-store/alembic/versions/0003_rbac.py            NEW   (users + user_roles tables, indexes)

# Tests
tests/unit/test_rbac.py                                          NEW   (Role enum, require_role gate, header parsing)
tests/unit/test_api_users.py                                     NEW   (CRUD users + role assignment via API)
tests/unit/test_api_rbac_enforcement.py                          NEW   (admin vs operator vs viewer per-route matrix)
tests/unit/test_store.py                                         UPDATE (UserStore behavioral suite)
tests/unit/fakes.py                                              UPDATE (FakeUserStore)
adapters/postgres-store/tests/test_user_store.py                 NEW   (Postgres-backed UserStore tests; opt-in via PG_DSN)
adapters/postgres-store/tests/test_migrations.py                 NEW   (upgrade 0001→0002→0003 + downgrade trip back to 0001 + assert schema)

# Docs
docs/RBAC.md                                                     NEW   (roles, permissions matrix, enablement, header surface)
docs/ARCHITECTURE.md                                             UPDATE (add RBAC section)
```

### `tenancy-frontend` owns

```
# Tenant primitives
frontend/src/lib/tenant.ts                                       NEW   (getTenantScope, setTenantScope, useTenantScope hook)
frontend/src/lib/api/client.ts                                   UPDATE (inject X-Wake-Organization-Id + X-Wake-Workspace-Id)

# Generated types + manual types
frontend/src/lib/api/generated.ts                                UPDATE (regenerate via `pnpm openapi:generate`)
frontend/src/lib/api/types.ts                                    UPDATE (add organization_id/workspace_id to Session/AgentConfig/Event)
frontend/src/lib/replay/types.ts                                 UPDATE (event types carry workspace_id)

# Query keys (6 hooks)
frontend/src/hooks/useSessions.ts                                UPDATE (["sessions", workspaceId, filters])
frontend/src/hooks/useSession.ts                                 UPDATE
frontend/src/hooks/useEvents.ts                                  UPDATE
frontend/src/hooks/useStateAt.ts                                 UPDATE
frontend/src/hooks/useMetrics.ts                                 UPDATE
frontend/src/hooks/useWorkers.ts                                 UPDATE

# SSE proxy
frontend/src/lib/sse.ts                                          UPDATE (point at /api/wake/sessions/[id]/stream)
frontend/src/hooks/useSSE.ts                                     UPDATE (carry workspaceId)
frontend/src/app/api/wake/sessions/[id]/stream/route.ts          NEW   (Next.js SSE proxy; regex-sanitize org/ws query string; inject headers to backend; pipe stream)

# Workspace selector UI
frontend/src/components/layout/Topbar.tsx                        UPDATE (workspace dropdown component)
frontend/src/components/workspace/WorkspaceSelector.tsx          NEW   (Popover + radix dropdown)
frontend/src/components/workspace/WorkspaceSwitchDialog.tsx      NEW   (confirmation when switching mid-session view)
frontend/src/app/login/page.tsx                                  UPDATE (org_id + workspace_id inputs alongside API key)
frontend/src/app/providers.tsx                                   UPDATE (useEffect on workspaceId change → queryClient.clear() + router.push("/sessions"))

# OAuth tenant forwarding
frontend/src/app/oauth/callback/api/route.ts                     UPDATE (forward X-Wake-Organization-Id + X-Wake-Workspace-Id from query/cookie to backend)

# Tests
frontend/tests/unit/tenant.test.ts                               NEW   (getTenantScope fallback default/default; setter persists)
frontend/tests/unit/api-client.test.ts                           UPDATE (verify both tenant headers present)
frontend/tests/unit/workspace-selector.test.tsx                  NEW   (dropdown UI + switch flow)
frontend/tests/unit/sse-proxy.test.ts                            NEW   (mock Next.js route handler; regex rejects bad chars; passes good chars)
frontend/tests/fixtures/sessions.ts                              UPDATE (organization_id + workspace_id in all fixture rows)
frontend/tests/fixtures/events-fixture.json                      UPDATE (workspace_id in events)
frontend/tests/e2e/multi-workspace.spec.ts                       NEW   (mount 2 workspaces; switch; verify isolation)
frontend/tests/e2e/sessions-list.spec.ts                         UPDATE (workspace selector visible; switch clears table)
```

### `tenancy-ops` owns

```
# Helm — backup
deploy/helm/wake/templates/cronjob-backup.yaml                   NEW   (CronJob: pgbackrest full Sun 02:00, incremental daily 02:00)
deploy/helm/wake/templates/configmap-pgbackrest.yaml             NEW   (pgbackrest.conf templated from values)
deploy/helm/wake/templates/secret-backup-s3.yaml                 NEW   (S3 creds — only rendered se values.backup.s3.secretName não provido)
deploy/helm/wake/templates/serviceaccount-backup.yaml            NEW   (least-privilege SA for backup CronJob)
deploy/helm/wake/templates/job-restore.yaml                      NEW   (Helm hook post-install,upgrade `helm.sh/hook: test`; opt-in via values.backup.restoreTest.enabled)
deploy/helm/wake/values.yaml                                     UPDATE (backup: { enabled, schedule, retention.full, retention.incremental, s3: { endpoint, bucket, accessKeyId, secretAccessKey, secretName }, restoreTest: { enabled, schedule } })
deploy/helm/wake/values.schema.json                              UPDATE (backup section schema)
deploy/helm/wake/README.md                                       UPDATE (backup setup + restore drill section)

# Compose (dev)
deploy/docker-compose.yml                                        UPDATE (add minio service + pgbackrest sidecar — opt-in via profile=backup)
deploy/docker-compose.backup.yml                                 NEW   (separate compose override file for backup stack)

# Docs
docs/DISASTER-RECOVERY.md                                        NEW   (RTO/RPO, threat model, backup lifecycle, restore procedure step-by-step, drill log template, ≥600 lines)
docs/RUNBOOK.md                                                  NEW   (incident playbooks: 1. tenant data isolation breach, 2. backup restore from scratch, 3. RBAC bypass detection, 4. cross-workspace event leakage, ≥400 lines)

# Drill automation
scripts/restore-drill.sh                                         NEW   (CI script: spin throwaway Postgres → restore latest backup → verify row counts vs baseline → assert RTO<30min)
.github/workflows/restore-drill.yml                              NEW   (weekly cron + manual dispatch; uploads metrics artifact)
.github/workflows/helm-lint.yml                                  UPDATE (lint backup templates)
```

---

## Cross-cutting (cuidado!)

### `src/wake/api/app.py`

`include_router` calls — slice A adiciona `users.router`. Slices B e C **não tocam**. Conflito esperado zero.

### `src/wake/api/dependencies.py`

Slice A estende com `get_current_user` + `require_role`. Mantém `get_tenant_context` (do `89bec12`) intacto. Sem conflito com B/C (que não tocam).

### `src/wake/api/routes/*.py`

Slice A adiciona `Depends(require_role(...))` em rotas existentes. Não muda response shape. Slices B/C **não tocam** essas rotas.

### `deploy/helm/wake/values.yaml`

Slice C adiciona seção `backup:`. Slices A/B **não tocam** Helm.

### `frontend/src/app/providers.tsx`

Slice B atualiza. Outros não tocam.

### `docs/ARCHITECTURE.md`

Slice A adiciona seção "RBAC". Slice C provavelmente referencia mas só lê. Conflito potencial: orchestrator resolve no merge mantendo ambas as seções (RBAC + backup).

### `docs/RUNBOOK.md` (NEW)

Slice C cria. Slices A/B podem QUERER adicionar runbooks próprios — **não fazem nesta phase**. Se A descobrir necessidade de runbook RBAC bypass, deixa nota em comentário pra C absorver no merge final.

### `pyproject.toml`

Provavelmente sem mudança (Python stdlib + alembic já presentes). Se slice A precisar de `passlib` pra hash de senha (caso introduza user/password local — **NÃO** está no escopo, user é via header injetado), não introduzir.

---

## ACCEPTANCE CRITERIA por slice

### `tenancy-rbac` done quando:

- [ ] `WAKE_RBAC_ENABLED=true` ativa enforcement; off (default) preserva back-compat
- [ ] `Role` enum: `ADMIN`, `OPERATOR`, `VIEWER` com `Role.permits(action)` helper
- [ ] `require_role(*roles)` factory FastAPI dependency
- [ ] `get_current_user` lê `X-Wake-User-Id` header (quando RBAC ON); valida via `UserStore.get(id)`; 401 se ausente/inválido
- [ ] `UserStore` Protocol em `src/wake/store/base.py`: `create(user)`, `get(id)`, `list(workspace_id)`, `assign_role(user_id, role, workspace_id)`, `revoke_role(...)`, `roles_for(user_id, workspace_id)`
- [ ] SQLite + Postgres implementações
- [ ] Migration 0003 cria tables `users` + `user_roles` (workspace-scoped) + indexes
- [ ] Migration 0001→0002→0003 upgrade limpo; downgrade reverse trip também
- [ ] Routes:
  - `POST /v1/users` (admin only) — create user
  - `GET /v1/users` (admin only) — list users no workspace
  - `GET /v1/users/me` — caller's user + roles
  - `POST /v1/users/{id}/roles` (admin only) — assign role
  - `DELETE /v1/users/{id}/roles/{role}` (admin only) — revoke
  - `PATCH /v1/users/{id}` (admin only) — update display name
- [ ] Per-route enforcement:
  - `POST /v1/agents` → `require_role(ADMIN, OPERATOR)`
  - `PATCH /v1/agents/{id}` → `require_role(ADMIN, OPERATOR)`
  - `POST /v1/sessions` → `require_role(ADMIN, OPERATOR)`
  - `DELETE /v1/sessions/{id}` → `require_role(ADMIN, OPERATOR)`
  - `POST /v1/vault/credentials/{id}/rotate` → `require_role(ADMIN)`
  - `GET /v1/vault/audit` → `require_role(ADMIN, OPERATOR, VIEWER)`
  - reads (`GET /v1/sessions`, `/v1/events`, `/v1/metrics/*`) → `require_role(ADMIN, OPERATOR, VIEWER)`
- [ ] `test_rbac.py`: enum, factory, permission matrix
- [ ] `test_api_users.py`: CRUD users via API com admin
- [ ] `test_api_rbac_enforcement.py`: matriz `(role × route × method) → 200/403` — ≥18 cases
- [ ] `test_api_tenancy.py` (existente) continua passando
- [ ] `test_migrations.py`: upgrade head + downgrade base + assert column existence
- [ ] `pytest tests/unit/ adapters/postgres-store/tests/ -q` clean
- [ ] `ruff` + `mypy --strict` clean nas adições
- [ ] `docs/RBAC.md` ≥300 linhas: motivação, role matrix, header surface, enablement flag, OAuth proxy guidance, role-customization escape hatch

### `tenancy-frontend` done quando:

- [ ] `getTenantScope()` retorna `{organizationId, workspaceId}` lendo de `localStorage` com fallback `default/default`
- [ ] `WakeApiClient.headers()` injeta `X-Wake-Organization-Id` + `X-Wake-Workspace-Id` em toda request autenticada
- [ ] `frontend/src/lib/api/generated.ts` regenerado contém `organization_id` / `workspace_id` em `Session`, `AgentConfig`, `Event`
- [ ] Manual types (`types.ts`, `replay/types.ts`) expõem campos
- [ ] Fixtures (`sessions.ts`, `events-fixture.json`) incluem tenant fields
- [ ] Query keys de 6 hooks têm `workspaceId` como 2º elemento
- [ ] Trocar workspace dispara `queryClient.clear()` + router push `/sessions`
- [ ] SSE proxy `/api/wake/sessions/[id]/stream`:
  - Aceita query params `org` + `ws`
  - Regex sanitiza: `^[a-z0-9][a-z0-9_-]{0,62}$` — 400 se inválido
  - Injeta headers no backend Wake fetch
  - Pipe streaming response (Server-Sent Events Content-Type)
  - Encerra graciosamente em client disconnect
- [ ] `EventSource` aponta pra rota Next.js (não backend direto)
- [ ] Topbar mostra workspace atual em formato `org / ws`; click abre dropdown com lista (mock por agora se backend ainda não expõe `/v1/workspaces`)
- [ ] Login page tem inputs `organization_id` + `workspace_id` (defaults `default`/`default`)
- [ ] OAuth callback route encaminha tenant pro backend
- [ ] Tests Vitest: tenant, api-client, workspace-selector, sse-proxy
- [ ] Tests Playwright: `multi-workspace.spec.ts` mount 2 workspaces, switch, assert tabela muda + URL preservada
- [ ] `pnpm vitest run` + `pnpm test:e2e` verdes
- [ ] `pnpm typecheck` strict — sem `any`
- [ ] `pnpm build` clean, bundle delta <50KB

### `tenancy-ops` done quando:

- [ ] `cronjob-backup.yaml` renderiza CronJob com pgbackrest full Sun 02:00 + incremental daily 02:00 (ambos configuráveis via values)
- [ ] `configmap-pgbackrest.yaml` templated com S3 endpoint/bucket
- [ ] Secret S3 ou rendered (se inline) ou referenced (se externo via `secretName`)
- [ ] `job-restore.yaml` opcional via `values.backup.restoreTest.enabled=true`
- [ ] `helm lint deploy/helm/wake` clean
- [ ] `helm template deploy/helm/wake --set backup.enabled=true --set backup.s3.bucket=test --set backup.s3.accessKeyId=k --set backup.s3.secretAccessKey=s` produz YAML válido
- [ ] `helm template ... --set backup.enabled=false` NÃO renderiza nenhum recurso de backup
- [ ] `docker-compose.backup.yml` sobe MinIO + pgbackrest local pra dev/teste
- [ ] `scripts/restore-drill.sh`:
  - Provisiona Postgres throwaway (container)
  - Restaura último backup
  - Conta linhas em `sessions`, `events`, `agents`, `environments`, `users`
  - Compara com baseline esperado (env var ou file)
  - Exit 0 se contagens > 0 e schema consistente
  - Exit 1 se RTO > 30min
- [ ] `.github/workflows/restore-drill.yml` weekly cron + manual dispatch
- [ ] `docs/DISASTER-RECOVERY.md` ≥600 linhas: RTO/RPO definidos, threat model, lifecycle (backup → archive → restore → verify), procedure step-by-step com comandos exatos, drill log template, troubleshooting
- [ ] `docs/RUNBOOK.md` ≥400 linhas com 4 playbooks (tenant breach, restore, RBAC bypass, event leakage)
- [ ] `deploy/helm/wake/README.md` atualizado com seção backup

**Quality (todos):**
- [ ] TypeScript strict, ruff, mypy strict (onde houver Python adicional) clean
- [ ] Commit prefixes: `api:`, `rbac:`, `frontend:`, `deploy:`, `docs:`, `ops:`
- [ ] Sem real OAuth providers em testes — MSW + httpx_mock
- [ ] Sem real Postgres em testes default — `PG_DSN` env enable opt-in suite
- [ ] Worktree disciplina — cada slice **EXCLUSIVAMENTE** em `wake-wt-tenancy-<slice>`

---

## ENTRY POINTS

Backend FastAPI: `src/wake/api/app.py` (`app = FastAPI()`). Novos routers via `app.include_router(...)`.

Frontend: Next.js 15 App Router em `frontend/`. Nova rota Next.js em `frontend/src/app/api/wake/sessions/[id]/stream/route.ts`.

Deploy: Helm chart em `deploy/helm/wake/`. Backup adiciona templates novos + values.

---

## SHARED DECISIONS

### Versioning

- Backend permanece `wake-ai 0.0.1` (bump pra `0.6.0` no merge final, orchestrator)
- Frontend `package.json` → `0.6.0`
- Tag final: `v0.6.0-tenancy` após todos os merges

### Auth contract (com RBAC ligado)

```
X-Wake-API-Key: <key>                 # exists since Phase 5.1
X-Wake-Organization-Id: <org>         # exists since 89bec12
X-Wake-Workspace-Id: <workspace>      # exists since 89bec12
X-Wake-User-Id: <user_id>             # NEW (slice A) — only checked when WAKE_RBAC_ENABLED=true
```

`WAKE_RBAC_ENABLED=false` (default) → `get_current_user` retorna `User.system()` sem checar header — back-compat puro.

### Backup contract

`values.yaml` (default):
```yaml
backup:
  enabled: false
  schedule:
    full: "0 2 * * 0"
    incremental: "0 2 * * 1-6"
  retention:
    full: 4
    incremental: 30
  s3:
    endpoint: ""
    bucket: ""
    region: "us-east-1"
    secretName: ""
  restoreTest:
    enabled: false
    schedule: "0 4 * * 0"
```

---

## MERGE ORDER

1. **`tenancy-frontend`** → main
   - Conflito esperado: zero (paths disjuntos vs A/C)
   - Pós-merge: `pnpm install --frozen-lockfile && pnpm build && pnpm vitest run`

2. **`tenancy-rbac`** → main
   - Conflito esperado: zero (paths disjuntos vs B/C, exceto `docs/ARCHITECTURE.md` que B não toca)
   - Pós-merge: `pytest tests/unit/ adapters/postgres-store/tests/ -q`
   - Integration: garantir que frontend continua passando com `WAKE_RBAC_ENABLED=false`

3. **`tenancy-ops`** → main
   - Conflito esperado: `docs/ARCHITECTURE.md` (se A adicionou seção; C lê e referencia) — resolve mantendo ambas seções
   - Pós-merge: `helm lint deploy/helm/wake` + `helm template` matriz de 3 valores

Após cada merge: `git tag` interno opcional (`v0.6.0-rc1`, `rc2`, `rc3`); tag final `v0.6.0-tenancy` no último.

---

## CONVENÇÕES

- TypeScript strict, ESLint, Prettier — `pnpm lint`, `pnpm typecheck`, `pnpm format`
- Python 3.11+, ruff, mypy strict — adições Python
- Commit prefixes: `api:`, `rbac:`, `frontend:`, `deploy:`, `docs:`, `ops:`
- Cada slice **EXCLUSIVAMENTE no seu worktree** (`wake-wt-tenancy-*`)
- Sem real OAuth/IdP em testes — MSW + httpx_mock
- Sem real S3 em testes — MinIO container ou mock via `aioboto3` stub
- Sem real Postgres em tests defaults — `PG_DSN` env enable opt-in suite
- `pnpm` (NÃO npm/yarn)
- Nunca expor tokens, senhas, ou S3 keys em events/logs

---

## DELIVERABLES por agent (resumo)

| Slice | Backend | Frontend | Deploy | Docs |
|---|---|---|---|---|
| tenancy-rbac | User entity + RBAC + per-route gates + migration 0003 + tests | — | — | `docs/RBAC.md` |
| tenancy-frontend | — | tenant headers + 6 hook keys + topbar selector + SSE proxy + tests | — | — |
| tenancy-ops | — | — | pgbackrest CronJob + restore drill + Helm values + compose backup | `docs/DISASTER-RECOVERY.md` + `docs/RUNBOOK.md` |

---

## REGRA DE OURO

1. **Leia este contrato + `docs/FRONTEND-TENANCY.md` (slice B) + `phases/PHASE-5-CONTRACT.md` (modelo) + commit `89bec12` (baseline) ANTES de codar.**
2. **Backend additions são ADDITIVE — não muda shape de rotas existentes; só adiciona `Depends(require_role(...))` quando RBAC ligado.**
3. **`WAKE_RBAC_ENABLED=false` é o default — feature flag duro pra back-compat zero-friction.**
4. **Cross-workspace → 404. Cross-RBAC sem permissão → 403. Auth fail → 401.**
5. **OpenAPI codegen é a fonte de verdade pros tipos do frontend — após mudar backend, regenerar.**
6. **Tokens / passwords / S3 keys NUNCA expostos via API/logs/events.**
7. **Commit no SEU worktree** (`wake-wt-tenancy-<slice>/`), branch `agent/tenancy-<slice>`.
8. **Quando terminar**: reporte tests (pytest + vitest + playwright), arquivos fora do slice tocados (deve ser zero), helm lint/template output.
9. **Estimativa**: 120-180min wall-clock por slice.
10. **NÃO PUSH. NÃO MERGE.** Orchestrator faz.
