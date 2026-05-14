# Phase 6 — Multi-tenancy + RBAC + Backup

> **Objetivo:** fechar os 3 Tier 0 gaps do roadmap pós-adversarial review. Wake passa a ter isolamento operacional first-class (`workspace_id`), modelo de permissão verificável (RBAC), e procedimento de recuperação de desastre testado. Sem isso, lançar é entregar um substrato com superfícies de incidente conhecidas e não-cobertas.

| | |
|---|---|
| **Status** | ⚪ in_progress (backend tenancy baseline shipped em `89bec12`) |
| **Duração estimada** | 3-4 semanas (~3-6h multi-agent wall-clock + integração) |
| **Dependências** | Phase 5 done (Dashboard) + Phase 5.1 / 5.2 (adversarial fixes) |
| **Baseline** | `v0.5.3-tenancy-backend` — backend tenancy primitives + 3 isolation tests |
| **Tier resolved** | Tier 0 #1 (tenancy completion) + #2 (RBAC) + #3 (backup runbook) |

---

## Por que essa fase existe

O roadmap re-priorizado (2026-05-14, `docs/ROADMAP.md`) identificou 23 gaps cross-cutting, classificados em Tiers 0–5. **Tier 0 são bloqueadores de produção** — não dá pra ter um primeiro customer real sem eles. São 3:

1. **Tenancy** — `default/default` em prod é footgun: um operator desliga o gateway IdP por 5min e tudo cai numa origem comum. Wake precisa rejeitar headers vazios (✅ `89bec12`), filtrar reads por workspace (✅), retornar 404 cross-workspace (✅ — opacidade), e ter UI que reflita o scope (⏳ slice B).
2. **RBAC** — hoje todo holder de API key vira admin de tudo. Não dá pra dar API key pra um SRE só pra ler métricas sem ele também poder destruir vault. Roles `admin`/`operator`/`viewer` resolvem o caso 80/20.
3. **Backup runbook** — Postgres em Helm sem backup é Russian roulette. `pgbackrest` resolve com 1 CronJob + 1 secret S3. A doc precisa virar runbook real com drill mensal automático.

Sem essa phase, o Public Launch (Phase 10) seria um lançamento que queima o primeiro customer.

---

## Entry criteria

- ✅ Phase 5 done (`v0.5.2-fixes`) — dashboard Next.js 15 com sessions/replay/metrics/vault
- ✅ Phase 5.1 / 5.2 — auth canônico + sync factory + shared OAuth secret + held lock
- ✅ Baseline tenancy backend shipped (`89bec12` + `v0.5.3-tenancy-backend`)
- ✅ 3 isolation tests passing em `tests/unit/test_api_tenancy.py`

---

## Exit criteria (gates)

### Backend RBAC

- [ ] `Role` enum (`ADMIN`/`OPERATOR`/`VIEWER`) com permission matrix
- [ ] `require_role(*roles)` factory FastAPI dependency
- [ ] `UserStore` Protocol + SQLite + Postgres impls
- [ ] Migration `0003_rbac` cria `users` + `user_roles` workspace-scoped
- [ ] Endpoints `/v1/users` (CRUD + me + role assign/revoke)
- [ ] Per-route enforcement em todas rotas write
- [ ] `WAKE_RBAC_ENABLED=false` (default) preserva back-compat
- [ ] `test_api_rbac_enforcement.py` cobre matriz `(role × route × method)`
- [ ] `docs/RBAC.md` ≥300 linhas

### Frontend tenancy

- [ ] `getTenantScope()` + `WakeApiClient` injeta tenant headers
- [ ] Tipos gerados e manuais carregam `organization_id`/`workspace_id`
- [ ] 6 hooks com `workspaceId` em `queryKey`
- [ ] Topbar workspace selector + login page inputs
- [ ] Switch dispara `queryClient.clear()` + redirect `/sessions`
- [ ] SSE proxy Next.js `/api/wake/sessions/[id]/stream` com regex sanitization
- [ ] OAuth callback encaminha tenant
- [ ] e2e `multi-workspace.spec.ts` mount 2 workspaces + switch + isolation
- [ ] `pnpm typecheck` + `vitest` + `playwright` verdes

