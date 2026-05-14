# Phase 7 Execution Contract — Operational Hardening

> Tier 1 gaps (#4–#8): idempotency · retention · rate-limit · cost-budget · Prometheus.
> 3 agents Opus em paralelo, slices disjuntos, merge sequencial A → B → C.
>
> **Baseline:** tag `v0.6.0-tenancy` (Phase 6 done). Backend tenancy + RBAC + backup operacionais.

---

## Decisões locked (não rediscutir)

| Decisão | Valor | Justificativa |
|---|---|---|
| Rate-limit lib | **`slowapi`** + storage backend pluggable | Maduro, FastAPI-native, sliding window, Redis backend opcional |
| Rate-limit storage default | **in-memory** (`SimpleMemoryBackend`) | Single-process funciona; Redis opt-in via `WAKE_RATELIMIT_REDIS_URL` |
| Rate-limit shape | Per-API-key + per-tenant (workspace) + per-route override | Cobre 80/20 dos cenários abusivos |
| Default limits | 100 req/min per workspace · 1000 req/min per org · configurável via `values.yaml` | Razoável pra dev/POC; produção tunes per-customer |
| Idempotency key | `event.metadata.idempotency_key` (opcional) + UNIQUE `(workspace_id, session_id, idempotency_key)` partial index | Per-session scope evita colisões cross-session; partial index porque NOT NULL é opcional |
| Idempotency window | **Indefinida** (UNIQUE forever; TTL via retention) | Mantém append-only sem state machine de expiração |
| Cost budget | `agent.metadata.max_cost_usd` (Decimal opcional) | Reuses metadata field; sem schema change |
| Cost enforcement | Per-session check **após** cada evento com `metadata.cost_usd`; excedeu → `session.interrupt(reason="cost_budget_exceeded")` | Reactive, não preditivo — preditivo exige model pricing table |
| Worker backpressure | Header `X-Wake-Worker-Saturation` (0.0–1.0) returned em response normal; `503` + `Retry-After` quando queue depth > threshold | Cliente decide retry; sem retry loop server-side |
| Retention | TTL per-table via env (events: 90d, sessions: 365d, archive antes de delete) | Conservador; tightenable per-customer |
| Archive | `wake events archive --before=<date> --bucket=<s3>` CLI command + opcional CronJob | Cold storage em S3 (já existe pra backup) |
| Compact | `wake events compact --session=<id>` — coalesce `assistant.delta` events em snapshot único | Replay continua funcional via reconstruction |
| Prometheus | `/metrics` exposition (separado de `/v1/metrics/summary` JSON) via `prometheus-fastapi-instrumentator` | Padrão Prom — counters, histograms, gauges |
| ServiceMonitor | Helm template, opt-in via `monitoring.enabled` | kube-prometheus-stack-compatible |
| Load test | **k6** (postgres-store já tem; estender pra full API) + published `docs/BENCHMARKS.md` | Cobertura mínima 1000 concurrent sessions |

---

## Pre-existing — não modificar

- `src/wake/tenancy.py`, `src/wake/rbac.py`, `get_tenant_context`, `get_current_user`, `require_role` (Phase 6 baseline)
- Stores Protocols — só ESTENDER (não muda shape de métodos existentes)
- `src/wake/types.py` — `Event.metadata` já existe como `dict[str, Any]` — idempotency_key vive aí (sem schema change)
- Specs `SPEC-EVENT-SCHEMA.md` — `metadata.idempotency_key` é addition compatível
- `adapters/*` (exceto `postgres-store` que ganha migration 0004)
- `phases/PHASE-*-CONTRACT.md` anteriores

---

## Divisão de slices

| Agent | Worktree | Branch | Owns |
|---|---|---|---|
| `ops-throughput` | `wake-wt-ops-throughput` | `agent/ops-throughput` | rate-limit middleware + idempotency_key + worker backpressure |
| `ops-cost-retention` | `wake-wt-ops-cost-retention` | `agent/ops-cost-retention` | max_cost_usd enforcement + retention TTL + compact + archive CLI |
| `ops-metrics-benchmark` | `wake-wt-ops-metrics-benchmark` | `agent/ops-metrics-benchmark` | `/metrics` Prometheus + ServiceMonitor + k6 load test + BENCHMARKS.md |

---

## Files ownership

### `ops-throughput` owns

```
# Rate limit
src/wake/api/ratelimit.py                                        NEW   (slowapi setup + key extractor + storage backend selector)
src/wake/api/app.py                                              UPDATE (mount Limiter, custom exceptions handler 429)
src/wake/api/dependencies.py                                     UPDATE (rate_limit dependency, exposes Limiter)
pyproject.toml                                                   UPDATE (add slowapi + redis[hiredis] optional extras)

# Per-route limits
src/wake/api/routes/{agents,sessions,events,vault,users}.py      UPDATE (Depends(rate_limit(per_workspace=...)))

# Idempotency
src/wake/core/event_log.py                                       UPDATE (idempotency_key honored in append; ON CONFLICT DO NOTHING + return existing)
src/wake/store/base.py                                           UPDATE (EventStore.append signature accepts idempotency_key kwarg)
src/wake/store/sqlite.py                                         UPDATE (UNIQUE partial index + ON CONFLICT logic)
adapters/postgres-store/src/wake_store_postgres/events.py        UPDATE (Postgres equivalent + ON CONFLICT)
adapters/postgres-store/alembic/versions/0004_idempotency.py     NEW   (CREATE UNIQUE INDEX ... WHERE idempotency_key IS NOT NULL)

# Worker backpressure
src/wake/runtime/dispatcher.py                                   UPDATE (queue depth gauge + saturation calc)
src/wake/api/middleware/backpressure.py                          NEW   (response header injector + 503 trigger)
src/wake/api/app.py                                              UPDATE (mount backpressure middleware)

# Tests
tests/unit/test_ratelimit.py                                     NEW
tests/unit/test_idempotency.py                                   NEW
tests/unit/test_backpressure.py                                  NEW
adapters/postgres-store/tests/test_idempotency.py                NEW
tests/unit/fakes.py                                              UPDATE (FakeRateLimitStorage)

# Docs
docs/OPERATIONS.md                                               NEW (rate-limit + idempotency + backpressure setup)
```

### `ops-cost-retention` owns

```
# Cost budget
src/wake/runtime/cost_budget.py                                  NEW   (CostBudgetEnforcer reading agent.metadata.max_cost_usd)
src/wake/runtime/dispatcher.py                                   UPDATE (post-step cost check + interrupt trigger)
src/wake/core/session.py                                         UPDATE (interrupt reason = "cost_budget_exceeded" allowed)

# Retention
src/wake/cli/retention.py                                        NEW   (wake events compact + wake events archive commands)
src/wake/store/base.py                                           UPDATE (compact + archive helpers)
src/wake/store/sqlite.py                                         UPDATE (impl)
adapters/postgres-store/src/wake_store_postgres/events.py        UPDATE (impl + delete in batches)
adapters/postgres-store/alembic/versions/0005_retention.py       NEW   (archive_log table for audit of archived events)

# Helm — retention CronJob
deploy/helm/wake/templates/cronjob-retention.yaml                NEW   (opt-in via values.retention.enabled)
deploy/helm/wake/values.yaml                                     UPDATE (retention: { enabled, events_ttl_days, sessions_ttl_days, s3_archive: {bucket, region} })
deploy/helm/wake/values.schema.json                              UPDATE

# Tests
tests/unit/test_cost_budget.py                                   NEW
tests/unit/test_retention.py                                     NEW
tests/unit/test_compact.py                                       NEW
adapters/postgres-store/tests/test_retention.py                  NEW (opt-in PG)

# Docs
docs/COST-BUDGET.md                                              NEW
docs/RETENTION.md                                                NEW (compact + archive + restore from archive)
```

### `ops-metrics-benchmark` owns

```
# Prometheus
src/wake/api/metrics_prom.py                                     NEW   (prometheus-fastapi-instrumentator setup)
src/wake/api/app.py                                              UPDATE (mount instrumentator + /metrics endpoint)
pyproject.toml                                                   UPDATE (prometheus-fastapi-instrumentator)

# Custom metrics
src/wake/observability/metrics.py                                NEW   (counters/histograms for sessions, events, costs, errors)
src/wake/runtime/dispatcher.py                                   UPDATE (emit metric on step)

# Helm — ServiceMonitor
deploy/helm/wake/templates/servicemonitor.yaml                   NEW   (opt-in via monitoring.enabled)
deploy/helm/wake/values.yaml                                     UPDATE (monitoring: { enabled, labels })
deploy/helm/wake/values.schema.json                              UPDATE

# Benchmarks (k6)
tests/load/k6/wake-api.js                                        NEW   (1000 concurrent sessions scenario)
tests/load/k6/session-create.js                                  NEW
tests/load/k6/event-append.js                                    NEW
tests/load/README.md                                             NEW

# Tests
tests/unit/test_metrics_prom.py                                  NEW

# Docs
docs/BENCHMARKS.md                                               NEW (p50/p95/p99 + throughput results published)
docs/OBSERVABILITY.md                                            NEW (Prometheus + ServiceMonitor + dashboards Grafana JSON)
```

---

## Cross-cutting (cuidado!)

### `pyproject.toml`

Slice A adiciona `slowapi`. Slice C adiciona `prometheus-fastapi-instrumentator`. Merge: orchestrator resolve mantendo ambas.

### `src/wake/api/app.py`

A monta `Limiter` + exception handler. A monta `backpressure middleware`. C monta `instrumentator` + `/metrics` endpoint. Conflito esperado; orchestrator resolve mantendo todas as mounts.

### `src/wake/runtime/dispatcher.py`

A adiciona queue depth gauge. B adiciona post-step cost check. C emite metrics. 3-way conflito esperado; orchestrator resolve mantendo todas as inserções (cada uma em método diferente do dispatcher).

### `deploy/helm/wake/values.yaml`

B adiciona seção `retention:`. C adiciona seção `monitoring:`. Sem overlap.

### `deploy/helm/wake/values.schema.json`

Idem — B adiciona schema retention, C adiciona schema monitoring. Sem overlap.

### `src/wake/store/base.py`

A estende `EventStore.append` (signature). B adiciona compact + archive helpers. Sem conflito (métodos diferentes).

---

## ACCEPTANCE CRITERIA por slice

### `ops-throughput` done quando:

- [ ] `slowapi` mounted; `Limiter` exposed via `get_state(request)`
- [ ] Rate-limit key extractor: `f"{api_key_or_anon}:{workspace_id}"`
- [ ] Per-route limits: writes (`POST/PATCH/DELETE`) → 60/min · reads → 300/min (configurable)
- [ ] 429 response includes `Retry-After` header + JSON body com `detail` + `limit` + `reset_at`
- [ ] Redis backend opt-in via `WAKE_RATELIMIT_REDIS_URL` (graceful fallback to memory se URL inválida)
- [ ] `EventStore.append(..., idempotency_key=None)` — repeated append com mesma key retorna evento existente (não cria duplicate)
- [ ] Migration `0004_idempotency` cria UNIQUE partial index em Postgres
- [ ] SQLite usa CREATE UNIQUE INDEX equivalente
- [ ] Worker queue depth exposto como atributo do dispatcher; saturation = depth / max_queue
- [ ] Header `X-Wake-Worker-Saturation` em response autenticadas
- [ ] 503 + `Retry-After: 30` quando saturation >= 1.0
- [ ] `test_ratelimit.py`: 4+ cases (under limit, over limit, redis fallback, per-route override)
- [ ] `test_idempotency.py`: 6+ cases (no key → normal append, with key → first creates, second returns existing, different sessions don't collide, different workspaces don't collide, NULL keys never collide)
- [ ] `test_backpressure.py`: 3+ cases (saturation < 0.8 → header only, saturation >= 1.0 → 503, header value rounded)
- [ ] `pytest tests/unit/ adapters/postgres-store/tests/ -q` clean
- [ ] `docs/OPERATIONS.md` ≥200 linhas

### `ops-cost-retention` done quando:

- [ ] `agent.metadata.max_cost_usd` honored: session interrupted quando soma de event.metadata.cost_usd > max
- [ ] `event.metadata.cost_usd` continua sendo emitido por LiteLLM callbacks (não muda)
- [ ] Interrupt event tem reason="cost_budget_exceeded"
- [ ] `wake events compact --session=<id>` coalesce delta events: 1k deltas → 1 snapshot event + delete deltas
- [ ] `wake events archive --before=<ISO date> --bucket=s3://...` exporta JSONL gzip pra S3 + delete local
- [ ] Migration 0005 cria `archive_log` (audit: timestamp, session_count, event_count, bytes, s3_key)
- [ ] Helm CronJob retention opt-in; default off
- [ ] `test_cost_budget.py`: budget under, budget exceeded → interrupt, no budget → no enforcement
- [ ] `test_retention.py`: TTL filter, batch delete, dry-run mode
- [ ] `test_compact.py`: 100 deltas → 1 snapshot; idempotent; preserva replay determinism
- [ ] `pytest tests/unit/ -q` clean (sem regressão Phase 6 baseline)
- [ ] `docs/COST-BUDGET.md` ≥150 linhas
- [ ] `docs/RETENTION.md` ≥250 linhas (TTL + compact + archive + restore from archive procedure)

### `ops-metrics-benchmark` done quando:

- [ ] `GET /metrics` retorna Prom exposition format
- [ ] Counters: `wake_sessions_total{status}`, `wake_events_total{type, workspace}`, `wake_errors_total{code}`
- [ ] Histograms: `wake_step_duration_seconds`, `wake_cost_usd`, `wake_event_count_per_session`
- [ ] Gauges: `wake_worker_queue_depth`, `wake_workers_active`
- [ ] Labels incluem `workspace` (cardinality controlada via env `WAKE_METRICS_WORKSPACE_LABEL=true/false`; default false em production multi-tenant pra evitar cardinality explosion)
- [ ] Helm `ServiceMonitor` opt-in via `monitoring.enabled=true`; renderiza com kube-prometheus-stack labels
- [ ] k6 scenario `tests/load/k6/wake-api.js` simula 1000 concurrent sessions, 10k events/min sustained, 30 min
- [ ] `docs/BENCHMARKS.md` ≥300 linhas com results table: p50/p95/p99 latency per endpoint, throughput, error rate, observed resource usage
- [ ] `docs/OBSERVABILITY.md` ≥200 linhas com Prom queries exemplares + Grafana dashboard JSON anexo
- [ ] `pytest tests/unit/test_metrics_prom.py -v` 5+ cases
- [ ] `helm template ... --set monitoring.enabled=true` renderiza ServiceMonitor válido

**Quality (todos):**
- [ ] Sem regressão nas suites existentes (382 unit baseline)
- [ ] TypeScript strict (se houver frontend additions; provavelmente nenhum)
- [ ] ruff + mypy strict clean
- [ ] Commit prefixes: `api:`, `rbac:`, `ops:`, `deploy:`, `docs:`, `tests:`

---

## MERGE ORDER

1. **`ops-throughput`** → main (idempotency é foundational; rate-limit + backpressure independentes)
2. **`ops-cost-retention`** → main (cost-budget usa dispatcher; pode conflitar em `dispatcher.py` com A)
3. **`ops-metrics-benchmark`** → main (metrics depende de dispatcher final estado)

Conflict resolution: `dispatcher.py` é 3-way (A queue depth + B cost check + C metrics emit). Orchestrator mantém todas as inserções (cada uma em método diferente).

Após cada merge: `pytest tests/unit/ adapters/postgres-store/tests/ -q` + `helm lint deploy/helm/wake`.

Tag final: `v0.7.0-ops-hardening` após merge C.

---

## CONVENÇÕES

- Python 3.11+, ruff, mypy strict
- Migration idempotente (`CREATE/ALTER ... IF NOT EXISTS`)
- Rate-limit storage NÃO pode ser hard-dep em Redis — fallback memory é mandatório
- Cost enforcement NUNCA bloqueia event append (não-trivial revert); apenas interrupt session subsequente
- Compact NUNCA muda hashes de eventos preservados (snapshot é novo event ULID, deltas são deleted)
- Archive NUNCA delete antes de confirmar upload S3 success
- `/metrics` endpoint NÃO autenticado (Prom convention) — operadores firewall via network policy

---

## REGRA DE OURO

1. **Leia este contrato + `docs/ROADMAP.md` Tier 1 + `phases/PHASE-6-CONTRACT.md` (padrão) ANTES de codar.**
2. **Backend additions são ADDITIVE — não muda shape de Event/AgentConfig/Session.**
3. **Idempotency: NULL key = comportamento atual (sempre append); NOT NULL = ON CONFLICT DO NOTHING + return existing.**
4. **Cost enforcement é REATIVO (post-step), não preditivo.**
5. **Prometheus labels alta-cardinality (workspace) opt-in via env — default off em prod.**
6. **Commit no SEU worktree** (`wake-wt-ops-<slice>/`), branch `agent/ops-<slice>`.
7. **Quando terminar**: reporte tests, helm lint/template, k6 results se aplicável, files fora do slice tocados.
8. **Estimativa**: 150-210min wall-clock por slice.
9. **NÃO PUSH. NÃO MERGE.** Orchestrator faz.
