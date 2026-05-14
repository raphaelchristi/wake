/*
 * Wake API — full load scenario (Phase 7 / Tier 1 gap #8).
 *
 * Mixed workload that approximates a realistic production hour:
 *
 *   * 1000 concurrent virtual users (each owns one session)
 *   * Sustained 10 000 events/min for 30 min
 *   * Mixed reads (~30%) + writes (~70%)
 *
 * Run from the project root:
 *
 *   k6 run \
 *     -e WAKE_BASE=http://localhost:8080 \
 *     -e WAKE_API_KEY=<key> \
 *     tests/load/k6/wake-api.js
 *
 * For SaaS-grade machines, raise the rate target via -e RATE_PER_MIN=...
 * The scenario is *not* run in PR CI — it requires real infra and is too
 * noisy / heavy for hosted runners. Run it on a staging cluster after
 * each significant runtime change and update docs/BENCHMARKS.md.
 *
 * Thresholds match docs/BENCHMARKS.md "Targets" table; tune as you
 * collect baselines per cluster size.
 */

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Trend, Counter, Rate } from 'k6/metrics';
import { randomString } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js';

// ---------------------------------------------------------------------------
// Config — overridable via -e KEY=VALUE
// ---------------------------------------------------------------------------

const BASE = __ENV.WAKE_BASE || 'http://localhost:8080';
const KEY = __ENV.WAKE_API_KEY || '';
const DURATION = __ENV.DURATION || '30m';
const VUS = parseInt(__ENV.VUS || '1000', 10);
const RATE_PER_MIN = parseInt(__ENV.RATE_PER_MIN || '10000', 10);

// ---------------------------------------------------------------------------
// Custom metrics — surface latency + throughput per logical operation,
// not just per HTTP route. Operators look at these in Grafana.
// ---------------------------------------------------------------------------

const sessionCreateLatency = new Trend('wake_session_create_ms', true);
const eventAppendLatency = new Trend('wake_event_append_ms', true);
const summaryLatency = new Trend('wake_summary_ms', true);
const opErrors = new Counter('wake_op_errors_total');
const opSuccess = new Rate('wake_op_success_ratio');

// ---------------------------------------------------------------------------
// Scenarios — two concurrent workloads.
//
//   * `steady_load`: constant VUs that own sessions and emit events.
//   * `read_traffic`: per-second arrival rate for /v1/metrics/summary
//     and /v1/sessions GET routes — keeps the read path under load too.
// ---------------------------------------------------------------------------