### Backup ops

- [ ] `pgbackrest` CronJob no Helm (full semanal + incremental diário)
- [ ] S3-compatible storage config via `values.yaml`
- [ ] Restore drill script automatizado (`scripts/restore-drill.sh`)
- [ ] GitHub Actions weekly cron executa drill + uploads metrics
- [ ] `helm lint` + `helm template` em 3 cenários (off/full/full+drill) clean
- [ ] `docs/DISASTER-RECOVERY.md` ≥600 linhas com RTO<30min target documentado
- [ ] `docs/RUNBOOK.md` ≥400 linhas com 4 incident playbooks
- [ ] Compose dev sobe MinIO + pgbackrest local via `--profile backup`

### Quality

- [ ] Ruff + mypy strict clean
- [ ] TypeScript strict, sem `any`
- [ ] Sem regressão nas suites existentes (claude-sdk, conformance, langgraph, sandbox, vault, litellm)
- [ ] Tag `v0.6.0-tenancy` após merge final

---

## Deliverables

### Estrutura nova

```
src/wake/
├── rbac.py                                        NEW
├── api/routes/users.py                            NEW
└── api/dependencies.py                            UPDATE

adapters/postgres-store/
├── alembic/versions/0003_rbac.py                  NEW
├── src/wake_store_postgres/users.py               NEW
└── tests/test_migrations.py                       NEW

frontend/src/
├── lib/tenant.ts                                  NEW
├── app/api/wake/sessions/[id]/stream/route.ts     NEW
├── components/workspace/                          NEW (selector + switch dialog)
└── (updates to 6 hooks + Topbar + providers + sse + client)

deploy/helm/wake/templates/
├── cronjob-backup.yaml                            NEW
├── configmap-pgbackrest.yaml                      NEW
├── secret-backup-s3.yaml                          NEW
├── serviceaccount-backup.yaml                     NEW
└── job-restore.yaml                               NEW

scripts/restore-drill.sh                           NEW
.github/workflows/restore-drill.yml                NEW

docs/RBAC.md                                       NEW
docs/DISASTER-RECOVERY.md                          NEW
docs/RUNBOOK.md                                    NEW
```

### API contract (backend additions)

```
POST   /v1/users                  (admin)     — create user
GET    /v1/users                  (admin)     — list users in workspace
GET    /v1/users/me                           — current caller user + roles
PATCH  /v1/users/{id}             (admin)     — update display name
POST   /v1/users/{id}/roles       (admin)     — assign role
DELETE /v1/users/{id}/roles/{role} (admin)    — revoke role
```

Todas existentes (sessions, events, vault, etc.) **ganham `Depends(require_role(...))`** quando `WAKE_RBAC_ENABLED=true`. Shape inalterado.

---

## Tasks resumidas

Ver `phases/PHASE-6-CONTRACT.md` pra ownership detalhado por slice.

### Slice A — `tenancy-rbac` (backend, ~150min)
RBAC layer + User CRUD + per-route gates + Postgres migration 0003 + tests + docs/RBAC.md.

### Slice B — `tenancy-frontend` (frontend, ~150min)
Tenant headers + 6 hooks com workspaceId + topbar selector + SSE proxy + multi-workspace e2e.

### Slice C — `tenancy-ops` (deploy + docs, ~120min)
pgbackrest CronJob + restore drill + DISASTER-RECOVERY.md + RUNBOOK.md.

---

## Reusable components (não reinventar)

