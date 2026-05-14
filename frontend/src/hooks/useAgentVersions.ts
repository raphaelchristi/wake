/**
 * useAgentVersions — read + mutate the agent version history.
 *
 * Phase 8 / Tier 2 gap #12. Wraps:
 *   - GET   /v1/agents/{id}/versions       → list (oldest first)
 *   - PATCH /v1/agents/{id}                → new version w/ canary metadata
 *
 * The dashboard versioning page renders a timeline of versions with
 * adjacent diff + a canary slider. We split into two hooks so the diff
 * + slider components can subscribe independently.
 */
"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import type { AgentConfig } from "@/lib/api/types";
import { useTenantScope } from "@/hooks/useTenantScope";

interface VersionListResponse {
  data: AgentConfig[];
}

/**
 * Fetch all versions for `agentId`. Returns oldest first — same order
 * the backend `AgentStore.list_versions` emits.
 */
export function useAgentVersions(
  agentId: string | undefined,
): UseQueryResult<AgentConfig[]> {
  const { workspaceId } = useTenantScope();
  return useQuery({
    queryKey: ["agent-versions", workspaceId, agentId],
    enabled: Boolean(agentId),
    queryFn: async () => {
      const resp = await request<VersionListResponse>(
        `/v1/agents/${agentId}/versions`,
      );
      return [...resp.data].sort((a, b) => a.version - b.version);
    },
    staleTime: 15_000,
  });
}

export interface CanaryUpdate {
  /** New canary weight 0-100. `null` removes the canary key entirely. */
  weight: number | null;
}

/**
 * Set / clear the canary weight on the agent. The backend stores it as
 * a metadata string; we serialise / strip here so the slider component
 * stays UI-only.
 *
 * Backend contract: PATCH /v1/agents/{id} with `metadata` REPLACES the
 * full metadata map. We merge with the current version's metadata so
 * callers don't accidentally wipe e.g. `max_steps` or `tags`.
 */
export function useApplyCanary(
  agentId: string | undefined,
  currentMetadata: Record<string, string> | undefined,
): UseMutationResult<AgentConfig, Error, CanaryUpdate> {
  const queryClient = useQueryClient();
  const { workspaceId } = useTenantScope();
  return useMutation<AgentConfig, Error, CanaryUpdate>({
    mutationKey: ["apply-canary", workspaceId, agentId],
    mutationFn: async ({ weight }: CanaryUpdate) => {
      if (!agentId) throw new Error("useApplyCanary: missing agentId");
      const merged: Record<string, string> = { ...(currentMetadata ?? {}) };
      if (weight === null) {
        delete merged.canary_weight;
      } else {
        const clamped = Math.max(0, Math.min(100, Math.round(weight)));
        merged.canary_weight = String(clamped);
      }
      return request<AgentConfig>("PATCH", `/v1/agents/${agentId}`, {
        body: { metadata: merged },
      });
    },
    onSuccess: async () => {
      // Invalidate version history so the new canary row appears.
      await queryClient.invalidateQueries({
        queryKey: ["agent-versions", workspaceId, agentId],
      });
    },
  });
}
