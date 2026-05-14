"use client";

import * as React from "react";

import { WakeApiError, getClient } from "@/lib/api/client";
import type { WakeApiClient } from "@/lib/api/client";
import type {
  MetricsSummary,
  MetricsWindow,
} from "@/lib/api/metrics-types";
import { useTenantScope } from "@/hooks/useTenantScope";

export type UseMetricsState =
  | { status: "idle"; data: null; error: null }
  | { status: "loading"; data: MetricsSummary | null; error: null }
  | { status: "success"; data: MetricsSummary; error: null }
  | { status: "error"; data: MetricsSummary | null; error: Error };

export interface UseMetricsOptions {
  window?: MetricsWindow;
  autoRefreshMs?: number | null;
  client?: WakeApiClient;
}

/**
 * Fetches `/v1/metrics/summary?window=<window>` and exposes a small state
 * machine plus a `refresh()` callback. Auto-refreshes every
 * `autoRefreshMs` (default 30s; pass null to disable).
 *
 * The shell slice will eventually wire TanStack Query in; until then this
 * hook is intentionally dependency-free so it works on a bare Next app.
 */
export function useMetrics(
  options: UseMetricsOptions = {},
): UseMetricsState & { refresh: () => void; isFetching: boolean } {
  const window = options.window ?? "24h";
  const autoRefreshMs = options.autoRefreshMs === undefined ? 30_000 : options.autoRefreshMs;
  const client = options.client ?? getClient();
  // Tenancy: a workspaceId reativa entra como dep do `load` para que
  // mudar de workspace dispare um novo fetch (o client já injeta o header
  // novo via `getTenantScope()`). Equivalente lógico a uma queryKey.
  const { workspaceId } = useTenantScope();

  const [state, setState] = React.useState<UseMetricsState>({
    status: "idle",
    data: null,
    error: null,
  });
  const [isFetching, setIsFetching] = React.useState(false);
  const lastTriggerRef = React.useRef(0);

  const load = React.useCallback(async () => {
    lastTriggerRef.current += 1;
    const ticket = lastTriggerRef.current;
    setIsFetching(true);
    setState((prev) =>
      prev.status === "success"
        ? { status: "loading", data: prev.data, error: null }
        : { status: "loading", data: null, error: null },
    );
    try {
      const data = await client.get<MetricsSummary>("/v1/metrics/summary", {
        window,
      });
      if (ticket !== lastTriggerRef.current) return;
      setState({ status: "success", data, error: null });
    } catch (err) {
      if (ticket !== lastTriggerRef.current) return;
      const error =
        err instanceof Error
          ? err
          : new Error(typeof err === "string" ? err : "unknown error");
      setState((prev) => ({ status: "error", data: prev.data, error }));
    } finally {
      if (ticket === lastTriggerRef.current) setIsFetching(false);
    }
    // workspaceId é referenciada apenas para acionar re-fetch em troca de
    // workspace; o valor real entra no header via client.headers().
    void workspaceId;
  }, [client, window, workspaceId]);

  React.useEffect(() => {
    void load();
  }, [load]);

  React.useEffect(() => {
    if (!autoRefreshMs || autoRefreshMs <= 0) return;
    const id = window === "1h" ? setInterval(load, autoRefreshMs) : setInterval(load, autoRefreshMs);
    return () => clearInterval(id);
  }, [autoRefreshMs, load, window]);

  return { ...state, refresh: load, isFetching };
}

/** Stable detection of `WakeApiError` for callers that want to branch on auth. */
export function isAuthError(error: unknown): boolean {
  return error instanceof WakeApiError && error.isAuthError;
}