| Item | Source | License | Uso |
|---|---|---|---|
| Backup engine | [pgbackrest](https://pgbackrest.org/) | MIT | full/incremental, retention, restore-test built-in |
| S3-compatible client (Helm) | pgbackrest nativo (libcurl) | — | sem extra dep |
| S3-compatible storage (dev) | [MinIO](https://min.io/) | AGPLv3 (client Apache 2) | container dev/teste |
| FastAPI deps | já em uso | — | `Depends(require_role(...))` é só callable factory |
| Radix Popover (frontend) | `@radix-ui/react-popover` (já instalado via shadcn) | MIT | workspace selector |
| TanStack Query `clear()` (frontend) | já em uso | — | API existente |

### Anti-reuso

- ❌ Cookie-based session pro SSE — complexidade desnecessária; query string + backend re-valida resolve. Revisitar em Phase 7 se ops hardening trouxer server-session.
- ❌ Casbin / opa pra RBAC — Wake tem 3 roles fixas + small permission matrix; um Enum + factory é suficiente. Estender para policy DSL quando matrix crescer.
- ❌ `pg_dump` em cron — funciona pra dev, mas perde incremental, retention policy declarativa e restore-verification automática. pgbackrest é o padrão maduro.
- ❌ Backup app-level (dump dos events table só) — perde estado do Vault Infisical (`adapters/vault-infisical/data`), perde Helm secrets sync. Postgres-level garante consistência cross-table.

---

## Risks e mitigações

### R6.1 — RBAC feature flag esquecida em prod
**Prob:** baixa · **Imp:** alto
- Default `WAKE_RBAC_ENABLED=false` pra back-compat zero-friction
- Helm `values.yaml` documenta a flag com aviso big-bold pra ligar em prod
- Adicionar `auth.rbacEnabled` no Helm `values.schema.json` pra validar

### R6.2 — Migration 0003 falha em Postgres com data existente
**Prob:** média · **Imp:** alto
- Migration usa `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ADD COLUMN IF NOT EXISTS` (idempotente)
- Tests `test_migrations.py` cobrem upgrade 0001→0002→0003 + downgrade reverse trip
- Drill em DB com data realista antes de mergear

### R6.3 — `queryClient.clear()` no switch perde estado de UI legítimo
**Prob:** média · **Imp:** baixo
- Switch é ação explícita do usuário (não automática) — loading state é UX aceitável
- Documentar comportamento em tooltip do selector

### R6.4 — SSE proxy Next.js vira gargalo / single point of failure
**Prob:** média · **Imp:** médio
- Rota Next.js só pipe stream, não buffer — sem allocação proporcional ao volume de eventos
- Documentar limite de conexões simultâneas em Next.js standalone (~50 por instance default)
- Em produção multi-replica frontend, load balancer já distribui

### R6.5 — Backup S3 keys vazam via Helm secret manifests
**Prob:** baixa · **Imp:** alto
- `secret-backup-s3.yaml` só rendered se inline mode (sem `secretName`)
- Documentar best practice: usar `secretName` apontando pra Secret pre-criada com `kubectl create secret`
- Helm `--show-only` review obrigatório antes de install em prod

### R6.6 — Restore drill quebra inadvertidamente em production-like DB
**Prob:** baixa · **Imp:** alto
- `scripts/restore-drill.sh` SEMPRE restaura em container throwaway (não toca prod)
- Marca container com label `restore-drill=true` pra audit
- Drill workflow GitHub Actions só rode em runner cloud, nunca self-hosted apontando pra prod

### R6.7 — Per-route `require_role` esquecido em rota nova
**Prob:** alta (humano) · **Imp:** médio
- Test `test_api_rbac_enforcement.py` enumera rotas via `app.routes` e assert que cada rota write tem `require_role` no dependency tree
- Falha de CI se rota nova for adicionada sem role gate
- Linter/CI verifica padrão de decoração antes de mergear

---

## Decisões adiadas

- ❌ OAuth user-login real (Auth0/Clerk/IdP) — gateway externo injeta `X-Wake-User-Id`. Wake não é IdP.
- ❌ Custom roles além das 3 fixas — escape hatch via policy-DSL em phase futura
- ❌ Row-level security Postgres direto (em vez de filter na query) — adiciona complexidade pra ganho limitado quando reads já filtram via store layer
- ❌ Backup encryption-at-rest gerenciado pelo Wake — delega pra S3 SSE-KMS / cliente S3 KMS — config-only no Wake
- ❌ Cross-region backup replication automática — fica pra Phase 7 (ops hardening tier)
- ❌ Workspace deletion cascata — fica pra Phase 8 (retention tier)
- ❌ Audit log de RBAC changes — `vault_audit` existing pattern pode ser estendido; nesta phase só log inline em `events`

---

## Definition of Done

- [ ] Todos Exit Criteria checados
- [ ] Tag `v0.6.0-tenancy` criada (após merge final)
- [ ] Lighthouse `/sessions` Performance ≥85, Accessibility ≥90 (sem regressão Phase 5)
- [ ] `pytest` + `pnpm vitest` + `pnpm test:e2e` clean
- [ ] `helm lint deploy/helm/wake` clean
- [ ] `helm template ... --set backup.enabled=true --set rbac.enabled=true` produz YAML válido
- [ ] `docs/ROADMAP.md` updated: Tier 0 #1+#2+#3 marcados como done
- [ ] `phases/README.md` updated: Phase 6 status → `✅ done`
- [ ] `CONTEXT.md` updated com novo estado + next phase pointer

---

## Métricas de sucesso

| Métrica | Mínimo | Meta |
|---|---|---|
| RBAC enforcement test matrix coverage | ≥15 cases | ≥25 cases |
| Frontend tenancy isolation e2e | 1 workspace switch | 3 workspaces matrix |
| Restore RTO (drill) | <30min | <15min |
| Backup retention configurabilidade | full + incremental | full + incremental + PITR (Phase 7) |
| Tests novos | ≥30 | ≥50 |
| Docs novas (linhas combinadas) | ≥1000 | ≥1500 |
| Helm template scenarios validados | 3 (off/full/full+drill) | 5 |

---

## After this phase

→ [Phase 7](./README.md) — Operational Hardening (idempotency, retention, rate limit, cost budget, Prometheus full surface). Backup vai ser estendido com PITR + cross-region. RBAC vai ser estendido com audit log + custom roles policy.

---

## Multi-agent slicing

Padrão validado 5x (Phases 1–5). 3 agents paralelos:

| Slice | Worktree | Owns |
|---|---|---|
| `tenancy-rbac` | `wake-wt-tenancy-rbac` | RBAC layer + User CRUD + per-route gates + migration 0003 + tests |
| `tenancy-frontend` | `wake-wt-tenancy-frontend` | 8 items FRONTEND-TENANCY.md + topbar + SSE proxy + e2e |
| `tenancy-ops` | `wake-wt-tenancy-ops` | pgbackrest no Helm + restore drill + DISASTER-RECOVERY.md + RUNBOOK.md |

Cada slice ~120-180min wall-clock.

Pre-existing não modificar:
- `src/wake/tenancy.py`, `get_tenant_context`, migration 0002 (baseline `89bec12`)
- Specs (`SPEC-EVENT-SCHEMA.md` / `SPEC-HARNESS-ADAPTER.md`)
- `adapters/*` exceto `postgres-store` (slice A adiciona migration + user store)
- `phases/PHASE-*-CONTRACT.md` anteriores

---

## Open questions (já fechadas)

Resolvidas via ultrathink antes de despachar:

1. ~~Workspace selector — topbar ou sidebar?~~ → **Topbar** (Wake só tem 2 níveis; sidebar é caminho crítico de navegação primária).
2. ~~Switch invalida queries ou clear()?~~ → **`queryClient.clear()`** (zero risco de vazamento visual; loading aceitável em troca explícita).
3. ~~SSE tenant via query string ou cookie/session?~~ → **Query string + regex sanitize** (backend é a fronteira de segurança real; cookie exige infra fora de escopo).
4. ~~RBAC roles fixas ou policy DSL?~~ → **3 roles fixas** (mínimo viável; policy DSL é escape hatch pra Phase 8+).
5. ~~Backup tool: pg_dump cron ou pgbackrest?~~ → **pgbackrest** (full+incremental+retention+restore-test built-in).
6. ~~Restore drill: manual ou CI?~~ → **CI weekly + manual dispatch** (drill que ninguém roda não é drill).
7. ~~RBAC default: on ou off?~~ → **Off** (`WAKE_RBAC_ENABLED=false` por default — back-compat zero-friction).

Sem perguntas pendentes — agents podem começar imediatamente.
