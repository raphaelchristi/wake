"use client";

import * as React from "react";

import { WakeApiError, getClient } from "@/lib/api/client";
import type { WakeApiClient } from "@/lib/api/client";
import type { AuditEntry, AuditList } from "@/lib/api/vault-types";

export interface UseAuditFilters {
  since?: string | null;
  limit?: number;
  provider?: string | null;
  host?: string | null;
  decision?: string | null;
}

export interface UseAuditOptions extends UseAuditFilters {
  client?: WakeApiClient;
  autoRefreshMs?: number | null;
}

export interface UseAuditResult {
  entries: AuditEntry[];
  isLoading: boolean;
  error: Error | null;
  offline: boolean;
  refresh: () => Promise<void>;
}

export function useAudit(options: UseAuditOptions = {}): UseAuditResult {
  const {
    since,
    limit = 200,
    provider,
    host,
    decision,
    client = getClient(),
    autoRefreshMs = 30_000,
  } = options;

  const [entries, setEntries] = React.useState<AuditEntry[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<Error | null>(null);
  const [offline, setOffline] = React.useState(false);
  const ticketRef = React.useRef(0);

  const refresh = React.useCallback(async () => {
    ticketRef.current += 1;
    const ticket = ticketRef.current;
    try {
      const data = await client.get<AuditList>("/v1/vault/audit", {
        since: since ?? undefined,
        limit,
        provider: provider ?? undefined,
        host: host ?? undefined,
        decision: decision ?? undefined,
      });
      if (ticket !== ticketRef.current) return;
      setEntries(data.data ?? []);
      setError(null);
      setOffline(false);
    } catch (err) {
      if (ticket !== ticketRef.current) return;
      if (err instanceof WakeApiError && err.status === 503) {
        setOffline(true);
        setError(err);
        return;
      }
      setError(
        err instanceof Error
          ? err
          : new Error(typeof err === "string" ? err : "unknown error"),
      );
    } finally {
      if (ticket === ticketRef.current) setIsLoading(false);
    }
  }, [client, decision, host, limit, provider, since]);

  React.useEffect(() => {
    setIsLoading(true);
    void refresh();
  }, [refresh]);

  React.useEffect(() => {
    if (!autoRefreshMs || autoRefreshMs <= 0) return;
    const id = setInterval(() => void refresh(), autoRefreshMs);
    return () => clearInterval(id);
  }, [autoRefreshMs, refresh]);

  return { entries, isLoading, error, offline, refresh };
}
