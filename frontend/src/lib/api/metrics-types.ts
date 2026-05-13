// Type definitions mirroring the backend metrics + workers route payloads.
// These intentionally live in their own file (separate from the OpenAPI-
// generated `types.ts` shell will land) so they survive the shell merge as
// hand-written helpers used inside this slice.

export type MetricsWindow = "1h" | "24h" | "7d" | "30d";

export interface MetricsWindowMeta {
  code: MetricsWindow | string;
  start: string;
  end: string;
  bucket_seconds: number;
}

export interface MetricsLatency {
  p50_ms: number;
  p95_ms: number;
  p99_ms: number;
  samples: number;
}

export interface MetricsCost {
  total_usd: number;
  avg_per_session_usd: number;
  max_session_usd: number;
  samples: number;
}

export interface MetricsThroughput {
  sessions: number;
  per_hour: number;
}

export interface MetricsErrors {
  count: number;
  rate: number;
  sessions_affected: number;
}

export interface LatencyPoint {
  t: string;
  p50: number;
  p95: number;
  p99: number;
}

export interface CostPoint {
  t: string;
  cost_usd: number;
}

export interface ThroughputPoint {
  t: string;
  sessions: number;
}

export interface ErrorPoint {
  t: string;
  errors: number;
}

export interface MetricsSummary {
  window: MetricsWindowMeta;
  latency: MetricsLatency;
  cost: MetricsCost;
  throughput: MetricsThroughput;
  errors: MetricsErrors;
  workers_alive: number;
  queue_depth: number;
  series: {
    latency: LatencyPoint[];
    cost: CostPoint[];
    throughput: ThroughputPoint[];
    errors: ErrorPoint[];
  };
}

export type WorkerStatus = "alive" | "stale" | "idle";

export interface Worker {
  worker_id: string;
  status: WorkerStatus;
  last_heartbeat_at: string | null;
  current_session_id: string | null;
  current_sessions: string[];
}

export interface WorkerList {
  data: Worker[];
}
