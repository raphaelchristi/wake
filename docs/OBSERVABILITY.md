# Wake observability

Wake exposes a **single Prometheus exposition endpoint** at `GET /metrics`
on every API replica. It serves both:

1. **HTTP transport metrics** (`http_request_duration_seconds`,
   `http_requests_total`, etc.) emitted by
   [`prometheus-fastapi-instrumentator`](https://github.com/trallnag/prometheus-fastapi-instrumentator).
2. **Wake business metrics** (`wake_sessions_total`, `wake_events_total`,
   `wake_cost_usd`, `wake_worker_queue_depth`, etc.) defined in
   [`src/wake/observability/metrics.py`](../src/wake/observability/metrics.py).

This document explains:

* What each metric means and when to alert on it.
* The cardinality discipline (workspace label opt-in, label hygiene).
* The Helm `ServiceMonitor` opt-in.
* Example PromQL queries for the four common questions operators ask.
* A Grafana dashboard JSON skeleton — drop it into Grafana and you get
  Wake's SLO board.

> **Endpoint is unauthenticated by Prometheus convention.** Restrict at
> the *network* layer — a `NetworkPolicy` that allows only the
> kube-prometheus-stack namespace to reach the API pod on the metrics
> port. App-layer auth would require Prometheus to carry the
> `X-Wake-API-Key` header, which is not standard.

---

## Metrics catalogue

### Counters

#### `wake_sessions_total{status}`

Total number of Wake session terminal transitions classified by terminal
state. Labels:

* `status` ∈ {`terminated`, `interrupted`, `failed`}. Bounded
  cardinality.

Emitted by the dispatcher / session state machine on every terminal
transition. Useful for:

* Rate of session failures: `rate(wake_sessions_total{status="failed"}[5m])`
* Interrupt ratio (cost-budget enforcement signal):
  `sum(rate(wake_sessions_total{status="interrupted"}[1h]))
  / sum(rate(wake_sessions_total[1h]))`

#### `wake_events_total{type, workspace}`

Total events appended to the event log. Labels:

* `type` ∈ the canonical Wake `EventType` enum (8 fixed values:
  `user.message`, `assistant.delta`, `assistant.message`,
  `tool.call`, `tool.result`, `session.created`,
  `session.terminated`, `session.interrupt`). Bounded.
* `workspace` — see [Cardinality discipline](#cardinality-discipline)
  below. Default `_aggregated`; the actual workspace ID only when
  `WAKE_METRICS_WORKSPACE_LABEL=true`.

Useful for:

* Event-throughput board: `sum by (type) (rate(wake_events_total[1m]))`
* Per-workspace traffic (when label is on):
  `topk(10, sum by (workspace) (rate(wake_events_total[1h])))`

#### `wake_errors_total{code}`

Business-level errors classified by **short stable codes**, not
free-form messages. Labels:

* `code` — small enum of e.g. `dispatcher_step_failed`,
  `oauth_state_invalid`, `cost_budget_exceeded`,
  `rate_limit_exceeded`. New codes are added in source — never
  derived from exception text.

Useful for:

* Error budget burn:
  `sum(rate(wake_errors_total[5m]))
  / sum(rate(wake_events_total[5m]))`
* Cost-budget enforcement rate:
  `rate(wake_errors_total{code="cost_budget_exceeded"}[1h])`

### Histograms

#### `wake_step_duration_seconds`

Latency of a single dispatcher adapter step in seconds.

Buckets: 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 25.0,
60.0, 120.0 — tuned for LLM-driven steps (typically 0.1-30 s) plus
sub-second tool calls.

Useful for:

* p95 latency: `histogram_quantile(0.95, sum(rate(wake_step_duration_seconds_bucket[5m])) by (le))`
* Slow-step detection: `histogram_quantile(0.99, sum(rate(wake_step_duration_seconds_bucket[5m])) by (le)) > 30`

#### `wake_cost_usd`

Distribution of per-event cost in USD (read from
`event.metadata.cost_usd`).

Buckets: 0.0001, 0.001, 0.01, 0.05, 0.10, 0.50, 1.0, 5.0, 10.0.

Useful for:

* Sum of dollars spent in an interval:
  `sum(increase(wake_cost_usd_sum[1h]))`
* Average cost per event:
  `sum(rate(wake_cost_usd_sum[1h])) / sum(rate(wake_cost_usd_count[1h]))`
* Top-spending sessions (label-free; aggregate at the event-log layer).

#### `wake_event_count_per_session`

Distribution of total events at session termination.

Buckets: 1, 5, 10, 50, 100, 500, 1_000, 5_000, 10_000.

Useful for:

* Detect runaway sessions: histogram quantile p99 spiking.
* Right-size compaction: if p95 > 500, consider running
  `wake events compact` more aggressively.

### Gauges

#### `wake_worker_queue_depth`

Current depth of the dispatcher's pending-session queue. One sample per
worker replica when scraped.

Useful for:

* HPA scale-out signal (Phase 8 will wire this into the autoscaler).
* Backpressure dashboards: alert when sustained > N for M minutes.

#### `wake_workers_active`

Number of workers currently processing at least one session.

Useful for:

* Capacity dashboards: `(wake_workers_active / wake_workers_max) > 0.8`
  for the saturation alert.

### HTTP transport metrics (out-of-box)

These come from `prometheus-fastapi-instrumentator` with the
`http_request` / `http_response` namespace:

* `http_request_duration_seconds_bucket{handler, method, status}`
* `http_requests_total{handler, method, status}`
* `http_request_size_bytes_sum/count`
* `http_response_size_bytes_sum/count`

The `handler` label uses the **templated route** (`/v1/sessions/{session_id}`,
not `/v1/sessions/abc123`) so cardinality stays bounded. The `/metrics`
endpoint itself is excluded.

---

## Cardinality discipline

Prometheus is a *fixed-cardinality* TSDB. Labels with unbounded values
(workspace ID, session ID, user ID) destroy a Prometheus deployment
silently — RAM grows linearly with active series until OOM.

Wake therefore practises three rules:

1. **`workspace` label is OPT-IN.** Set
   `WAKE_METRICS_WORKSPACE_LABEL=true` only in deployments with
   ≤ ~100 workspaces. The default (off) collapses all workspaces into a
   constant string `_aggregated`. The aggregation is acceptable
   because per-workspace breakdowns can be reconstructed from the
   `/v1/metrics/summary` JSON endpoint (which queries the event log
   directly).

2. **Session / user IDs never appear as labels.** Wake stores those in
   payloads / structured logs instead.

3. **Error codes are a small enum.** New error classifications are
   added in source, not derived from exception messages.

If you see Prometheus RAM ballooning after enabling Wake, check the
output of `count(count by (workspace) (wake_events_total))`. If it
exceeds ~1000, turn `WAKE_METRICS_WORKSPACE_LABEL` off and re-deploy.

---

## Helm `ServiceMonitor`

Wake ships a kube-prometheus-stack-compatible `ServiceMonitor` template
that is **disabled by default** (opt-in).

### Enable

```yaml
# values.yaml
monitoring:
  enabled: true
  labels:
    release: prometheus   # matches your kube-prom-stack selector
  interval: "30s"
  scrapeTimeout: "10s"
```

Apply: `helm upgrade --install wake ./deploy/helm/wake -f values.yaml`.

### Verify

```bash
kubectl get servicemonitor -n <ns> wake-api
kubectl get servicemonitor -n <ns> wake-api -o yaml
```

Then check the Prometheus targets page: it should list each `wake-api`
pod with state `UP`.

### Notes

* The CRD `monitoring.coreos.com/v1` must exist in the cluster.
  Install kube-prometheus-stack first — Wake does not bundle the CRD.
* The endpoint port is `http` (matches the `wake-api` Service spec).
* `targetLabels` defaults to `[]` — pass selectors (e.g. `app.kubernetes.io/instance`)
  to forward labels onto the scraped series.

---

## Example PromQL

These cover the four most common operator questions:

### "Is Wake healthy right now?"

```promql
# 5xx ratio over the last 5 minutes
sum(rate(http_requests_total{status=~"5.."}[5m]))
  / sum(rate(http_requests_total[5m]))
```

Alert when > 0.5 % for > 5 minutes.

### "How busy is the worker fleet?"

```promql
# Average queue depth across worker replicas
avg(wake_worker_queue_depth)
```

Alert when > 10 sustained > 10 min OR `wake_worker_queue_depth > 50` instantaneously.

### "How much money did we spend in the last hour?"

```promql
sum(increase(wake_cost_usd_sum[1h]))
```

For a per-workspace breakdown (with `WAKE_METRICS_WORKSPACE_LABEL=true`):

```promql
topk(10, sum by (workspace) (increase(wake_cost_usd_sum[1h])))
```

### "Are users hitting cost budgets?"

```promql
rate(wake_errors_total{code="cost_budget_exceeded"}[1h])
```

Alert when > 5/min for > 30 min (= many concurrent budgets blowing).

### "What's the p95 step latency?"

```promql
histogram_quantile(
  0.95,
  sum by (le) (rate(wake_step_duration_seconds_bucket[5m]))
)
```

Alert when > 30 s sustained (likely model upstream issue).

### "Which workspace generates the most events?"

```promql
# Requires WAKE_METRICS_WORKSPACE_LABEL=true
topk(20,
  sum by (workspace) (rate(wake_events_total[1h]))
)
```

---

## Suggested alerts

Drop these into your kube-prometheus-stack `PrometheusRule`:

```yaml
groups:
  - name: wake-api.slo
    rules:
      - alert: WakeAPIHighErrorRate
        expr: |
          (
            sum(rate(http_requests_total{job="wake-api", status=~"5.."}[5m]))
              / sum(rate(http_requests_total{job="wake-api"}[5m]))
          ) > 0.005
        for: 10m
        labels: { severity: warning }
        annotations:
          summary: "Wake API 5xx ratio > 0.5% for 10m"

      - alert: WakeWorkerQueueDepthHigh
        expr: avg(wake_worker_queue_depth) > 10
        for: 10m
        labels: { severity: warning }

      - alert: WakeCostBudgetSpike
        expr: rate(wake_errors_total{code="cost_budget_exceeded"}[5m]) > 0.1
        for: 5m
        labels: { severity: info }
        annotations:
          summary: "Multiple sessions interrupted by cost budget"

      - alert: WakeStepLatencyP99Slow
        expr: |
          histogram_quantile(0.99,
            sum by (le) (rate(wake_step_duration_seconds_bucket[5m]))
          ) > 30
        for: 10m
        labels: { severity: warning }
        annotations:
          summary: "p99 step latency > 30 s — model upstream may be slow"
```

---

## Grafana dashboard

The following JSON is a minimal Grafana dashboard skeleton that
visualises the headline Wake metrics. Save as `wake.json` and import
via Grafana → Dashboards → Import.

```json
{
  "title": "Wake — Runtime Substrate",
  "schemaVersion": 39,
  "version": 1,
  "refresh": "30s",
  "panels": [
    {
      "id": 1,
      "type": "timeseries",
      "title": "HTTP 5xx ratio",
      "gridPos": { "x": 0, "y": 0, "w": 12, "h": 8 },
      "targets": [
        {
          "expr": "sum(rate(http_requests_total{status=~\"5..\"}[5m])) / sum(rate(http_requests_total[5m]))",
          "legendFormat": "5xx ratio"
        }
      ]
    },
    {
      "id": 2,
      "type": "timeseries",
      "title": "Step latency p50/p95/p99",
      "gridPos": { "x": 12, "y": 0, "w": 12, "h": 8 },
      "targets": [
        { "expr": "histogram_quantile(0.50, sum by (le) (rate(wake_step_duration_seconds_bucket[5m])))", "legendFormat": "p50" },
        { "expr": "histogram_quantile(0.95, sum by (le) (rate(wake_step_duration_seconds_bucket[5m])))", "legendFormat": "p95" },
        { "expr": "histogram_quantile(0.99, sum by (le) (rate(wake_step_duration_seconds_bucket[5m])))", "legendFormat": "p99" }
      ]
    },
    {
      "id": 3,
      "type": "timeseries",
      "title": "Events / second (by type)",
      "gridPos": { "x": 0, "y": 8, "w": 12, "h": 8 },
      "targets": [
        {
          "expr": "sum by (type) (rate(wake_events_total[1m]))",
          "legendFormat": "{{ type }}"
        }
      ]
    },
    {
      "id": 4,
      "type": "timeseries",
      "title": "Worker queue depth",
      "gridPos": { "x": 12, "y": 8, "w": 12, "h": 8 },
      "targets": [
        { "expr": "avg(wake_worker_queue_depth)", "legendFormat": "avg" },
        { "expr": "max(wake_worker_queue_depth)", "legendFormat": "max" }
      ]
    },
    {
      "id": 5,
      "type": "stat",
      "title": "USD spent (last 1h)",
      "gridPos": { "x": 0, "y": 16, "w": 6, "h": 6 },
      "targets": [
        { "expr": "sum(increase(wake_cost_usd_sum[1h]))" }
      ]
    },
    {
      "id": 6,
      "type": "stat",
      "title": "Active workers",
      "gridPos": { "x": 6, "y": 16, "w": 6, "h": 6 },
      "targets": [
        { "expr": "sum(wake_workers_active)" }
      ]
    },
    {
      "id": 7,
      "type": "timeseries",
      "title": "Error codes (rate / min)",
      "gridPos": { "x": 12, "y": 16, "w": 12, "h": 6 },
      "targets": [
        {
          "expr": "sum by (code) (rate(wake_errors_total[1m]))",
          "legendFormat": "{{ code }}"
        }
      ]
    },
    {
      "id": 8,
      "type": "timeseries",
      "title": "Session terminal transitions",
      "gridPos": { "x": 0, "y": 22, "w": 12, "h": 8 },
      "targets": [
        {
          "expr": "sum by (status) (rate(wake_sessions_total[5m]))",
          "legendFormat": "{{ status }}"
        }
      ]
    },
    {
      "id": 9,
      "type": "timeseries",
      "title": "HTTP request rate by handler",
      "gridPos": { "x": 12, "y": 22, "w": 12, "h": 8 },
      "targets": [
        {
          "expr": "sum by (handler) (rate(http_requests_total[1m]))",
          "legendFormat": "{{ handler }}"
        }
      ]
    }
  ]
}
```

Tune the dashboard variables (datasource, time range, refresh) per
your Grafana install. For a per-workspace breakdown panel, add a
filter variable bound to the `workspace` label (only meaningful when
`WAKE_METRICS_WORKSPACE_LABEL=true`).

---

## Cardinality budget worked example

A 3-replica Wake API with default settings emits roughly:

| Series family | Cardinality per pod | 3 pods |
|---|---|---|
| `wake_events_total{type, workspace="_aggregated"}` | 8 (types) | 24 |
| `wake_sessions_total{status}` | 3 | 9 |
| `wake_errors_total{code}` | ~10 | ~30 |
| `wake_step_duration_seconds_bucket{le}` | 13 buckets | 39 |
| `wake_cost_usd_bucket{le}` | 10 | 30 |
| `wake_event_count_per_session_bucket{le}` | 10 | 30 |
| `wake_worker_queue_depth` | 1 | 3 |
| `wake_workers_active` | 1 | 3 |
| `http_request_duration_seconds_bucket{handler, method, status, le}` | ~25 routes × 4 methods × 4 status groups × 13 le ≈ 5 200 | ~15 600 |
| python/process collectors | ~20 | ~60 |
| **Total** | ~5 300 | **~15 800** |

Per-pod Prom RAM footprint: roughly 16 MiB at this cardinality
(rule of thumb: ~3 KiB / series). Comfortable.

With `WAKE_METRICS_WORKSPACE_LABEL=true` and 50 workspaces, the
`wake_events_total` family grows from 24 to 8 × 50 × 3 = 1 200 series.
Still small. At 5 000 workspaces it's 120 000 — that's where Prom
starts to feel it.

---

## Troubleshooting

### `/metrics` returns 404

Possible causes:

* The Helm chart is older than v0.7.0. Upgrade.
* `install_prometheus(app)` was not called — only happens if
  someone hand-crafted a FastAPI app outside `create_app()`.

### Metrics page returns 200 but is empty

Likely a wrong `instrument()` ordering — the API was instrumented
after the routes were added in a custom factory. Wake's
`create_app()` does it correctly. If you call `install_prometheus`
manually, do it **after** every `include_router` call.

### Cardinality alert from Prom

Either:

1. You enabled `WAKE_METRICS_WORKSPACE_LABEL=true` in a deployment
   with too many workspaces (> 1000). Turn it off, restart pods.
2. A new error code was added without enum discipline. Check
   `wake_errors_total` for unusual `code=` values.

### Scrapes time out

The default `interval=30s, scrapeTimeout=10s` should be ample. If
scrapes time out, the API pod is overloaded — drill into
`wake_worker_queue_depth` and CPU/RSS on the pod.

### `histogram_quantile` returns `NaN`

Either:

* No samples yet — the histogram is empty.
* Misspelled bucket label name in the query (`_bucket` suffix is
  required).

---

## Implementation notes

* The Prom collector for Wake business metrics lives in
  [`src/wake/observability/metrics.py`](../src/wake/observability/metrics.py).
  All instruments register against the **global** `prometheus_client.REGISTRY`
  so they coexist with the HTTP instrumentator's metrics in a single
  exposition.
* The endpoint mount lives in
  [`src/wake/api/metrics_prom.py`](../src/wake/api/metrics_prom.py).
  It is **re-entrant** — `create_app()` can be called multiple times
  in the same process (tests, `--factory` mode) without raising
  `Duplicated timeseries`.
* `WAKE_METRICS_WORKSPACE_LABEL` is read once at first metric
  emission. Flipping it mid-process requires a restart (Prom
  instruments are immutable once registered).

---

## References

* [Prometheus FastAPI Instrumentator](https://github.com/trallnag/prometheus-fastapi-instrumentator)
* [Prometheus Operator ServiceMonitor](https://prometheus-operator.dev/docs/operator/api/#monitoring.coreos.com/v1.ServiceMonitor)
* [Wake Phase 7 contract](../phases/PHASE-7-CONTRACT.md)
* [`docs/BENCHMARKS.md`](./BENCHMARKS.md)
* [`tests/load/README.md`](../tests/load/README.md)
