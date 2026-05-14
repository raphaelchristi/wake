import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";

import { useMetrics } from "@/hooks/useMetrics";
import { useWorkers } from "@/hooks/useWorkers";
import { WakeApiClient, WakeApiError } from "@/lib/api/client";
import type { MetricsSummary, WorkerList } from "@/lib/api/metrics-types";
import { setTenantScope, clearTenantScope } from "@/lib/tenant";

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

// Helper: cria uma Promise com handle externo (resolve callable).
function deferred<T>(): { promise: Promise<T>; resolve: (v: T) => void } {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

// Regressão: Codex review MEDIUM #3 (Phase 6 fixes). Hooks fora do
// TanStack mantinham `prev.data` / `workers` ao trocar de workspace,
// vazando dados do tenant anterior. Após o fix, mudar `workspaceId`
// deve resetar imediatamente o state local antes do próximo fetch.
describe("workspace switching — local cache hygiene", () => {
  beforeEach(() => {
    clearTenantScope();
    setTenantScope({ organizationId: "org-a", workspaceId: "ws-a" });
  });

  afterEach(() => {
    clearTenantScope();
  });

  it("useMetrics drops prev.data when workspace changes", async () => {
    // Resposta por workspace — usa o tenant header do request real.
    const summaryFor = (p50: number): MetricsSummary => ({
      ...SUMMARY,
      latency: { p50_ms: p50, p95_ms: 800, p99_ms: 1500, samples: 12 },
    });
    const summaryByWorkspace: Record<string, MetricsSummary> = {
      default: summaryFor(50), // fetch antes do hydrate do tenant
      "ws-a": summaryFor(100),
      "ws-b": summaryFor(999),
    };

    // Sinaliza entrada do fetch ws-b + handle de release.
    const wsBStarted = deferred<void>();
    let releaseWsBFetch: (() => void) | null = null;

    const client = new WakeApiClient({
      baseUrl: "http://test",
      apiKey: "key",
      fetchImpl: (async (_url, init) => {
        const headers = new Headers(init?.headers ?? {});
        const ws = headers.get("X-Wake-Workspace-Id") ?? "default";
        if (ws === "ws-b") {
          wsBStarted.resolve();
          await new Promise<void>((resolve) => {
            releaseWsBFetch = resolve;
          });
        }
        const body = summaryByWorkspace[ws] ?? summaryFor(0);
        return new Response(JSON.stringify(body), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }) as typeof fetch,
    });

    const { result } = renderHook(() =>
      useMetrics({ client, autoRefreshMs: null }),
    );

    // 1) Workspace A carrega (após hydrate). p50 = 100 confirma que o
    //    fetch real do ws-a completou.
    await waitFor(() =>
      expect(result.current.data?.latency.p50_ms).toBe(100),
    );
    expect(result.current.status).toBe("success");

    // 2) Troca para workspace B (fetch ficará pendurado até release).
    await act(async () => {
      setTenantScope({ workspaceId: "ws-b" });
    });
    await wsBStarted.promise;

    // 3) Durante o fetch in-flight do ws-b, `data` deve ser null —
    //    p50=100 do ws-a NÃO pode permanecer visível.
    await waitFor(() => {
      expect(result.current.status).toBe("loading");
    });
    expect(result.current.data).toBeNull();

    // 4) Libera e confirma resultado final.
    if (releaseWsBFetch) (releaseWsBFetch as () => void)();
    await waitFor(() =>
      expect(result.current.data?.latency.p50_ms).toBe(999),
    );
  });

  it("useWorkers drops previous workers array when workspace changes", async () => {
    const listByWorkspace: Record<string, WorkerList> = {
      default: { data: [] },
      "ws-a": {
        data: [
          {
            worker_id: "ws-a-worker",
            status: "alive",
            last_heartbeat_at: "2025-01-01T00:00:00Z",
            current_session_id: null,
            current_sessions: [],
          },
        ],
      },
      "ws-b": {
        data: [
          {
            worker_id: "ws-b-worker",
            status: "alive",
            last_heartbeat_at: "2025-01-01T00:00:00Z",
            current_session_id: null,
            current_sessions: [],
          },
        ],
      },
    };

    const wsBStarted = deferred<void>();
    let releaseWsBFetch: (() => void) | null = null;

    const client = new WakeApiClient({
      baseUrl: "http://test",
      apiKey: "key",
      fetchImpl: (async (_url, init) => {
        const headers = new Headers(init?.headers ?? {});
        const ws = headers.get("X-Wake-Workspace-Id") ?? "default";
        if (ws === "ws-b") {
          wsBStarted.resolve();
          await new Promise<void>((resolve) => {
            releaseWsBFetch = resolve;
          });
        }
        const body = listByWorkspace[ws] ?? { data: [] };
        return new Response(JSON.stringify(body), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }) as typeof fetch,
    });

    const { result } = renderHook(() =>
      useWorkers({ client, autoRefreshMs: null }),
    );

    // 1) Workspace A carrega — ws-a-worker presente.
    await waitFor(() => {
      expect(result.current.workers[0]?.worker_id).toBe("ws-a-worker");
    });

    // 2) Troca para workspace B (fetch pendurado).
    await act(async () => {
      setTenantScope({ workspaceId: "ws-b" });
    });
    await wsBStarted.promise;

    // 3) Workers do ws-a NÃO podem aparecer durante o fetch do ws-b.
    await waitFor(() => {
      expect(result.current.workers).toEqual([]);
    });
    expect(result.current.isLoading).toBe(true);

    // 4) Libera e confirma resultado final.
    if (releaseWsBFetch) (releaseWsBFetch as () => void)();
    await waitFor(() => {
      expect(result.current.workers[0]?.worker_id).toBe("ws-b-worker");
    });
  });
});
