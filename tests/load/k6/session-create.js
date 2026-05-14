/*
 * Wake API — session-create micro-benchmark.
 *
 * Isolates POST /v1/sessions to measure the cold-path cost (advisory
 * locks, agent lookup, session row insert). Used to bisect regressions
 * suspected in the session creation hot path.
 *
 *   k6 run \
 *     -e WAKE_BASE=http://localhost:8080 \
 *     -e WAKE_API_KEY=<key> \
 *     tests/load/k6/session-create.js
 *
 * Targets:
 *   * p50 < 50ms
 *   * p95 < 200ms
 *   * p99 < 500ms
 */

import http from 'k6/http';
import { check } from 'k6';
import { Trend } from 'k6/metrics';

const BASE = __ENV.WAKE_BASE || 'http://localhost:8080';
const KEY = __ENV.WAKE_API_KEY || '';
const VUS = parseInt(__ENV.VUS || '50', 10);
const DURATION = __ENV.DURATION || '5m';

const createLatency = new Trend('wake_session_create_ms', true);

export const options = {
  vus: VUS,
  duration: DURATION,
  thresholds: {
    'wake_session_create_ms': ['p(50)<50', 'p(95)<200', 'p(99)<500'],
    'http_req_failed': ['rate<0.001'],
  },
};

function headers() {
  return KEY
    ? { 'Content-Type': 'application/json', 'X-Wake-API-Key': KEY }
    : { 'Content-Type': 'application/json' };
}

export function setup() {
  // Ensure the agent exists. Single upsert avoids race; idempotent on Wake.
  const res = http.put(`${BASE}/v1/agents/loadagent-sc`, JSON.stringify({
    version: 1,
    name: 'Session Create Loadagent',
    model: { provider: 'anthropic', name: 'claude-3-haiku' },
  }), { headers: headers() });
  check(res, { 'setup agent upserted': r => r.status === 200 || r.status === 201 });
}

export default function () {
  const res = http.post(`${BASE}/v1/sessions`, JSON.stringify({
    agent_id: 'loadagent-sc',
    agent_version: 1,
  }), { headers: headers(), tags: { op: 'session_create' } });
  check(res, { 'session created': r => r.status === 201 || r.status === 200 });
  createLatency.add(res.timings.duration);
}
