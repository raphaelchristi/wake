"use client";

import { useQuery } from "@tanstack/react-query";

import { getDefaultClient } from "@/lib/api/client";
import type { Session } from "@/lib/api/types";

export function useSession(id: string | undefined) {
  return useQuery<Session>({
    queryKey: ["session", id],
    enabled: Boolean(id),
    queryFn: () => getDefaultClient().getSession(id as string),
  });
}
