"use client";

import { useQuery } from "@tanstack/react-query";

import { getDefaultClient } from "@/lib/api/client";
import type { Session } from "@/lib/api/types";
import { useTenantScope } from "@/hooks/useTenantScope";

export function useSession(id: string | undefined) {
  const { workspaceId } = useTenantScope();
  return useQuery<Session>({
    queryKey: ["session", workspaceId, id],
    enabled: Boolean(id),
    queryFn: () => getDefaultClient().getSession(id as string),
  });
}
