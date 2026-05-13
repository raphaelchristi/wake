"use client";

import * as React from "react";

import { WakeApiClient, WakeApiError, getClient } from "@/lib/api/client";
import type {
  CredentialList,
  OAuthStartRequest,
  OAuthStartResponse,
  RotateRequest,
  VaultCredential,
} from "@/lib/api/vault-types";

export type VaultStatus = "ready" | "loading" | "offline" | "unauthorized" | "error";

export interface UseCredentialsResult {
  credentials: VaultCredential[];
  status: VaultStatus;
  error: Error | null;
  refresh: () => Promise<void>;
  startOAuth: (req: OAuthStartRequest) => Promise<OAuthStartResponse>;
  rotate: (vaultId: string, req?: RotateRequest) => Promise<OAuthStartResponse>;
  revoke: (vaultId: string) => Promise<void>;
}

export interface UseCredentialsOptions {
  client?: WakeApiClient;
  autoRefreshMs?: number | null;
}

/**
 * Drives the vault list. Translates HTTP failures into a coarse
 * `VaultStatus` so the UI can render "offline" without confusing it for
 * a generic 500. The backend explicitly returns 503 when no vault
 * adapter is wired — see `wake.api.routes.vault`.
 */
export function useCredentials(
  options: UseCredentialsOptions = {},
): UseCredentialsResult {
  const client = options.client ?? getClient();
  const autoRefreshMs =
    options.autoRefreshMs === undefined ? 60_000 : options.autoRefreshMs;

  const [credentials, setCredentials] = React.useState<VaultCredential[]>([]);
  const [status, setStatus] = React.useState<VaultStatus>("loading");
  const [error, setError] = React.useState<Error | null>(null);
  const ticketRef = React.useRef(0);

  const refresh = React.useCallback(async () => {
    ticketRef.current += 1;
    const ticket = ticketRef.current;
    setStatus((prev) => (prev === "ready" ? prev : "loading"));
    try {
      const data = await client.get<CredentialList>("/v1/vault/credentials");
      if (ticket !== ticketRef.current) return;
      setCredentials(data.data ?? []);
      setError(null);
      setStatus("ready");
    } catch (err) {
      if (ticket !== ticketRef.current) return;
      if (err instanceof WakeApiError) {
        if (err.status === 503) {
          setStatus("offline");
          setError(err);
          return;
        }
        if (err.isAuthError) {
          setStatus("unauthorized");
          setError(err);
          return;
        }
      }
      setStatus("error");
      setError(
        err instanceof Error
          ? err
          : new Error(typeof err === "string" ? err : "unknown error"),
      );
    }
  }, [client]);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  React.useEffect(() => {
    if (!autoRefreshMs || autoRefreshMs <= 0) return;
    const id = setInterval(() => void refresh(), autoRefreshMs);
    return () => clearInterval(id);
  }, [autoRefreshMs, refresh]);

  const startOAuth = React.useCallback(
    async (req: OAuthStartRequest) =>
      client.post<OAuthStartResponse>("/v1/vault/oauth/start", req),
    [client],
  );

  const rotate = React.useCallback(
    async (vaultId: string, req: RotateRequest = {}) =>
      client.post<OAuthStartResponse>(`/v1/vault/credentials/${vaultId}/rotate`, req),
    [client],
  );

  const revoke = React.useCallback(
    async (vaultId: string) => {
      await client.delete<void>(`/v1/vault/credentials/${vaultId}`);
      await refresh();
    },
    [client, refresh],
  );

  return {
    credentials,
    status,
    error,
    refresh,
    startOAuth,
    rotate,
    revoke,
  };
}
