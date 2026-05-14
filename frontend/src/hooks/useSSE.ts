"use client";

import { useEffect, useMemo } from "react";

import { openSSE, sseUrlForSession, type SSEEvent } from "@/lib/sse";
import { useTenantScope } from "@/hooks/useTenantScope";

interface UseSSEOptions<T> {
  enabled?: boolean;
  onEvent: (event: SSEEvent<T>) => void;
  onError?: (error: Event) => void;
  onOpen?: () => void;
}

/**
 * Reactively subscribe to a Server-Sent Events stream while the component is
 * mounted. Closes the connection on unmount or url change.
 *
 * Aceita uma URL absoluta ou caminho relativo. Para o caso comum de uma
 * sessão Wake, prefira `useSessionSSE(sessionId, ...)` que monta a URL
 * via `sseUrlForSession()` carregando o scope tenant atual.
 */
export function useSSE<T = unknown>(url: string | null, options: UseSSEOptions<T>): void {
  const enabled = options.enabled ?? true;
  useEffect(() => {
    if (!enabled || !url) return undefined;
    const close = openSSE(url, {
      onEvent: (event) => options.onEvent(event as unknown as SSEEvent<T>),
      onError: options.onError,
      onOpen: options.onOpen,
    });
    return close;
    // We intentionally only depend on url + enabled. Callers should memoise
    // their callbacks if they care about stability.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, enabled]);
}

/**
 * Wrapper conveniente: abre SSE contra a rota Next.js de proxy para
 * a sessão dada, carregando `org`/`ws` do scope tenant atual. Reconnect
 * automático quando o workspace muda (a URL muda → effect re-roda).
 */
export function useSessionSSE<T = unknown>(
  sessionId: string | null | undefined,
  options: UseSSEOptions<T>,
): void {
  const { organizationId, workspaceId } = useTenantScope();
  const url = useMemo(() => {
    if (!sessionId) return null;
    return sseUrlForSession(sessionId, { organizationId, workspaceId });
  }, [sessionId, organizationId, workspaceId]);
  useSSE<T>(url, options);
}
