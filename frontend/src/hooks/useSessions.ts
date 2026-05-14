"use client";

import { useQuery } from "@tanstack/react-query";

import { getDefaultClient } from "@/lib/api/client";
import type { SessionList, SessionListQuery } from "@/lib/api/types";
import { useTenantScope } from "@/hooks/useTenantScope";

const SESSIONS_QUERY_KEY = "sessions";

export function useSessions(query: SessionListQuery = {}) {
  const { workspaceId } = useTenantScope();
  return useQuery<SessionList>({
    // Tenancy: workspaceId entra como 2º elemento da key para que cada
    // workspace tenha cache isolado. Trocar workspace gera key nova
    // (e o provider chama queryClient.clear() de qualquer jeito).
    queryKey: [SESSIONS_QUERY_KEY, workspaceId, query],
    queryFn: () => getDefaultClient().listSessions(query),
    refetchInterval: 5_000, // poll while page is open; SSE upgrade in replay slice
  });
}
