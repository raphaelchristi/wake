import { describe, expect, it } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";

import { useMetrics } from "@/hooks/useMetrics";
import { useWorkers } from "@/hooks/useWorkers";
import { WakeApiClient, WakeApiError } from "@/lib/api/client";
import type { MetricsSummary, WorkerList } from "@/lib/api/metrics-types";

const SUMMARY: MetricsSummary = {
  window: {
    code: "24h",
    start: "2025-01-01T00:00:00Z",
    end: "2025-01-02T00:00:00Z",
    bucket_seconds: 1800,
  },
  latency: { p50_ms: 200, p95_ms: 800, p99_ms: 1500, samples: 12 },
  cost: { total_usd: 1.23, avg_per_session_usd: 0.1, max_session_usd: 0.4, samples: 12 },
  throughput: { sessions: 12, per_hour: 0.5 },
  errors: { count: 1, rate: 0.083, sessions_affected: 1 },
  workers_alive: 2,
  queue_depth: 0,
  series: { latency: [], cost: [], throughput: [], errors: [] },
};

function makeClient(impl: (path: string) => unknown | Promise<unknown>): WakeApiClient {
  return new WakeApiClient({
    baseUrl: "http://test",
    apiKey: "key",
    fetchImpl: ((url: URL | string) => {
      const path = typeof url === "string" ? url : url.pathname + url.search;
      return Promise.resolve()
        .then(() => impl(path))
        .then((body) => {
          if (body instanceof Error) throw body;
          return new Response(JSON.stringify(body), {
            status: 200,
            headers: { "content-type": "application/json" },
          });
        });
    }) as typeof fetch,
  });
}

describe("useMetrics", () => {
  it("transitions idle → loading → success on first load", async () => {
    const client = makeClient(() => SUMMARY);
    const { result } = renderHook(() =>
      useMetrics({ client, autoRefreshMs: null }),
    );
    await waitFor(() => expect(result.current.status).toBe("success"));
    expect(result.current.data?.latency.p50_ms).toBe(200);
  });

  it("captures errors but keeps last good data", async () => {
    let fail = false;
    const client = makeClient(() => {
      if (fail) {
        return Promise.reject(new WakeApiError("backend nope", 500, { detail: "x" }));
      }
      return SUMMARY;
    });
    const { result } = renderHook(() =>
      useMetrics({ client, autoRefreshMs: null }),
    );
    await waitFor(() => expect(result.current.status).toBe("success"));
    fail = true;
    await act(async () => {
      result.current.refresh();
    });
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.data).not.toBeNull();
    expect(result.current.error?.message).toMatch(/backend nope/);
  });
});

describe("useWorkers", () => {
  it("returns the worker list from the backend", async () => {
    const payload: WorkerList = {
      data: [
        {
          worker_id: "w-1",
          status: "alive",
          last_heartbeat_at: "2025-01-01T00:00:00Z",
          current_session_id: "s-1",
          current_sessions: ["s-1"],
        },
      ],
    };
    const client = makeClient(() => payload);
    const { result } = renderHook(() =>
      useWorkers({ client, autoRefreshMs: null }),
    );
    await waitFor(() => expect(result.current.workers).toHaveLength(1));
    expect(result.current.workers[0]?.worker_id).toBe("w-1");
  });
});
