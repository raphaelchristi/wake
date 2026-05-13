/**
 * Fetch the reconstructed sandbox state at a specific seq.
 *
 * Heavily cached by (session_id, seq): scrubbing back-and-forth must NOT
 * re-issue requests for positions we already viewed. We keep snapshots
 * effectively forever (cacheTime = Infinity) — they're tied to immutable
 * events so they never go stale.
 */
"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import type { StateAtResponse } from "@/lib/replay/types";

export function useStateAt(
  sessionId: string | undefined,
  seq: number | undefined,
): UseQueryResult<StateAtResponse> {
  return useQuery({
    queryKey: ["state-at", sessionId, seq],
    enabled: Boolean(sessionId) && typeof seq === "number" && seq >= 0,
    queryFn: () =>
      request<StateAtResponse>(`/v1/sessions/${sessionId}/state-at/${seq}`),
    staleTime: Infinity,
    gcTime: Infinity,
  });
}
