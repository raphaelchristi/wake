"use client";

import { useQuery } from "@tanstack/react-query";

import { getDefaultClient } from "@/lib/api/client";
import type { SessionList, SessionListQuery } from "@/lib/api/types";

const SESSIONS_QUERY_KEY = "sessions";

export function useSessions(query: SessionListQuery = {}) {
  return useQuery<SessionList>({
    queryKey: [SESSIONS_QUERY_KEY, query],
    queryFn: () => getDefaultClient().listSessions(query),
    refetchInterval: 5_000, // poll while page is open; SSE upgrade in replay slice
  });
}
