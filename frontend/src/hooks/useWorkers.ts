"use client";

import * as React from "react";

import { getClient } from "@/lib/api/client";
import type { WakeApiClient } from "@/lib/api/client";
import type { Worker, WorkerList } from "@/lib/api/metrics-types";
import { useTenantScope } from "@/hooks/useTenantScope";

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

/**
 * Tenancy isolation (Codex review MEDIUM #3 — Phase 6):
 *   - Em mudança de workspace o array `workers` é resetado para `[]` e
 *     `isLoading` volta a `true` ANTES do próximo fetch. Sem isso, o user
 *     veria a worker list de workspace A enquanto o B carrega — vazamento
 *     de dados operacionais entre tenants no mesmo browser session.
 */
export function useWorkers(options: UseWorkersOptions = {}): UseWorkersResult {
  const autoRefreshMs =
    options.autoRefreshMs === undefined ? 15_000 : options.autoRefreshMs;
  const client = options.client ?? getClient();
  // Tenancy: dispara re-load quando o workspace muda.
  const { workspaceId } = useTenantScope();

  const [workers, setWorkers] = React.useState<Worker[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);
  const [isFetching, setIsFetching] = React.useState(false);
  const [error, setError] = React.useState<Error | null>(null);
  const ticketRef = React.useRef(0);
  // Workspace do último fetch — usado para detectar troca e descartar
  // workers do tenant anterior antes do próximo fetch.
  const lastWorkspaceRef = React.useRef<string | null>(null);

  const load = React.useCallback(async () => {
    ticketRef.current += 1;
    const ticket = ticketRef.current;
    const previousWorkspace = lastWorkspaceRef.current;
    const workspaceChanged =
      previousWorkspace !== null && previousWorkspace !== workspaceId;
    lastWorkspaceRef.current = workspaceId;
    setIsFetching(true);
    if (workspaceChanged) {
      // Reset imediato: nenhum dado do workspace anterior continua visível
      // enquanto o fetch do novo workspace estiver inflight.
      setWorkers([]);
      setError(null);
      setIsLoading(true);
    }
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
      // Em erro durante workspace change, mantém o reset (workers já é [])
      // para não exibir lista antiga junto com o erro.
    } finally {
      if (ticket === ticketRef.current) {
        setIsLoading(false);
        setIsFetching(false);
      }
    }
  }, [client, workspaceId]);

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
