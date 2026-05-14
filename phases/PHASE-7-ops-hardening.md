# Phase 7 — Operational Hardening

> **Objetivo:** Wake passa em load test de 1000 concurrent sessions em produção real. Resolve Tier 1 gaps (#4–#8) do roadmap: idempotency, retention, rate-limit, cost-budget, Prometheus.

| | |
|---|---|
| **Status** | 🟡 next |
| **Duração estimada** | 2-3 semanas (~5-8h multi-agent wall-clock) |
| **Dependências** | Phase 6 done (`v0.6.0-tenancy`) |
| **Tier resolved** | Tier 1 (#4 idempotency · #5 retention · #6 rate-limit · #7 cost-budget · #8 Prometheus) |

---

## Por que essa fase existe

Phase 6 entregou multi-tenant + RBAC + backup. Wake agora **opera em produção**, mas ainda é "dev tool" sem hardening operacional. Tier 1 cobre os 5 gaps que separam "dev tool" de "production substrate":

| Gap | Problema | Impacto |
|---|---|---|
| #4 Idempotency | Worker double-process (Codex finding Phase 5.2) pode escrever 2× | Drift de seq + custos duplicados |
| #5 Retention | Event log cresce pra sempre; sessões 100k+ inviáveis no replay | Storage explosivo + degradação UX |
| #6 Rate-limit | Cliente mal-configurado faz DDoS interno | Worker saturação cascateia em outras sessions |
| #7 Cost-budget | Session pode rodar até R$10k sem ninguém saber | Risco financeiro não-bound |
| #8 Prometheus | Só JSON `/v1/metrics/summary` pro dashboard | SRE não consegue alertar; ops scrape Prom, não REST |

Sem essa phase, Wake **não roda em prod com customer real** mesmo com Phase 6 done — primeiro abuso/bug operacional queima a confiança.

---

## Entry criteria

- ✅ Phase 6 done (`v0.6.0-tenancy`)
- ✅ 382 unit tests pass baseline
- ✅ Helm chart com tenancy + RBAC + backup operacionais

---

## Exit criteria

### Rate-limit + idempotency + backpressure (Slice A)
- [ ] `slowapi` mounted; per-API-key + per-workspace + per-route limits
- [ ] 429 com `Retry-After` + JSON detail
- [ ] Redis backend opt-in; fallback memory
- [ ] `event.metadata.idempotency_key` honored com UNIQUE partial index
- [ ] Worker backpressure header + 503 trigger
- [ ] Migration 0004 idempotente

### Cost-budget + retention (Slice B)
- [ ] `agent.metadata.max_cost_usd` enforced (interrupt quando excede)
- [ ] `wake events compact --session=<id>` coalesce deltas
- [ ] `wake events archive --before=<date> --bucket=s3://...` exporta JSONL gzip
- [ ] Helm CronJob retention opt-in
- [ ] Migration 0005 cria `archive_log` audit table

### Prometheus + benchmarks (Slice C)
- [ ] `GET /metrics` retorna Prom exposition
- [ ] Counters/histograms/gauges para sessions, events, costs, errors
- [ ] Helm `ServiceMonitor` opt-in
- [ ] k6 load test 1000 concurrent sessions
- [ ] `docs/BENCHMARKS.md` published com p50/p95/p99 results

### Quality
- [ ] Sem regressão nas 382 unit tests + 107 vitest baseline
- [ ] Tag `v0.7.0-ops-hardening`

---

## Deliverables

```
src/wake/api/
├── ratelimit.py                   NEW (slice A)
├── metrics_prom.py                NEW (slice C)
├── middleware/backpressure.py     NEW (slice A)
└── (updates em app.py + dependencies.py)

src/wake/runtime/
├── cost_budget.py                 NEW (slice B)
├── dispatcher.py                  UPDATE (3-way: queue depth + cost check + metrics)
└── (updates)

src/wake/cli/
└── retention.py                   NEW (slice B — wake events compact/archive)

src/wake/observability/
└── metrics.py                     NEW (slice C — Prom counters/histograms)

adapters/postgres-store/alembic/versions/
├── 0004_idempotency.py            NEW (slice A)
└── 0005_retention.py              NEW (slice B)

deploy/helm/wake/templates/
├── cronjob-retention.yaml         NEW (slice B)
└── servicemonitor.yaml            NEW (slice C)

tests/load/k6/
├── wake-api.js                    NEW (slice C)
├── session-create.js              NEW
└── event-append.js                NEW

docs/
├── OPERATIONS.md                  NEW (slice A — rate-limit + idempotency + backpressure)
├── COST-BUDGET.md                 NEW (slice B)
├── RETENTION.md                   NEW (slice B)
├── BENCHMARKS.md                  NEW (slice C)
└── OBSERVABILITY.md               NEW (slice C)
```

---

## Reusable components

| Item | Source | License | Uso |
|---|---|---|---|
| Rate-limit | [slowapi](https://github.com/laurentS/slowapi) | MIT | FastAPI-native, Limiter pattern |
| Rate-limit storage | Redis (opt-in) | BSD | Já presente em deploy Compose |
| Prom instrumentator | [prometheus-fastapi-instrumentator](https://github.com/trallnag/prometheus-fastapi-instrumentator) | ISC | Cobre HTTP metrics out-of-box |
| k6 | [Grafana k6](https://k6.io/) | AGPL (client MIT) | Industry-standard load tester |
| ServiceMonitor CRD | [kube-prometheus-stack](https://prometheus-operator.dev/) | Apache 2 | Operadores já usam |

---

## Risks

### R7.1 — Rate-limit em multi-replica frontend sem Redis
**Prob:** alta · **Imp:** médio
- Memory backend é per-replica → cliente pode 4× burlar com round-robin LB
- Mitigação: `WAKE_RATELIMIT_REDIS_URL` é opt-in mas docs/OPERATIONS.md alerta com bold

### R7.2 — Idempotency partial index não suportado no SQLite < 3.8
**Prob:** baixa · **Imp:** baixo
- Wake já requer SQLite 3.35+ (RETURNING clause); 3.8+ tem partial index
- Tests validam funcionamento

### R7.3 — Cost-budget enforcement vira race window
**Prob:** média · **Imp:** baixo
- Check post-step; race possível entre check + interrupt em sessions long-running
- Aceito; overrun de 1 step não é dimensional (max 1 LLM call)

### R7.4 — Prom labels com workspace → cardinality explosion
**Prob:** alta · **Imp:** alto
- 1000 workspaces × 5 event types × N status = millions de timeseries
- Mitigação: workspace label OPT-IN via `WAKE_METRICS_WORKSPACE_LABEL=true` (default false)

### R7.5 — k6 load test em CI vira ruidoso/flaky
**Prob:** alta · **Imp:** baixo
- Não rodar em PR CI; manual dispatch + scheduled (weekly)
- Results published manually em BENCHMARKS.md

### R7.6 — Archive S3 antes de confirm delete causa data loss
**Prob:** baixa · **Imp:** alto
- Slice B archive command faz upload → verify S3 ETag → delete local — nesta ordem
- Audit table `archive_log` registra cada batch

---

## Decisões adiadas

- ❌ PITR (point-in-time recovery) — Phase 8+ ou opt-in custom
- ❌ Per-customer billing aggregator — Phase 8+
- ❌ OpenTelemetry traces — Phase 9 (junto com supply chain)
- ❌ Auto-scaling dispatcher worker pool — Phase 8+ (HPA Helm template)

---

## Definition of Done

- [ ] Exit criteria checados
- [ ] Tag `v0.7.0-ops-hardening`
- [ ] `pytest` + `vitest` + `helm lint` + `k6` clean
- [ ] `docs/ROADMAP.md` updated — Tier 1 marcado ✅
- [ ] `phases/README.md` updated — Phase 7 ✅
- [ ] Codex adversarial review #3 executada + findings addressed

---

## After this phase

→ [Phase 8](./README.md) — Developer Experience (SDKs Python + TS, edit-and-replay, eval framework, versioning UI).

---

## Multi-agent slicing

3 agents Opus em paralelo, slices disjuntos:

| Slice | Worktree | Owns |
|---|---|---|
| `ops-throughput` | `wake-wt-ops-throughput` | rate-limit + idempotency + backpressure + migration 0004 |
| `ops-cost-retention` | `wake-wt-ops-cost-retention` | cost-budget + compact + archive + retention CronJob + migration 0005 |
| `ops-metrics-benchmark` | `wake-wt-ops-metrics-benchmark` | Prometheus + ServiceMonitor + k6 + BENCHMARKS + OBSERVABILITY |

Detalhes em [`PHASE-7-CONTRACT.md`](./PHASE-7-CONTRACT.md).
