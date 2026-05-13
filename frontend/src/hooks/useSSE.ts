"use client";

import { useEffect } from "react";

import { openSSE, type SSEEvent } from "@/lib/sse";

interface UseSSEOptions<T> {
  enabled?: boolean;
  onEvent: (event: SSEEvent<T>) => void;
  onError?: (error: Event) => void;
  onOpen?: () => void;
}

/**
 * Reactively subscribe to a Server-Sent Events stream while the component is
 * mounted. Closes the connection on unmount or url change.
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
