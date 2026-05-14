/**
 * Fetch the full event log for a session.
 *
 * Replay is read-mostly: we fetch once, then cache forever. SSE updates are
 * handled separately by `useSSE` (owned by dashboard-shell). When a new
 * event lands, the consumer invalidates this query.
 */
"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import type { WakeEvent } from "@/lib/replay/types";
import { useTenantScope } from "@/hooks/useTenantScope";

interface EventListResponse {
  data: WakeEvent[];
}

export function useEvents(sessionId: string | undefined): UseQueryResult<WakeEvent[]> {
  const { workspaceId } = useTenantScope();
  return useQuery({
    queryKey: ["events", workspaceId, sessionId],
    enabled: Boolean(sessionId),
    queryFn: async () => {
      const resp = await request<EventListResponse>(
        `/v1/sessions/${sessionId}/events`,
      );
      // Defensive: sort by seq even if backend returns out-of-order.
      return [...resp.data].sort((a, b) => a.seq - b.seq);
    },
    staleTime: 30_000,
  });
}
