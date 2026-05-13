"use client";

import * as React from "react";

import { getClient } from "@/lib/api/client";
import type { WakeApiClient } from "@/lib/api/client";
import type { Worker, WorkerList } from "@/lib/api/metrics-types";

export interface UseWorkersOptions {
  autoRefreshMs?: number | null;
  client?: WakeApiClient;
}

export interface UseWorkersResult {
  workers: Worker[];
  isLoading: boolean;
  isFetching: boolean;
  error: Error | null;
  refresh: () => void;
}

export function useWorkers(options: UseWorkersOptions = {}): UseWorkersResult {
  const autoRefreshMs =
    options.autoRefreshMs === undefined ? 15_000 : options.autoRefreshMs;
  const client = options.client ?? getClient();

  const [workers, setWorkers] = React.useState<Worker[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);
  const [isFetching, setIsFetching] = React.useState(false);
  const [error, setError] = React.useState<Error | null>(null);
  const ticketRef = React.useRef(0);

  const load = React.useCallback(async () => {
    ticketRef.current += 1;
    const ticket = ticketRef.current;
    setIsFetching(true);
    try {
      const data = await client.get<WorkerList>("/v1/workers");
      if (ticket !== ticketRef.current) return;
      setWorkers(data.data ?? []);
      setError(null);
    } catch (err) {
      if (ticket !== ticketRef.current) return;
      setError(
        err instanceof Error
          ? err
          : new Error(typeof err === "string" ? err : "unknown error"),
      );
    } finally {
      if (ticket === ticketRef.current) {
        setIsLoading(false);
        setIsFetching(false);
      }
    }
  }, [client]);

  React.useEffect(() => {
    void load();
  }, [load]);

  React.useEffect(() => {
    if (!autoRefreshMs || autoRefreshMs <= 0) return;
    const id = setInterval(load, autoRefreshMs);
    return () => clearInterval(id);
  }, [autoRefreshMs, load]);

  return { workers, isLoading, isFetching, error, refresh: load };
}
