/*
 * Wake API — event-append micro-benchmark.
 *
 * Isolates POST /v1/sessions/{id}/events to measure the hot path most
 * sensitive to event-log throughput (Postgres index pressure, NOTIFY
 * fan-out cost, idempotency UNIQUE check overhead).
 *
 * Each VU creates ONE session in setup() then loops emitting events
 * into it. Shared session-id keeps the test focused on append latency
 * rather than session creation.
 *
 *   k6 run \
 *     -e WAKE_BASE=http://localhost:8080 \
 *     -e WAKE_API_KEY=<key> \
 *     tests/load/k6/event-append.js
 *
 * Targets:
 *   * p50 < 20ms
 *   * p95 < 100ms
 *   * p99 < 300ms
 *   * sustained throughput >= 5000 events/min/VU group
 */

import http from 'k6/http';
import { check } from 'k6';
import { Trend, Counter } from 'k6/metrics';
import { randomString } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js';

const BASE = __ENV.WAKE_BASE || 'http://localhost:8080';
const KEY = __ENV.WAKE_API_KEY || '';
const VUS = parseInt(__ENV.VUS || '100', 10);
const DURATION = __ENV.DURATION || '10m';

const appendLatency = new Trend('wake_event_append_ms', true);
const appendCount = new Counter('wake_events_appended');

export const options = {
  vus: VUS,
  duration: DURATION,
  thresholds: {
    'wake_event_append_ms': ['p(50)<20', 'p(95)<100', 'p(99)<300'],
    'http_req_failed': ['rate<0.001'],
  },
};

function headers() {
  return KEY
    ? { 'Content-Type': 'application/json', 'X-Wake-API-Key': KEY }
    : { 'Content-Type': 'application/json' };
}

export function setup() {
  // Single shared agent for the run.
  const r = http.put(`${BASE}/v1/agents/loadagent-ea`, JSON.stringify({
    version: 1,
    name: 'Event Append Loadagent',
    model: { provider: 'anthropic', name: 'claude-3-haiku' },
  }), { headers: headers() });
  check(r, { 'setup agent upserted': res => res.status < 400 });
  // One shared session for every VU (writes can still parallelise
  // because per-session locks are advisory at the row level in Wake).
  const s = http.post(`${BASE}/v1/sessions`, JSON.stringify({
    agent_id: 'loadagent-ea',
    agent_version: 1,
    metadata: { source: 'k6-event-append' },
  }), { headers: headers() });
  check(s, { 'setup session created': res => res.status < 400 });
  return { sessionId: s.json('id') };
}

export default function (data) {
  if (!data || !data.sessionId) return;
  const body = JSON.stringify({
    type: 'user.message',
    payload: { text: `k6-${__VU}-${__ITER}-${randomString(16)}` },
    metadata: { source: 'k6', cost_usd: 0.0002 },
  });
  const res = http.post(`${BASE}/v1/sessions/${data.sessionId}/events`,
    body, { headers: headers(), tags: { op: 'event_append' } });
  check(res, { 'event appended': r => r.status < 400 });
  appendLatency.add(res.timings.duration);
  appendCount.add(1);
}