export const options = {
  scenarios: {
    steady_load: {
      executor: 'constant-vus',
      vus: VUS,
      duration: DURATION,
      gracefulStop: '30s',
      exec: 'workload',
    },
    read_traffic: {
      executor: 'constant-arrival-rate',
      rate: 50,
      timeUnit: '1s',
      duration: DURATION,
      preAllocatedVUs: 100,
      maxVUs: 300,
      exec: 'reads',
    },
  },
  // SLO thresholds — break the test if production targets regress.
  thresholds: {
    'http_req_duration{op:session_create}': ['p(95)<500', 'p(99)<1500'],
    'http_req_duration{op:event_append}': ['p(95)<200', 'p(99)<750'],
    'http_req_duration{op:summary}': ['p(95)<800'],
    'http_req_failed': ['rate<0.005'], // < 0.5% errors
    'wake_op_success_ratio': ['rate>0.995'],
  },
  // Reduce noise on tiny machines — set to 0 if needed.
  noConnectionReuse: false,
  discardResponseBodies: false,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function headers() {
  return KEY
    ? { 'Content-Type': 'application/json', 'X-Wake-API-Key': KEY }
    : { 'Content-Type': 'application/json' };
}

function recordResult(label, res, latencyMetric) {
  const ok = check(res, {
    [`${label} status 2xx`]: r => r.status >= 200 && r.status < 300,
  });
  if (latencyMetric) latencyMetric.add(res.timings.duration);
  opSuccess.add(ok);
  if (!ok) opErrors.add(1);
  return ok;
}

// ---------------------------------------------------------------------------
// `workload` — the main write-heavy scenario
// ---------------------------------------------------------------------------

export function workload() {
  // Create agent on the first iteration (one per VU).
  const agentId = `loadagent-${__VU}`;
  if (__ITER === 0) {
    const res = http.put(`${BASE}/v1/agents/${agentId}`, JSON.stringify({
      version: 1,
      name: `Load Agent ${__VU}`,
      model: { provider: 'anthropic', name: 'claude-3-haiku' },
    }), { headers: headers(), tags: { op: 'agent_upsert' } });
    check(res, { 'agent upserted': r => r.status === 200 || r.status === 201 });
  }

  let sessionId = null;
  group('session lifecycle', () => {
    const r1 = http.post(`${BASE}/v1/sessions`, JSON.stringify({
      agent_id: agentId,
      agent_version: 1,
      metadata: { vu: __VU, iter: __ITER },
    }), { headers: headers(), tags: { op: 'session_create' } });
    if (!recordResult('session_create', r1, sessionCreateLatency)) return;
    try { sessionId = r1.json('id'); } catch (e) { sessionId = null; }
  });

  if (!sessionId) return;

  // Each VU emits ~6-10 events per iter to land near the global
  // 10 000 events/min target with default VUS=1000 and ~1s sleep.
  const eventBudget = Math.max(1, Math.floor(RATE_PER_MIN / VUS / 60));
  group('event emission', () => {
    for (let i = 0; i < eventBudget; i++) {
      const body = JSON.stringify({
        type: 'user.message',
        payload: { text: `vu-${__VU}-iter-${__ITER}-msg-${i}-${randomString(8)}` },
        metadata: { source: 'k6', cost_usd: 0.0005 },
      });
      const r = http.post(`${BASE}/v1/sessions/${sessionId}/events`, body,
        { headers: headers(), tags: { op: 'event_append' } });
      recordResult('event_append', r, eventAppendLatency);
    }
  });

  // Occasional session GET (keeps read path warm).
  if (__ITER % 5 === 0) {
    const r = http.get(`${BASE}/v1/sessions/${sessionId}`,
      { headers: headers(), tags: { op: 'session_get' } });
    recordResult('session_get', r, null);
  }

  sleep(1);
}

// ---------------------------------------------------------------------------
// `reads` — independent read-only workload exercising the JSON metrics
// summary + sessions list endpoints in parallel with writes.
// ---------------------------------------------------------------------------

export function reads() {
  const r1 = http.get(`${BASE}/v1/metrics/summary?window=1h`,
    { headers: headers(), tags: { op: 'summary' } });
  recordResult('summary', r1, summaryLatency);

  const r2 = http.get(`${BASE}/v1/sessions?limit=20`,
    { headers: headers(), tags: { op: 'sessions_list' } });
  recordResult('sessions_list', r2, null);

  const r3 = http.get(`${BASE}/health`,
    { tags: { op: 'health' } });
  recordResult('health', r3, null);
}

// ---------------------------------------------------------------------------
// Lifecycle hooks — print a final summary so operators can paste it
// straight into docs/BENCHMARKS.md.
// ---------------------------------------------------------------------------

export function handleSummary(data) {
  const out = ['', '== Wake API load summary ==', ''];
  const metrics = data.metrics;
  for (const name of [
    'http_req_duration',
    'wake_session_create_ms',
    'wake_event_append_ms',
    'wake_summary_ms',
    'http_req_failed',
    'wake_op_success_ratio',
  ]) {
    const m = metrics[name];
    if (!m) continue;
    if (m.type === 'trend') {
      out.push(
        `${name}: p50=${m.values['p(50)'].toFixed(1)}ms ` +
        `p95=${m.values['p(95)'].toFixed(1)}ms ` +
        `p99=${m.values['p(99)'].toFixed(1)}ms ` +
        `count=${m.values.count}`
      );
    } else if (m.type === 'rate') {
      out.push(`${name}: rate=${(m.values.rate * 100).toFixed(2)}%`);
    } else if (m.type === 'counter') {
      out.push(`${name}: total=${m.values.count}`);
    }
  }
  out.push('');
  return { 'stdout': out.join('\n') };
}
