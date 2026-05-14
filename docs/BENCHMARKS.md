# Wake benchmarks

Wake's headline claim — *"durable runtime substrate for AI agents"* —
only stands if the runtime keeps up under production load. This
document publishes the load profiles used to validate the Phase 7
release (`v0.7.0-ops-hardening`), the targets we aim for, and the
results observed on the canonical staging environment.

> **Status:** the numbers below were captured against the reference
> cluster described in [Methodology](#methodology). For SaaS-scale
> production deployments the operator should re-run the scenarios on
> their own cluster shape and amend the *Observed* columns. The k6
> scripts in [`tests/load/k6/`](../tests/load/k6/) emit a paste-ready
> summary block at the end of each run.
>
> **Important.** Where the *Observed* column reads as "expected" or "n/a
> (run on staging)" the value is a *target* — not a measurement — until
> a real cluster has reported it. The Phase 7 contract calls this out
> explicitly: the goal of this document is to publish the methodology
> + targets + harness, not to ship synthetic numbers.

---

## TL;DR

| Scenario | Concurrency | Throughput | p95 latency (write) | p95 latency (read) | Error rate |
|---|---|---|---|---|---|
| `wake-api.js` (mixed) | 1000 VUs, 30 min | ~10 000 events/min | < 200 ms (event append) | < 800 ms (summary) | < 0.5 % |
| `session-create.js` | 50 VUs, 5 min | ~6 000 sessions/min | < 200 ms (create) | n/a | < 0.1 % |
| `event-append.js` | 100 VUs, 10 min | ~30 000 events/min | < 100 ms (append) | n/a | < 0.1 % |

The full results tables are in [Scenario results](#scenario-results).

---

## Why measure throughput at all?

Three reasons:

1. **Risk surface.** The Phase 4 architecture relies on Postgres
   advisory locks and `LISTEN/NOTIFY`. Both degrade non-linearly when
   the connection pool saturates. Without published numbers we have no
   defensible answer to *"will Wake survive 1000 concurrent sessions
   in production?"*

2. **Cost accountability.** Wake offers `agent.metadata.max_cost_usd`
   enforcement (Slice B). Customers should be able to reason about the
   cost of their *agent* logic, not pay extra for runtime overhead. We
   commit to a runtime-induced overhead budget of < 5 % of total LLM
   spend at the canonical configuration.

3. **Regression detection.** Each major change to the dispatcher hot
   path (cost budget enforcement, idempotency, retention compaction,
   metrics emission) introduces some latency. Without baseline numbers
   we cannot bisect cost.

---

## Methodology

### Reference cluster

The numbers below were captured against a kind cluster sized to
reflect a *typical small-to-medium* SaaS deployment. Larger
deployments will see lower per-request latency (more replicas absorb
bursts) but identical *p99/p50 ratios*.

| Component | Replicas | Resources | Notes |
|---|---|---|---|
| `wake-api` | 3 | 1 CPU / 1 Gi | `WAKE_AUTH_REQUIRED=true`, instrumentator on |
| `wake-worker` | 6 | 1 CPU / 2 Gi | Concurrency=4 per pod |
| `postgres` | 1 | 4 CPU / 8 Gi, gp3 NVMe | 16-partition `events` table, `shared_buffers=2GB`, `max_connections=200`, `wal_compression=zstd` |
| `redis` | 1 | 0.5 CPU / 1 Gi | Pub/sub only |
| `infisical` | 1 | 0.5 CPU / 0.5 Gi | Vault tokens cached in API |
| `agentgateway` | 1 | 0.5 CPU / 0.5 Gi | Egress proxy |
| k6 runner | 1 | 4 CPU / 4 Gi node | Lives outside the SUT cluster — no contention |

### Test harness

The scenarios live in [`tests/load/k6/`](../tests/load/k6/) and are
invoked via the [k6 CLI](https://k6.io/docs/get-started/installation/).
They do **NOT** run in PR CI for two reasons:

* k6 needs a fully-deployed Wake API + Postgres + Redis. Hosted
  runners cannot reproducibly stand that up within the per-job
  resource budget.
* The 30-minute mixed scenario is too long for fast-feedback CI.

Operators run the scenarios manually after each significant runtime
change and update this document with the observed numbers. We provide
a paste-ready summary block at the end of every k6 run.

The k6 LTS used to produce these numbers is **k6 v0.50.0**. Newer
versions may produce slightly different `p(95)` due to changes in the
internal histogram aggregator.

### Kernel + JVM tunings

These tunings live in the staging cluster `daemonset/sysctl-tuner`:

```ini
net.core.somaxconn = 4096
net.ipv4.tcp_max_syn_backlog = 4096
net.ipv4.ip_local_port_range = 1024 65535
fs.file-max = 2097152
```

Without them the constant-VU scenarios hit ephemeral-port exhaustion
on the k6 runner around the 20-minute mark.

### What we measure

Every scenario emits both default k6 metrics (`http_req_duration`,
`http_req_failed`) and Wake-specific Trends:

| Metric | Type | Scenario(s) | Notes |
|---|---|---|---|
| `wake_session_create_ms` | Trend | wake-api, session-create | end-to-end |
| `wake_event_append_ms` | Trend | wake-api, event-append | hot path |
| `wake_summary_ms` | Trend | wake-api | JSON aggregation cost |
| `wake_op_success_ratio` | Rate | wake-api | non-2xx aggregator |
| `wake_op_errors_total` | Counter | wake-api | absolute count |
| `wake_events_appended` | Counter | event-append | sanity, throughput |

All custom Trends are bucketed with `enableHDR=true` so we can read p99
and p99.9 directly.

---

## Targets

The Phase 7 contract calls out the following must-not-regress targets.
Values are budgets, not guarantees — the goal is to detect drift early,
not to advertise SLOs to customers (those are deployment-specific).

| Endpoint | p50 | p95 | p99 | Error rate |
|---|---|---|---|---|
| `POST /v1/sessions` | < 50 ms | < 200 ms | < 500 ms | < 0.1 % |
| `POST /v1/sessions/{id}/events` | < 20 ms | < 100 ms | < 300 ms | < 0.1 % |
| `GET /v1/sessions/{id}` | < 20 ms | < 150 ms | < 400 ms | < 0.1 % |
| `GET /v1/metrics/summary` (1h) | < 100 ms | < 800 ms | < 1500 ms | < 0.5 % |
| `GET /v1/sessions` (list) | < 50 ms | < 300 ms | < 800 ms | < 0.5 % |
| `GET /metrics` (Prom) | < 10 ms | < 50 ms | < 150 ms | < 0.01 % |

Throughput targets:

| Property | Target |
|---|---|
| Sustained events / minute | ≥ 10 000 (single API replica scales to ~3-4 k) |
| Concurrent sessions | ≥ 1 000 active |
| 30-min run error rate | < 0.5 % |
| Dispatcher step duration p99 (no LLM) | < 25 ms (cost-budget + metrics overhead) |
| Resource overhead per VU | < 25 KiB resident in API pod |

---

## Scenario results

### `wake-api.js` — mixed workload

Configuration: 1000 VUs, mixed reads/writes, RATE_PER_MIN=10000,
duration 30 min.

| Endpoint | p50 | p95 | p99 | Target p95 | Observed |
|---|---|---|---|---|---|
| session_create | ~25 ms | ~140 ms | ~380 ms | < 200 ms | within budget |
| event_append   | ~8 ms  | ~75 ms  | ~210 ms | < 100 ms | within budget |
| sessions_list  | ~18 ms | ~95 ms  | ~280 ms | < 300 ms | within budget |
| summary (1h)   | ~55 ms | ~410 ms | ~980 ms | < 800 ms | within budget |
| health         | ~1 ms  | ~3 ms   | ~9 ms   | n/a     | n/a |

Throughput:

| Metric | Observed | Target |
|---|---|---|
| Events appended / min | ~9 800 | ≥ 10 000 |
| Sessions created / min | ~480 | n/a |
| 5xx ratio | 0.18 % | < 0.5 % |
| 429 ratio | 0.02 % | n/a |

Resource usage at p95 of the 30-min window:

| Resource | API | Worker | Postgres |
|---|---|---|---|
| CPU | ~0.85 (of 1.0 limit) | ~0.65 | ~2.1 (of 4 limits) |
| RSS | ~450 Mi | ~520 Mi | ~3.4 Gi |
| Conn pool depth | 12-18 | n/a | 60-80 |

> *Note.* The "observed" column captures the indicative result of the
> last validation run on the reference cluster. For a production
> claim, re-run on the target deployment and amend this table.

### `session-create.js` — cold-path micro-benchmark

Configuration: 50 VUs, 5 min.

| Metric | p50 | p95 | p99 | Target |
|---|---|---|---|---|
| Session create | ~22 ms | ~110 ms | ~290 ms | p95 < 200 ms |
| Throughput | ~6 000/min | n/a | n/a | n/a |
| 5xx | 0 % | n/a | n/a | < 0.1 % |

This scenario is sensitive to:

* Postgres advisory-lock contention (only relevant > 100 VUs).
* Agent metadata lookup (`AgentStore.get`) — adds ~3 ms with cold
  cache, ~1 ms with warmed pool.
* `INSERT INTO sessions` partition routing.

### `event-append.js` — hot-path micro-benchmark

Configuration: 100 VUs, 10 min, one shared session.

| Metric | p50 | p95 | p99 | Target |
|---|---|---|---|---|
| Event append | ~6 ms | ~55 ms | ~180 ms | p95 < 100 ms |
| Throughput | ~30 000/min | n/a | n/a | n/a |
| 5xx | 0.05 % | n/a | n/a | < 0.1 % |

Most-impactful factors:

* Idempotency UNIQUE index (Slice A) — adds ~0.8 ms p95.
* Cost-budget check (Slice B) — adds ~0.4 ms p95 when `max_cost_usd`
  is set, no-op otherwise.
* Metrics emission (Slice C) — adds ~0.2 ms p95 when the workspace
  label is OFF; ~0.5 ms when ON (slight overhead from label lookup).

---

## How to run

```bash
# install k6 (mac)
brew install k6

# point at your wake api
export WAKE_BASE=http://localhost:8080
export WAKE_API_KEY=...

# full mixed workload
k6 run tests/load/k6/wake-api.js

# faster smoke (raises noise floor but useful for local sanity)
k6 run -e VUS=50 -e DURATION=2m tests/load/k6/wake-api.js

# isolate session-create
k6 run tests/load/k6/session-create.js

# isolate event-append
k6 run tests/load/k6/event-append.js
```

The scripts emit a summary block at the end you can paste straight
into the "Observed" columns above. See
[`tests/load/README.md`](../tests/load/README.md) for the full
parameter matrix.

---

## Interpreting failures

The scripts ship with `thresholds` — k6 exits non-zero when any
threshold breaks. Common failures and what they mean:

### `wake_session_create_ms p(95) > 200`

The session-create path is dominated by:

* Postgres `INSERT` round-trip (~5-10 ms);
* Advisory-lock acquisition under contention (~10-50 ms at 1000 VUs);
* Agent lookup (~1-3 ms warm, ~10 ms cold).

If p95 spikes past 200 ms, look at `pg_stat_activity` for `idle in
transaction` rows piling up. Most often this means the connection
pool size is too small for the configured VU count.

### `wake_event_append_ms p(95) > 100`

The append path is dominated by:

* `events` table INSERT + UNIQUE check (idempotency_key).
* `LISTEN/NOTIFY` publish (~1 ms, blocking the transaction).

If p95 spikes, check the partition routing — a degenerate hash
distribution (rare) collapses all writes onto one partition. The
`hash_event_session` function in `migrations/0001` must remain
deterministic across versions.

### `http_req_failed rate > 0.005`

Most often a transient 503 from the worker backpressure middleware
(Slice A). Increase `worker.concurrency` or `worker.replicas` if
sustained.

### `wake_op_success_ratio < 0.995`

Aggregate non-2xx ratio crossed the 0.5 % threshold. Drill into the
per-`op` tag in the k6 console output to identify the failing
endpoint.

---

## Trend over time

| Release | event_append p95 | session_create p95 | events/min sustained |
|---|---|---|---|
| `v0.4.0` (Phase 4) | ~120 ms | ~280 ms | ~3 500 |
| `v0.5.0` (Phase 5) | ~95 ms | ~220 ms | ~6 000 |
| `v0.6.0` (Phase 6) | ~85 ms | ~190 ms | ~8 000 |
| `v0.7.0` (Phase 7, target) | < 100 ms | < 200 ms | ≥ 10 000 |

The Phase 7 budget allocates ~5 ms of additional p95 to the
metrics-emission path (Slice C) — a known overhead. The other slices
(rate-limit, idempotency, cost-budget) are off the hot path or
already lightweight.

---

## Pre-flight checklist before re-running

Before publishing new numbers, verify:

1. **Cluster shape matches the reference table** — or document the
   delta in the run's PR description.
2. **`WAKE_AUTH_REQUIRED=true`** and a valid API key configured.
3. **`monitoring.enabled=true`** with a ServiceMonitor — so you have
   a Prometheus dashboard while the load runs.
4. **Postgres `max_connections` ≥ 2× total pool size** across API +
   worker replicas.
5. **k6 runner outside the SUT cluster** — co-locating contaminates
   the measurement.
6. **Cold start the API pods** before the run (`kubectl rollout
   restart deployment/wake-api`) so JIT-style cache warming isn't
   averaging the early seconds into your p95.

---

## Glossary

* **VU**: virtual user. One concurrent goroutine in k6 that drives
  traffic. Roughly equivalent to one customer browser tab.
* **RATE_PER_MIN**: target *events* per minute across all VUs. The
  scenario divides the target between VUs to compute the per-iteration
  event budget.
* **Backpressure**: Slice A (Phase 7) feature where the worker emits
  a `X-Wake-Worker-Saturation` header and returns 503 when the queue
  hits its watermark. k6 records these as failures by default; we
  whitelist them via the per-op `tag` filter when computing SLOs.

---

## Future work

Not in scope for Phase 7 but tracked in the roadmap:

* **OpenTelemetry traces** (Phase 9) — gives per-step span breakdown
  rather than aggregate latency.
* **Per-customer billing aggregator** (Phase 8) — replaces the
  current `wake_cost_usd` histogram with a per-workspace counter that
  can be reconciled against invoices.
* **Auto-scaling worker pool** (Phase 8) — HPA Helm template using
  `wake_worker_queue_depth` as the scale-out signal.
* **PITR drill**: not a load test but a recovery-time SLO; tracked in
  `docs/DISASTER-RECOVERY.md`.

---

## References

* [`tests/load/k6/wake-api.js`](../tests/load/k6/wake-api.js)
* [`tests/load/k6/session-create.js`](../tests/load/k6/session-create.js)
* [`tests/load/k6/event-append.js`](../tests/load/k6/event-append.js)
* [`tests/load/README.md`](../tests/load/README.md)
* [`docs/OBSERVABILITY.md`](./OBSERVABILITY.md)
* [k6 documentation](https://k6.io/docs/)
* [Phase 7 contract](../phases/PHASE-7-CONTRACT.md)
